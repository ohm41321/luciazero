"""Shared test fixtures: disposable git repositories for the M3 worktree
rules, and the few things a test must do differently on Windows -- start a
fake provider, ask whether a file is private, look at a process, and give a
command a terminal of its own.

Every repository lives under a temporary directory the test owns and git
runs with the fixture's own identity, never the developer's config."""

from __future__ import annotations

import io
import os
import platform
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

WINDOWS = sys.platform == "win32"
#: What a pseudo console paints with besides text; stripped to read its screen.
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[=>()][0-9A-Za-z]?")

GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="fixture",
    GIT_AUTHOR_EMAIL="fixture@example.invalid",
    GIT_COMMITTER_NAME="fixture",
    GIT_COMMITTER_EMAIL="fixture@example.invalid",
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_TERMINAL_PROMPT="0",
)


def git(path: str | Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=GIT_ENV)
    return result.stdout.strip()


def make_repo(path: str | Path, *, branch: str = "main") -> str:
    """Create a repository with one commit holding README.md and
    reports/x.md; returns the real toplevel path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True, capture_output=True, env=GIT_ENV)
    # Unique content: two fixtures made in the same second with identical
    # trees, identity, and message would otherwise share commit ids. Every
    # file is written byte for byte (newline=""): tests count its bytes, and
    # text mode on Windows would turn each \n into \r\n.
    (path / "README.md").write_text(f"fixture {path.name} {uuid.uuid4().hex}\n", encoding="utf-8", newline="")
    (path / "reports").mkdir(exist_ok=True)
    (path / "reports" / "x.md").write_text("# report\n", encoding="utf-8", newline="")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fixture")
    return os.path.realpath(str(path))


def commit_file(repo: str | Path, name: str, content: str) -> str:
    """Write ``name`` in ``repo``, commit it, and return the new HEAD oid."""
    target = Path(repo) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


def remove_tree(path: str | Path) -> None:
    """shutil.rmtree that also removes read-only files. Git writes its
    objects read-only, and on Windows a read-only file cannot be deleted."""
    def writable_and_again(function, target, *_):
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        function(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable_and_again)
    else:
        shutil.rmtree(path, onerror=writable_and_again)


def fake_cli(path: Path, body: str) -> str:
    """An executable stand-in for a provider CLI, written in Python; returns
    the command that starts it.

    POSIX: a script with a shebang. Windows has no shebang: a pip-installed
    CLI there is a launcher .exe with its script zipped behind it, so that is
    what this builds, from the launcher pip itself ships. Every argument then
    reaches the script exactly as given, which a .cmd wrapper cannot promise.
    """
    if not WINDOWS:
        path.write_text("#!" + sys.executable + "\n" + body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)
    import pkgutil
    arm = platform.machine().lower() in ("arm64", "aarch64")
    launcher = pkgutil.get_data("pip._vendor.distlib",
                                "t64-arm.exe" if arm else "t64.exe" if struct.calcsize("P") == 8 else "t32.exe")
    if launcher is None:
        raise RuntimeError("pip's script launcher is missing; cannot build a fake provider")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("__main__.py", body)
    exe = path.with_name(path.name + ".exe")
    exe.write_bytes(launcher + b'#!"' + sys.executable.encode("utf-8") + b'"\r\n' + archive.getvalue())
    return str(exe)


def private_problem(path: str | Path) -> Optional[str]:
    """Why `path` is not private to this user, or None when it is.

    POSIX: mode 0600 for a file, 0700 for a directory. Windows: the mode bits
    say nothing, so the DACL itself is read -- protected, so nothing above it
    is inherited, and allowing this user and SYSTEM alone.
    """
    path = str(path)
    if not WINDOWS:
        want = 0o700 if os.path.isdir(path) else 0o600
        mode = stat.S_IMODE(os.stat(path).st_mode)
        return None if mode == want else f"mode {oct(mode)}, not {oct(want)}"
    from luciazero_agentd import winproc
    sddl = dacl_sddl(path)
    flags = re.match(r"D:([A-Z_]*)", sddl)
    if flags is None or "P" not in re.sub(r"AI|AR|NO_ACCESS_CONTROL", "", flags.group(1)):
        return f"the DACL is not protected: {sddl}"
    mine = str(winproc._my_sid())
    trustees = []
    for kind, flags, sid in dacl_entries(path):
        if kind != ACCESS_ALLOWED_ACE_TYPE or flags & INHERITED_ACE:
            return f"an entry of type {kind}, flags {flags:#x}, is not an explicit allow entry: {sddl}"
        trustees.append(sid)
    if sorted(trustees) != sorted([mine, SYSTEM_SID]):
        return f"admits {trustees}, not this user ({mine}) and SYSTEM alone: {sddl}"
    return None


ACCESS_ALLOWED_ACE_TYPE = 0
INHERITED_ACE = 0x10
SYSTEM_SID = "S-1-5-18"


def dacl_entries(path: str | Path) -> list[tuple[int, int, Optional[str]]]:
    """Windows: each entry of a path's DACL as (type, flags, SID string).

    Read from the binary ACL, not from SDDL: SDDL writes a well-known account
    as an alias -- SY, BA, or LA for the machine's built-in Administrator --
    and an alias says which account an entry names, not whether that account
    is the one running. ConvertSidToStringSidW always gives S-1-... form. The
    SID is None for an entry type that does not keep it where an allow entry
    does; the caller refuses those anyway."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read = advapi32.GetNamedSecurityInfoW
    read.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD] + [ctypes.c_void_p] * 2 \
        + [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    read.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    se_file_object, dacl_information = 1, 0x4
    dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
    error = read(str(path), se_file_object, dacl_information, None, None, ctypes.byref(dacl), None,
                 ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        if not dacl.value:
            raise AssertionError(f"{path} has no DACL at all, which admits everyone")
        # ACL header: revision, padding, size (WORD), entry count (WORD).
        count = struct.unpack_from("<BBHH", ctypes.string_at(dacl.value, 8))[3]
        entries: list[tuple[int, int, Optional[str]]] = []
        for index in range(count):
            ace = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                raise ctypes.WinError(ctypes.get_last_error())
            kind, flags, _ = struct.unpack_from("<BBH", ctypes.string_at(ace.value, 4))
            sid = None
            if kind == ACCESS_ALLOWED_ACE_TYPE:
                # ACCESS_ALLOWED_ACE: the header, the access mask, then the SID.
                text = wintypes.LPWSTR()
                if not advapi32.ConvertSidToStringSidW(ace.value + 8, ctypes.byref(text)):
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    sid = text.value
                finally:
                    kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
            entries.append((kind, flags, sid))
        return entries
    finally:
        kernel32.LocalFree(descriptor)


def set_dacl(path: str | Path, sddl: str) -> None:
    """Windows: replace a path's DACL with the one `sddl` describes. SDDL, not
    icacls, so a test can name an account by its alias."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    parse = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    parse.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    parse.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    write = advapi32.SetNamedSecurityInfoW
    write.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD] + [ctypes.c_void_p] * 4
    write.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    se_file_object, dacl_information, protected_dacl_information = 1, 0x4, 0x80000000
    descriptor = ctypes.c_void_p()
    if not parse(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl),
                                                  ctypes.byref(defaulted)) or not present:
            raise ctypes.WinError(ctypes.get_last_error())
        error = write(str(path), se_file_object, dacl_information | protected_dacl_information,
                      None, None, dacl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        kernel32.LocalFree(descriptor)


def dacl_sddl(path: str | Path) -> str:
    """Windows: the DACL of a file or directory, as SDDL."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    read = advapi32.GetNamedSecurityInfoW
    read.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD] + [ctypes.c_void_p] * 4 \
        + [ctypes.POINTER(ctypes.c_void_p)]
    read.restype = wintypes.DWORD
    text = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    text.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                     ctypes.c_void_p]
    text.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    se_file_object, dacl_information = 1, 0x4
    descriptor = ctypes.c_void_p()
    error = read(str(path), se_file_object, dacl_information, None, None, None, None, ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        out = ctypes.c_void_p()
        if not text(descriptor, 1, dacl_information, ctypes.byref(out), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.wstring_at(out.value)
        finally:
            kernel32.LocalFree(out)
    finally:
        kernel32.LocalFree(descriptor)


def pid_running(pid: int) -> bool:
    """Whether a process is still there. Never os.kill(pid, 0) on Windows:
    there signal 0 is CTRL_C_EVENT."""
    if WINDOWS:
        from luciazero_agentd import winproc
        return winproc.exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_pid(pid: int) -> None:
    """End one process now, ignoring one that is already gone."""
    try:
        if WINDOWS:
            from luciazero_agentd import winproc
            winproc.kill(pid)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class OnConsole:
    """Windows: a command on a pseudo console of its own -- what a person's
    terminal is there -- with everything it paints collected as it comes.

    It stands in for a pty wherever a test needs a terminal: for a command
    that refuses a pipe (`approve`, `claim`) and for `run`, which proxies one.
    """

    def __init__(self, argv: list[str], env: dict[str, str]) -> None:
        from luciazero_agentd import conpty
        self.session = conpty.Session(argv, env)
        self._chunks: list[bytes] = []
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self) -> None:
        for chunk in iter(self.session.read, b""):
            self._chunks.append(chunk)

    def screen(self) -> str:
        """Everything painted so far, as text. Decoded whole, so a character
        or an escape sequence split across two reads is still one."""
        return ANSI.sub("", b"".join(self._chunks).decode("utf-8", "replace"))

    def type(self, keys: str) -> None:
        self.session.write(keys.encode("utf-8"))

    def wait_for(self, needle: str, seconds: float = 30.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if needle in self.screen():
                return True
            time.sleep(0.05)
        return needle in self.screen()

    def finish(self, seconds: float = 60.0) -> Optional[int]:
        """The exit code if the command ended within `seconds`, or None when
        it had to be ended. Either way the console is closed afterwards and
        everything it painted has been read."""
        code = self.session.wait(seconds)
        if code is None:
            from luciazero_agentd import procinfo, winproc
            tree = winproc.table()
            below, found = {self.session.pid}, True
            while found:
                found = False
                for row in tree:
                    if row["ppid"] in below and row["pid"] not in below:
                        below.add(row["pid"])
                        found = True
            started = [(pid, winproc.started_at(pid)) for pid in below]
            self.session.end()
            # The job ends the whole tree, though not all in one instant, and
            # Windows will not delete a file a process is still running from:
            # a test that removes its directory next needs every one gone.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and any(procinfo.alive(pid, at) for pid, at in started):
                time.sleep(0.05)
        self.session.close_console()
        self._reader.join(10.0)
        self.session.close()
        return code

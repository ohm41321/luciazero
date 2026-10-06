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
    # trees, identity, and message would otherwise share commit ids.
    (path / "README.md").write_text(f"fixture {path.name} {uuid.uuid4().hex}\n", encoding="utf-8")
    (path / "reports").mkdir(exist_ok=True)
    (path / "reports" / "x.md").write_text("# report\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fixture")
    return os.path.realpath(str(path))


def commit_file(repo: str | Path, name: str, content: str) -> str:
    """Write ``name`` in ``repo``, commit it, and return the new HEAD oid."""
    target = Path(repo) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


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
    trustees = []
    for entry in re.findall(r"\(([^)]*)\)", sddl):
        kind, inherited, trustee = entry.split(";")[0], entry.split(";")[1], entry.split(";")[5]
        if kind != "A" or "ID" in inherited:
            return f"{entry} is not an explicit allow entry: {sddl}"
        trustees.append(trustee)
    if sorted(trustees) != sorted([str(winproc._my_sid()), "SY"]):
        return f"admits {trustees}, not this user and SYSTEM alone: {sddl}"
    return None


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

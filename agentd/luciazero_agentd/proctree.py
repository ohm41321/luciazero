"""Starting a provider so that all of it can be stopped, on every platform.

A provider spawns children of its own -- a shell, a language server, a
sandbox -- and they inherit the turn's credential, so stopping a provider
means stopping all of them. On macOS and Linux the provider leads a process
group of its own (``start_new_session``) and the group is signalled. Windows
has no signal that reaches a group and no SIGKILL. There ``start`` creates
the provider suspended, puts it in a Job Object of its own and only then lets
it run, so every process below it is in the job from the first one on --
including a grandchild whose parent has already exited, which a walk of
parent pids cannot find. Ending the job ends the tree. A process that
Windows would not put in a job, or one this daemon did not start (an orphan
from a daemon that was killed), is ended with ``taskkill /T /F`` instead.
The provider also starts in a new process group, so a Ctrl+C meant for the
user's console is not delivered to a turn running in the background.

Windows also starts a command differently. CreateProcess finds `claude.exe`
but not `claude`, which needs the extension PATHEXT supplies, and an
npm-installed CLI is a `.cmd` shim, which only cmd.exe runs -- and cmd.exe
re-reads the whole command line, so a prompt holding a newline, a quote, `&`,
`|`, `%` or `^` is cut short or run as commands. ``argv_for`` therefore reads
an npm shim for the script it starts and runs that script with node directly,
and refuses any other batch file whose arguments cmd.exe would act on.

And Windows looks for a bare command name in the working directory before
PATH -- CreateProcess does, and so does `shutil.which`, on every Python this
supports. A provider runs inside a repository that peers write to, so a
`claude.exe` or `node.exe` planted there would start with the binding's
credential. ``find`` takes a bare name only from PATH's absolute entries.
"""

from __future__ import annotations

import ntpath
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, Optional, Sequence

WINDOWS = sys.platform == "win32"
if WINDOWS:
    from . import winproc
TASKKILL_SECONDS = 30
# What `find(..., only=PROGRAMS)` accepts: a program, never a batch file.
PROGRAMS = (".com", ".exe")
# The characters cmd.exe acts on when it re-reads a batch file's command line.
CMD_SPECIAL = re.compile(r'[\r\n"%^&|<>!]')
# The line an npm `.cmd` shim ends with names the script it runs relative to
# the shim's own directory: `"%dp0%\node_modules\pkg\cli.js" %*` in current
# cmd-shim, `"%~dp0\node_modules\pkg\cli.js" %*` in older ones.
NPM_SHIM_SCRIPT = re.compile(r'"%~?dp0%?\\([^"%]+\.(?:js|cjs|mjs))"\s+%\*')


# The job of every provider `start` put in one, by pid, until it is ended or
# released.
_jobs: dict[int, Any] = {}
_jobs_lock = threading.Lock()


class CommandError(ValueError):
    """A command that cannot be started safely on this platform."""


def start(argv: Sequence[str], *, group: bool = True, **popen: Any) -> "subprocess.Popen[Any]":
    """Popen for a provider. `group` puts it in a process group of its own
    (a session on POSIX), which a turn in the background wants and a provider
    in the user's own console does not. On Windows it also starts inside a
    Job Object; `end_tree` ends that job and `release` lets it go."""
    if not WINDOWS:
        return subprocess.Popen(list(argv), start_new_session=group, **popen)
    flags = int(popen.pop("creationflags", 0)) | winproc.CREATE_SUSPENDED
    if group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    child = subprocess.Popen(list(argv), creationflags=flags, **popen)
    try:
        job = winproc.contain(child.pid)
    except OSError:
        child.wait()
        raise
    if job is not None:
        with _jobs_lock:
            _jobs[child.pid] = job
    return child


def release(pid: int) -> None:
    """Windows: the provider has exited; let go of its job, which ends
    anything it left running. Nothing elsewhere."""
    with _jobs_lock:
        job = _jobs.pop(pid, None)
    if job is not None:
        job.close()


def _get(env: Mapping[str, str], name: str) -> Optional[str]:
    """`env[name]`, with Windows' case-insensitive names."""
    return next((value for key, value in env.items() if key.upper() == name), None)


def find(name: str, env: Optional[Mapping[str, str]] = None, *,
         only: Optional[Sequence[str]] = None) -> Optional[str]:
    """The program `name` means, or None. On Windows a name with a directory
    in it is the caller's own choice and is taken as given, with the PATHEXT
    extensions tried after it; a bare name is looked for only in PATH's
    absolute entries -- never in the working directory, and never in an
    entry such as `.` that means it. `only` narrows PATHEXT to those
    extensions: a caller whose arguments cmd.exe must not read a second time,
    as it does for a batch file, passes (".com", ".exe"). Elsewhere this is
    `shutil.which`, which looks only where PATH says."""
    env = os.environ if env is None else env
    search = _get(env, "PATH")
    if not WINDOWS:
        return shutil.which(name, path=search)
    exts = [ext for ext in (_get(env, "PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if ext]
    if only is not None:
        exts = [ext for ext in exts if ext.lower() in {wanted.lower() for wanted in only}]

    def program(base: str) -> Optional[str]:
        if ntpath.splitext(base)[1].lower() in {ext.lower() for ext in exts} and os.path.isfile(base):
            return base
        return next((base + ext for ext in exts if os.path.isfile(base + ext)), None)

    if ntpath.dirname(name) or ntpath.splitdrive(name)[0]:
        return program(name)
    for entry in (search or "").split(ntpath.pathsep):
        entry = entry.strip().strip('"')
        if not ntpath.splitdrive(entry)[0] or not ntpath.isabs(entry):
            continue
        found = program(ntpath.join(entry, name))
        if found is not None:
            return found
    return None


def _npm_shim(path: str, env: Mapping[str, str]) -> Optional[list[str]]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read(64 * 1024)
    except OSError:
        return None
    match = NPM_SHIM_SCRIPT.search(text)
    if match is None:
        return None
    here = os.path.dirname(os.path.abspath(path))
    script = os.path.normpath(os.path.join(here, match.group(1)))
    if not os.path.isfile(script):
        return None
    bundled = os.path.join(here, "node.exe")
    node = bundled if os.path.isfile(bundled) else find("node", env)
    if node is None:
        # The shim itself would ask cmd.exe for `node`, which looks in the
        # working directory first: the very lookup this is here to avoid.
        raise CommandError(f"{path} is an npm shim, and node is not on PATH; install Node.js or put it on PATH")
    return [node, script]


def argv_for(argv: Sequence[str], env: Optional[Mapping[str, str]] = None) -> list[str]:
    """argv as this platform can start it without a shell re-reading it,
    and on Windows with the program named by its full path. Unchanged off
    Windows, and for a path of the caller's own that is not there (Popen
    then fails as it would have). A bare name that is not on PATH is
    refused: CreateProcess would look for it in the working directory."""
    argv = list(argv)
    if not WINDOWS or not argv:
        return argv
    env = os.environ if env is None else env
    found = find(argv[0], env)
    if found is None:
        if ntpath.dirname(argv[0]) or ntpath.splitdrive(argv[0])[0]:
            return argv
        raise CommandError(f"{argv[0]} is not on PATH; only PATH's own directories are searched, "
                           "never the working directory")
    if not found.lower().endswith((".cmd", ".bat")):
        return [found] + argv[1:]
    script = _npm_shim(found, env)
    if script is not None:
        return script + argv[1:]
    unsafe = [arg for arg in argv[1:] if CMD_SPECIAL.search(arg)]
    if unsafe:
        raise CommandError(
            f"{found} is a batch file, and cmd.exe would re-read {len(unsafe)} of its arguments "
            "(a newline, quote, %, ^, &, |, < or >); install the provider's own executable, "
            "or name node and its script as the command")
    return [found] + argv[1:]


def _taskkill() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", "taskkill.exe")


def end_tree(pid: int, gone: Callable[[float], bool]) -> bool:
    """Windows: end a process and every process below it -- its job when
    `start` gave it one, otherwise the tree `taskkill` can walk. `gone(seconds)`
    waits up to that long and says whether the process has exited. True when
    it has."""
    with _jobs_lock:
        job = _jobs.pop(int(pid), None)
    if job is not None:
        job.terminate()
        job.close()
        return gone(5.0)
    try:
        subprocess.run([_taskkill(), "/PID", str(int(pid)), "/T", "/F"], capture_output=True,
                       timeout=TASKKILL_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return gone(5.0)


def wait_gone(alive: Callable[[], bool]) -> Callable[[float], bool]:
    """A `gone` for end_tree from a liveness check."""
    def gone(seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while alive():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True
    return gone

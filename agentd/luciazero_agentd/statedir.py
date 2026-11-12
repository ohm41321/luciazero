"""Local state directory: database, capability token, endpoint metadata.

Layout (ADR 0001): ``${LUCIAZERO_AGENT_BUS_HOME:-~/.luciazero/agent-bus}/``
holding ``bus.sqlite3``, ``token`` (0600), ``endpoint.json`` and
``daemon.log``. The directory is 0700. Tests always pass an explicit
temporary directory and never touch the real one.

On Windows chmod only sets the read-only bit, so ``restrict`` gives the same
paths a protected DACL for this user and SYSTEM instead, and a state
directory another account owns is refused, as chmod refuses it on POSIX.
Windows also differs in what a private directory protects: every account may
bypass traverse checking, so a file's own DACL decides who opens it, not its
directory's. A token or database left there earlier with grants of its own
keeps them however private the directory becomes, so on Windows
``ensure_state_dir`` makes every entry below it private too, before anything
is read or opened, and refuses one it cannot.
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Optional

ENV_HOME = "LUCIAZERO_AGENT_BUS_HOME"
DEFAULT_HOME = Path.home() / ".luciazero" / "agent-bus"
TOKEN_BYTES = 32
WINDOWS = sys.platform == "win32"


def resolve_state_dir(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get(ENV_HOME)
    return Path(env).expanduser() if env else DEFAULT_HOME


def restrict(path: Path) -> None:
    """Make a path this user's alone: 0700 for a directory and 0600 for a
    file, or on Windows a DACL that admits this user and SYSTEM only."""
    if WINDOWS:
        from . import winproc
        winproc.make_private(str(path), path.is_dir())
        return
    os.chmod(path, stat.S_IRWXU if path.is_dir() else stat.S_IRUSR | stat.S_IWUSR)


def ensure_state_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        _secure_windows_tree(path)
        return path
    restrict(path)
    return path


def _secure_windows_tree(path: Path) -> None:
    """Make the state directory and everything in it this user's alone.
    Refused, before anything is changed below it: an entry another account
    owns, which its owner could open up again whatever its DACL says, and a
    link, which would carry the token's reads and writes somewhere else.

    An entry that goes away while this looks is skipped, not refused: the
    last connection to a WAL database deletes its -wal and -shm files when
    it closes, so any bus client can remove one mid-walk. An owner that
    cannot be read is otherwise taken for another account's."""
    from . import winproc

    def owned(entry: Path) -> bool:
        if winproc.owned_path(str(entry)):
            return True
        if _vanished(entry):
            return False
        raise PermissionError(
            f"{entry} is owned by another account; the agent bus keeps its token there and will not use it "
            "(if it is yours from an elevated prompt, `takeown /f` it from this one)")

    def below(directory: Path) -> list[tuple[Path, bool]]:
        found = []
        try:
            with os.scandir(directory) as entries:
                listed = list(entries)
        except FileNotFoundError:
            return found
        for entry in listed:
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise PermissionError(f"{entry.path} is a link; the agent bus will not follow one out of its state directory")
            is_dir = stat.S_ISDIR(info.st_mode)
            found.append((Path(entry.path), is_dir))
            if is_dir:
                found.extend(below(Path(entry.path)))
        return found

    if not owned(path):
        raise FileNotFoundError(f"{path} went away while the agent bus was securing it")
    entries = [(entry, is_dir) for entry, is_dir in below(path) if owned(entry)]
    winproc.make_private(str(path), True)
    for entry, is_dir in entries:
        try:
            winproc.make_private(str(entry), is_dir)
        except OSError:
            if not _vanished(entry):
                raise


def _vanished(path: Path) -> bool:
    """True only when `path` is proven gone: lstat finds no such entry. Any
    other failure to look -- access denied above all -- raises, because an
    entry this process cannot inspect is not one it may skip securing."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return True
    return False


def create_private(path: Path) -> int:
    """Open `path` for writing, truncated, and this user's alone before a
    byte goes in: 0600, or on Windows a DACL of this user and SYSTEM. A mode
    given to os.open is ignored on Windows, where the file would otherwise
    take whatever its directory hands down, and on POSIX it is ignored for a
    file that already exists."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    try:
        restrict(Path(path))
    except BaseException:
        os.close(fd)
        raise
    return fd


def _write_private(path: Path, data: str) -> None:
    with os.fdopen(create_private(path), "w", encoding="utf-8") as handle:
        handle.write(data)


def load_or_create_token(state_dir: Path) -> str:
    token_path = state_dir / "token"
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(TOKEN_BYTES)
    _write_private(token_path, token + "\n")
    return token


def read_token(state_dir: Path) -> Optional[str]:
    """Read-only: a status command must never mint a secret."""
    token_path = state_dir / "token"
    if not token_path.exists():
        return None
    token = token_path.read_text(encoding="utf-8").strip()
    return token or None


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        # Never os.kill(pid, 0) here: on Windows signal 0 is CTRL_C_EVENT.
        from . import winproc
        return winproc.exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def write_endpoint(state_dir: Path, url: str, pid: int, started_at: str,
                   process_started_at: Optional[str] = None) -> None:
    """Record where the daemon listens. `process_started_at` is the process
    start time as `procinfo.stable_started_at` prints it, so a reader can tell
    the daemon from another process given the same pid after a crash."""
    record: dict[str, Any] = {"url": url, "pid": pid, "started_at": started_at}
    if process_started_at is not None:
        record["process_started_at"] = process_started_at
    _write_private(state_dir / "endpoint.json", json.dumps(record, indent=2) + "\n")


def endpoint_alive(endpoint: Optional[dict[str, Any]]) -> bool:
    """Is the daemon an endpoint record names still running? A daemon killed
    without its cleanup (power loss, SIGKILL) leaves its record behind, and
    after a reboot its pid can belong to any process, so the pid is checked
    against the start time the daemon recorded, when it recorded one.

    Unlike `procinfo.alive`, which guards credentials and fails closed, this
    fails OPEN: when the process table cannot be read, the pid alone decides,
    as it did before start times were recorded. A wrong no here would start a
    second daemon over a live one, or migrate a store under it."""
    pid = endpoint.get("pid") if endpoint is not None else None
    if not isinstance(pid, int) or isinstance(pid, bool) or not pid_alive(pid):
        return False
    recorded = endpoint.get("process_started_at") if endpoint is not None else None
    if not isinstance(recorded, str):
        return True
    from . import procinfo

    try:
        current = procinfo.stable_started_at(pid)
    except procinfo.ProcessError:
        return True
    return current is None or current == recorded


def read_endpoint(state_dir: Path) -> Optional[dict[str, Any]]:
    path = state_dir / "endpoint.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("url"), str) else None


def clear_endpoint(state_dir: Path, pid: Optional[int] = None) -> None:
    """Remove endpoint.json, but only if it still belongs to ``pid`` when one
    is given, so a daemon that lost the file to a newer one does not erase
    the newer one's record on exit."""
    if pid is not None:
        current = read_endpoint(state_dir)
        if current is not None and current.get("pid") != pid:
            return
    try:
        (state_dir / "endpoint.json").unlink()
    except FileNotFoundError:
        pass


def db_path(state_dir: Path) -> Path:
    return state_dir / "bus.sqlite3"


SERVE_LOCK = "serve.lock"


def hold_serve_lock(state_dir: Path) -> Optional[int]:
    """Take this state directory's serve lock, or return None when another
    process holds it. The caller keeps the returned descriptor open for as
    long as it serves; the lock goes with the process however it ends.

    endpoint.json alone could not keep two daemons apart: two `serve`s
    started together both read no live record, both bound a port, and the
    one whose record was overwritten went on serving the same database with
    nobody able to reach it. The lock is taken before the record is read, so
    exactly one of them gets past it. The file holds nothing; the lock is an
    advisory one, flock on POSIX and a one-byte region lock on Windows, and
    a daemon from before the lock simply does not take it, which is why
    `serve` still checks the record too."""
    path = state_dir / SERVE_LOCK
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), stat.S_IRUSR | stat.S_IWUSR)
    try:
        restrict(path)
    except BaseException:
        os.close(fd)
        raise
    try:
        if WINDOWS:
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        # Windows says a held region with EACCES (or EDEADLOCK, after its
        # retries); flock says it with EWOULDBLOCK. Anything else is a real
        # failure and is raised.
        held = (exc.errno in (errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK)) if WINDOWS
                else isinstance(exc, BlockingIOError))
        if held:
            return None
        raise
    return fd


def release_serve_lock(fd: Optional[int]) -> None:
    """Give the lock back before the descriptor closes: Windows asks for a
    region to be unlocked before its file is closed."""
    if fd is None:
        return
    try:
        if WINDOWS:
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        os.close(fd)

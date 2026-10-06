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

    def gone(entry: Path) -> bool:
        return not os.path.lexists(entry)

    def owned(entry: Path) -> bool:
        if winproc.owned_path(str(entry)):
            return True
        if gone(entry):
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
            if not gone(entry):
                raise


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


def write_endpoint(state_dir: Path, url: str, pid: int, started_at: str) -> None:
    _write_private(state_dir / "endpoint.json", json.dumps({"url": url, "pid": pid, "started_at": started_at}, indent=2) + "\n")


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

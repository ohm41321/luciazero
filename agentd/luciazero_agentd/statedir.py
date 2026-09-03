"""Local state directory: database, capability token, endpoint metadata.

Layout (ADR 0001): ``${LUCIAZERO_AGENT_BUS_HOME:-~/.luciazero/agent-bus}/``
holding ``bus.sqlite3``, ``token`` (0600), ``endpoint.json`` and
``daemon.log``. The directory is 0700. Tests always pass an explicit
temporary directory and never touch the real one.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Optional

ENV_HOME = "LUCIAZERO_AGENT_BUS_HOME"
DEFAULT_HOME = Path.home() / ".luciazero" / "agent-bus"
TOKEN_BYTES = 32


def resolve_state_dir(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get(ENV_HOME)
    return Path(env).expanduser() if env else DEFAULT_HOME


def ensure_state_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path


def _write_private(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


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

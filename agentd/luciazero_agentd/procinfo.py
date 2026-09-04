"""Process-table facts the daemon needs to bind a terminal (ADR 0004).

Three things are wanted: which provider CLI sessions own a terminal, the
identity of one process (tty, start time, working directory), and whether a
recorded process is still that same process. Only ``ps`` and, on macOS,
``lsof`` are used; nothing is installed and nothing needs privileges beyond
reading the caller's own processes.

Two facts shape this module:

* One terminal carries several provider processes. ``codex`` runs alongside
  its code-mode host, and the desktop app's bundled ``codex`` binary shares
  the same tty again, so a naive listing shows one window three times.
  ``sessions()`` keeps only the top-level process per terminal: one whose
  parent is not itself a provider process.
* A pid is reusable, a pid plus its start time is not. Every recorded binding
  keeps the start time, and ``alive()`` refuses a pid whose start time moved.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any, Optional, Sequence

PROVIDER_COMMANDS = {"claude": "claude", "codex": "codex"}
TIMEOUT_SECONDS = 10
# A process start time never changes, but a reused pid brings a new one, so
# the value is cached only briefly: long enough that a bound session does not
# spawn `ps` on every request, short enough that pid reuse is still caught.
START_CACHE_SECONDS = 5.0
_start_cache: dict[int, tuple[float, Optional[str]]] = {}


class ProcessError(RuntimeError):
    """The process table could not be read."""


def _run(argv: Sequence[str]) -> str:
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
    except FileNotFoundError as exc:
        raise ProcessError(f"{argv[0]} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessError(f"{argv[0]} timed out") from exc
    if done.returncode != 0:
        return ""
    return done.stdout


def _provider_of(command: str) -> Optional[str]:
    name = os.path.basename(command.split(" ", 1)[0])
    return PROVIDER_COMMANDS.get(name)


def started_at(pid: int, *, cache: bool = False) -> Optional[str]:
    """The process start time as the platform prints it. Compared as an
    opaque string: it only ever has to equal itself."""
    pid = int(pid)
    if cache:
        hit = _start_cache.get(pid)
        now = time.monotonic()
        if hit is not None and now - hit[0] < START_CACHE_SECONDS:
            return hit[1]
    out = _run(["ps", "-o", "lstart=", "-p", str(pid)]).strip() or None
    if cache:
        if len(_start_cache) > 512:
            _start_cache.clear()
        _start_cache[pid] = (time.monotonic(), out)
    return out


def _table() -> list[dict[str, Any]]:
    rows = []
    # comm comes last: a command path can contain spaces, the three fields
    # before it cannot.
    for line in _run(["ps", "-axo", "pid=,ppid=,tty=,comm="]).splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, tty, command = parts
        if not pid.isdigit() or not ppid.isdigit():
            continue
        rows.append({"pid": int(pid), "ppid": int(ppid), "tty": None if tty in ("??", "?", "-") else tty, "command": command})
    return rows


def cwd_of(pid: int) -> Optional[str]:
    """Working directory of a process the caller owns."""
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/{int(pid)}/cwd")
        except OSError:
            return None
    for line in _run(["lsof", "-a", "-p", str(int(pid)), "-d", "cwd", "-Fn"]).splitlines():
        if line.startswith("n"):
            return line[1:] or None
    return None


def sessions(*, with_cwd: bool = True) -> list[dict[str, Any]]:
    """Top-level provider processes that own a terminal, plus those without
    one (an IDE session), newest first."""
    table = _table()
    parent = {row["pid"]: row["ppid"] for row in table}
    providers = {row["pid"]: row for row in table if _provider_of(row["command"])}
    out = []
    for pid, row in providers.items():
        if _descends_from_provider(pid, parent, providers):
            continue  # a helper of another provider process, not a session
        out.append({
            "pid": pid,
            "tty": row["tty"],
            "provider": _provider_of(row["command"]),
            "command": row["command"],
            "started_at": started_at(pid),
            "cwd": cwd_of(pid) if with_cwd else None,
        })
    out.sort(key=lambda r: (r["tty"] or "~", r["pid"]))
    return out


def _descends_from_provider(pid: int, parent: dict[int, int], providers: dict[int, Any]) -> bool:
    """True when a provider process sits anywhere above this one. The chain
    can pass through non-provider helpers -- `codex` spawns a code-mode host
    which spawns further `codex` processes on the same tty -- so one level of
    parent is not enough."""
    seen = {pid}
    current = parent.get(pid)
    while current is not None and current > 1 and current not in seen:
        if current in providers:
            return True
        seen.add(current)
        current = parent.get(current)
    return False


def identity(pid: int) -> Optional[dict[str, Any]]:
    """Everything a binding records about one process, or None if it is gone
    or belongs to another user."""
    pid = int(pid)
    if not owned(pid):
        return None
    for row in _table():
        if row["pid"] == pid:
            return {
                "pid": pid,
                "tty": row["tty"],
                "provider": _provider_of(row["command"]),
                "command": row["command"],
                "started_at": started_at(pid),
                "cwd": cwd_of(pid),
            }
    return None


def owned(pid: int) -> bool:
    """True when the process exists and the caller may signal it, which for
    a single-user daemon means it is the caller's own."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # someone else's process is never this user's session
    except (OverflowError, ValueError):
        return False
    return True


def alive(pid: Optional[int], recorded_start: Optional[str]) -> bool:
    """Is the recorded process still running and still the same one? A
    binding with no pid (an IDE session) is not checked here; its credential
    expiry is what limits it.

    This runs on the authentication path of every request from a bound
    session, so it fails CLOSED: if the process table cannot be read at all,
    the answer is no, and the credential is refused rather than trusted."""
    if pid is None:
        return True
    if not owned(pid):
        return False
    if recorded_start is None:
        return True
    try:
        return started_at(pid, cache=True) == recorded_start
    except ProcessError:
        return False

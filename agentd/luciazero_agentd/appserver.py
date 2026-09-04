"""Codex App Server client (ADR 0001, ADR 0006).

One managed turn over JSON-RPC on a private stdio child: `initialize`, then
`thread/start` (or `thread/resume`), then `turn/start`, collecting until the
turn completes. The `-c key=value` overrides point that child at the bus and
never touch the `config.toml` in `CODEX_HOME`, so a managed worker cannot
change the user's own Codex configuration.

Approvals are the reason this protocol is used at all. ADR 0001 recorded that
under `approvalPolicy: "never"` a model-selected MCP tool call fails before it
reaches the bus, so a managed turn runs `"on-request"` and somebody has to
answer. That somebody is the user, in advance, per worker: `deny` (the
default) refuses every escalation and lets the turn finish as blocked,
`workspace` allows commands and edits that stay inside the turn's own
directory and refuses anything asking to leave the sandbox, and `accept`
allows what the provider asks. The adapter never invents an answer the user did not choose, and every
request it answered is kept on the run log.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Optional

from .runlog import RunLog

RPC_TIMEOUT = 60
TERMINATE_GRACE_SECONDS = 5.0
# Server-to-client requests, grouped by what saying yes would allow.
EXECUTION_APPROVALS = (
    "item/commandExecution/requestApproval",
    "execCommandApproval",
    "item/fileChange/requestApproval",
    "applyPatchApproval",
)
PERMISSION_APPROVALS = ("item/permissions/requestApproval",)
INPUT_REQUESTS = ("item/tool/requestUserInput",)
ELICITATIONS = ("mcpServer/elicitation/request",)
# Fields by which a request asks to leave the sandbox it was started in. Under
# `workspace` these are the difference between "work in your worktree" and
# "do whatever you asked for": accepting one is accepting `accept`.
ESCALATION_KEYS = (
    "withEscalatedPermissions", "with_escalated_permissions",
    "escalatedPermissions", "escalated_permissions",
    "grantRoot", "grant_root", "sandboxBypass", "sandbox_bypass",
)
# Where a request says it would write or run. What cannot be located cannot be
# confined, so under `workspace` an unreadable shape is a refusal.
PATH_KEYS = ("cwd", "path", "file", "filePath", "file_path", "root", "workdir", "working_directory")
CHANGE_KEYS = ("changes", "fileChanges", "file_changes", "paths", "files")


def _truthy(params: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(bool(params.get(key)) for key in keys)


def _claimed_paths(params: dict[str, Any]) -> list[str]:
    """Every filesystem location this request names, in whichever shape the
    server used: a bare path, a list of them, or a map keyed by path."""
    found: list[str] = []
    for key in PATH_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value:
            found.append(value)
    for key in CHANGE_KEYS:
        value = params.get(key)
        if isinstance(value, dict):
            found.extend(str(name) for name in value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, dict):
                    for inner in PATH_KEYS:
                        if isinstance(item.get(inner), str):
                            found.append(str(item[inner]))
    return found


class AppServerError(RuntimeError):
    """The App Server child failed, or spoke in a way this client cannot use."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class AppServer:
    """A Codex App Server child for exactly one turn."""

    def __init__(
        self,
        argv: list[str],
        *,
        env: dict[str, str],
        cwd: str,
        log: RunLog,
        approval_policy: str = "deny",
        on_process: Optional[Callable[[int], None]] = None,
    ) -> None:
        self.approval_policy = approval_policy
        # What `workspace` means, resolved once: the turn's own directory.
        self.cwd = os.path.realpath(cwd)
        self.answered: list[dict[str, Any]] = []
        self._log = log
        try:
            self._process = subprocess.Popen(
                argv, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                start_new_session=True,  # its own process group: see `close`
            )
        except (OSError, ValueError) as exc:
            raise AppServerError(f"cannot start {argv[0]!r}: {exc}", permanent=True) from exc
        if on_process is not None:
            on_process(self._process.pid)
        self._next_id = 1
        self._lines: queue.Queue[Optional[str]] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    # ------------------------------------------------------------- plumbing
    def _read(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._log.write(line)
            self._lines.put(line)
        self._lines.put(None)

    def _write(self, payload: dict[str, Any]) -> None:
        if self._process.poll() is not None:
            raise AppServerError("the app-server child exited")
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise AppServerError(f"the app-server child closed its input: {exc}") from exc

    def notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)

    def _next_message(self, deadline: float, what: str) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AppServerError(f"app-server timed out: {what}")
        try:
            line = self._lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise AppServerError(f"app-server timed out: {what}") from exc
        if line is None:
            raise AppServerError("the app-server child closed its output")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return message if isinstance(message, dict) else {}

    def request(self, method: str, params: Optional[dict[str, Any]] = None, timeout: int = RPC_TIMEOUT) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)
        deadline = time.monotonic() + timeout
        while True:
            message = self._next_message(deadline, method)
            if not message:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise AppServerError(f"{method} failed: {message['error']}")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise AppServerError(f"{method} returned a non-object result")
                return result
            if "id" in message and "method" in message:
                self.answer(message)

    def collect_until(self, method: str, timeout: int) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        collected: list[dict[str, Any]] = []
        while True:
            message = self._next_message(deadline, method)
            if not message:
                continue
            if "id" in message and "method" in message:
                self.answer(message)
                continue
            collected.append(message)
            if message.get("method") == method:
                return collected

    # ------------------------------------------------------------ approvals
    def decide(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """The user's policy, applied. Nothing here asks a human mid-turn:
        a managed turn runs while nobody is watching, so the answer has to
        have been chosen when the worker was enrolled."""
        if method in EXECUTION_APPROVALS:
            return {"decision": "accept" if self.allows(params) else "deny"}
        if method in PERMISSION_APPROVALS:
            # A permission grant is not scoped to a path, so `workspace` cannot
            # bound it; only `accept` hands one over.
            if self.approval_policy == "accept":
                return {"permissions": params.get("permissions") or {}, "scope": "turn"}
            return {"permissions": {}, "scope": "turn"}
        if method in INPUT_REQUESTS:
            # Nobody is at the keyboard; an invented answer is worse than none.
            return {"answers": {}}
        if method in ELICITATIONS:
            return {"action": "accept" if self.approval_policy == "accept" else "decline", "content": {}}
        return {}

    def allows(self, params: dict[str, Any]) -> bool:
        """Whether this policy lets the request through.

        Review finding: `workspace` and `accept` answered execution approvals
        identically, which made the middle tier decoration -- an operator who
        chose "in its own worktree" got "whatever it asks". `workspace` now
        means what it says: nothing that asks to leave the sandbox, and nothing
        that names a path outside the turn's own directory."""
        if self.approval_policy == "accept":
            return True
        if self.approval_policy != "workspace":
            return False
        if _truthy(params, ESCALATION_KEYS):
            return False  # asking to leave the sandbox is `accept`'s to grant
        claimed = _claimed_paths(params)
        if not claimed:
            # Nothing to check against: the request stays inside the
            # `workspace-write` sandbox the thread was started in.
            return True
        return all(self.inside(path) for path in claimed)

    def inside(self, path: str) -> bool:
        """Is this path within the turn's own directory? Resolved, so `..` and
        a symlink out of the worktree are not a way around the answer."""
        try:
            resolved = os.path.realpath(os.path.join(self.cwd, os.path.expanduser(path)))
        except (OSError, ValueError):
            return False
        return resolved == self.cwd or resolved.startswith(self.cwd + os.sep)

    def answer(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        result = self.decide(method, params if isinstance(params, dict) else {})
        self.answered.append({"method": method, "result": result})
        self._log.write(f"[dispatcher] {method} answered under policy {self.approval_policy}: {json.dumps(result, sort_keys=True)}\n")
        self._write({"id": message["id"], "result": result})

    # ---------------------------------------------------------------- close
    @property
    def pid(self) -> int:
        return self._process.pid

    def close(self) -> None:
        """Stop the child and everything it started. Codex spawns its own
        children, so the signal goes to the process group; killing only the
        parent would leave those behind."""
        if self._process.poll() is None:
            _terminate_group(self._process)
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def __enter__(self) -> "AppServer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _terminate_group(process: "subprocess.Popen[str]") -> None:
    """SIGTERM the child's process group, then SIGKILL what is left."""
    try:
        group = os.getpgid(process.pid)
    except (OSError, ProcessLookupError):
        group = None
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is not None:
            return
        try:
            if group is not None:
                os.killpg(group, sig)
            else:
                process.send_signal(sig)
        except (OSError, ProcessLookupError):
            return
        try:
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            continue

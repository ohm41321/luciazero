"""Provider adapters (ADR 0006): one contract, one implementation per provider.

An adapter's whole job is to run one turn of one provider and say what
happened. It never touches the database: the dispatcher owns every record, so
an adapter cannot invent progress, and a provider that lies about its exit
still cannot make a delivery look handled -- only the worker's own tool calls
can do that.

The bus reaches the child the way `luciazero-agentd run` reaches it: the
session credential travels in the environment or in a 0600 file, never on the
command line, because argv is world-readable through `ps`.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

from .appserver import RPC_TIMEOUT, AppServer, AppServerError, _terminate_group
from .runlog import RunLog

SERVER_NAME = "luciazero-bus"
URL_ENV = "LUCIAZERO_AGENT_BUS_URL"
TOKEN_ENV = "LUCIAZERO_AGENT_BUS_TOKEN"
PROMPT_ENV = "LUCIAZERO_AGENT_BUS_PROMPT"
AGENT_ENV = "LUCIAZERO_AGENT_BUS_AGENT"
SESSION_ENV = "LUCIAZERO_AGENT_BUS_SESSION"
TERMINATE_GRACE_SECONDS = 5.0

#: Flags a managed turn owns, per provider. They carry the bus, bound what the
#: turn may touch, or decide what it may do without asking -- so a worker
#: command may not carry them. The rule is a refusal rather than a silent
#: override because both CLIs let a repeated flag win or accumulate: with
#: `--dangerously-skip-permissions` in the command, the policy the human chose
#: at enrolment would be decoration. A human who wrote one of these meant
#: something by it, and is told no instead of being quietly ignored.
RESERVED_FLAGS: dict[str, tuple[str, ...]] = {
    "claude": (
        "-p", "--print", "-c", "--continue", "-r", "--resume", "--fork-session",
        "--mcp-config", "--strict-mcp-config", "--output-format",
        "--allowedTools", "--allowed-tools", "--disallowedTools", "--disallowed-tools",
        "--permission-mode", "--permission-prompt-tool", "--dangerously-skip-permissions",
    ),
    "codex": (
        "-c", "--config", "-s", "--sandbox", "-a", "--ask-for-approval", "--full-auto",
        "--dangerously-bypass-approvals-and-sandbox", "--yolo", "resume",
    ),
    "other": (),
}


def dangling_option(provider: str, command: Sequence[str]) -> Optional[str]:
    """The worker's last argument, when it is an option still waiting for a
    value. Review finding: a denylist of known-dangerous flags cannot close
    this class -- `claude --model` swallows the `--mcp-config` that follows it,
    and `codex exec --model` swallows the prompt itself, which is ADR 0001's
    trap exactly. Any command whose tail is an unpaired option is refused; the
    `--flag=value` spelling carries its own value and is fine."""
    if provider not in RESERVED_FLAGS or provider == "other":
        return None
    parts = list(command)[1:]
    if not parts:
        return None
    last = parts[-1]
    if last.startswith("-") and last != "-" and "=" not in last:
        return last
    return None


def reserved_flags_in(provider: str, command: Sequence[str]) -> list[str]:
    """Which flags of the dispatcher's own a worker command names. Matches the
    `--flag=value` spelling too, and skips the binary itself so a path that
    happens to contain a flag-shaped name is not a refusal."""
    reserved = RESERVED_FLAGS.get(provider, ())
    if not reserved:
        return []
    found = []
    for part in list(command)[1:]:
        head = part.split("=", 1)[0]
        if head in reserved and head not in found:
            found.append(head)
    return found


@dataclass(frozen=True)
class TurnRequest:
    """Everything one turn needs. ``provider_session_id`` present means resume."""

    agent_id: str
    provider: str
    command: tuple[str, ...]
    cwd: str
    prompt: str
    credential: str
    url: str
    timeout_seconds: int
    log: RunLog
    provider_session_id: Optional[str] = None
    # A private 0700 directory for this turn: anything an adapter has to write
    # (a Claude MCP config carrying the credential) lives here and dies with
    # the turn, and recovery removes what a killed dispatcher left.
    workspace: Optional[Path] = None
    # What the user allowed this worker to do when they enrolled it.
    approval_policy: str = "deny"
    # Called with the child's pid as soon as it exists, so the run record can
    # name the process a killed dispatcher would orphan.
    on_process: Optional[Callable[[int], None]] = None


@dataclass(frozen=True)
class TurnResult:
    """What the provider did. ``permanent`` marks a failure that retrying
    cannot fix -- a missing binary, an unusable configuration -- so the
    dispatcher dead-letters instead of spending the remaining attempts."""

    ok: bool
    exit_state: str
    provider_session_id: Optional[str] = None
    error: Optional[str] = None
    permanent: bool = False


class Adapter(Protocol):
    name: str

    def start(self, request: TurnRequest) -> TurnResult:
        """Run a turn in a new provider session."""

    def resume(self, request: TurnRequest) -> TurnResult:
        """Run a turn in the provider session the request names."""

    def cancel(self) -> None:
        """Stop the turn in flight, if any."""

    def status(self) -> str:
        """``running`` while a turn is in flight, otherwise ``idle``."""


class ProcessAdapter:
    """A provider that is a command: the offline gate's worker, and the base
    the provider-specific adapters build on. Output is streamed into the run
    log as it arrives rather than buffered, so a provider that never stops
    talking is bounded by the log's cap instead of by memory."""

    name = "process"

    #: Output kept for parsing (a provider's own session id, say). Bounded:
    #: the run log holds the whole turn, this is only the recent tail.
    TAIL_LINES = 200

    def __init__(self) -> None:
        self._child: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()
        self._tail: deque[str] = deque(maxlen=self.TAIL_LINES)

    # ------------------------------------------------------------- contract
    def start(self, request: TurnRequest) -> TurnResult:
        return self._run(request, resuming=False)

    def resume(self, request: TurnRequest) -> TurnResult:
        return self._run(request, resuming=True)

    def cancel(self) -> None:
        """Stop the turn and everything it started. Providers spawn their own
        children -- a shell, a language server, a sandbox -- and signalling only
        the process we know about leaves those running with the turn's
        credential still in their environment."""
        with self._lock:
            child = self._child
        if child is None or child.poll() is not None:
            return
        _terminate_group(child)

    def status(self) -> str:
        with self._lock:
            child = self._child
        return "running" if child is not None and child.poll() is None else "idle"

    # -------------------------------------------------------------- details
    def environment(self, request: TurnRequest, *, resuming: bool) -> dict[str, str]:
        env = dict(os.environ)
        env[URL_ENV] = request.url
        env[TOKEN_ENV] = request.credential
        env[PROMPT_ENV] = request.prompt
        env[AGENT_ENV] = request.agent_id
        if resuming and request.provider_session_id:
            env[SESSION_ENV] = request.provider_session_id
        return env

    def argv(self, request: TurnRequest, *, resuming: bool) -> list[str]:
        return list(request.command)

    def prepare(self, request: TurnRequest, *, resuming: bool) -> None:
        """Write whatever this provider needs before it starts."""

    def clean_up(self, request: TurnRequest) -> None:
        """Remove whatever `prepare` wrote, however the turn ended."""

    def session_id_of(self, request: TurnRequest, *, resuming: bool) -> Optional[str]:
        """What to record for the next turn to resume into. A bare command has
        no session of its own, so the dispatcher keeps whatever it had."""
        return request.provider_session_id

    def reject(self, request: TurnRequest) -> Optional[str]:
        """Why this worker's command may not run, if it may not. Checked at
        enrolment too; repeated here because a worker enrolled before the check
        existed still has to be refused rather than silently obeyed."""
        return refusal_for(request)

    def _run(self, request: TurnRequest, *, resuming: bool) -> TurnResult:
        self._tail.clear()
        problem = self.reject(request)
        if problem is not None:
            return TurnResult(ok=False, exit_state="config_refused", error=problem, permanent=True)
        try:
            try:
                self.prepare(request, resuming=resuming)
            except Exception as exc:  # noqa: BLE001 - a half-written config is still a config
                # Configuration we could not write will not write next time
                # either. The cleanup below still runs: `prepare` may have
                # created the file before it failed.
                return TurnResult(ok=False, exit_state="config_failed", error=f"cannot prepare the turn: {exc}", permanent=True)
            return self._spawn(request, resuming=resuming)
        finally:
            # However the turn ended -- exit, timeout, signal, exception -- the
            # credential this wrote to disk goes away with it.
            self.clean_up(request)

    def _spawn(self, request: TurnRequest, *, resuming: bool) -> TurnResult:
        argv = self.argv(request, resuming=resuming)
        try:
            child = subprocess.Popen(
                argv, cwd=request.cwd, env=self.environment(request, resuming=resuming),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                # Its own process group, so `cancel` reaches the children the
                # provider starts and not just the provider.
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            # A command that cannot start will not start on the next attempt
            # either: retrying a configuration error is a loop with a bill.
            return TurnResult(ok=False, exit_state="spawn_failed", error=f"cannot start {argv[0]!r}: {exc}", permanent=True)
        with self._lock:
            self._child = child
        if request.on_process is not None:
            request.on_process(child.pid)

        def pump() -> None:
            assert child.stdout is not None
            for line in child.stdout:
                request.log.write(line)
                self._tail.append(line)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        timed_out = False
        try:
            code = child.wait(timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.cancel()
            code = child.returncode if child.returncode is not None else -1
        finally:
            reader.join(timeout=TERMINATE_GRACE_SECONDS)
            if child.stdout is not None:
                child.stdout.close()
            with self._lock:
                self._child = None
        if timed_out:
            return TurnResult(ok=False, exit_state="timeout", error=f"the turn ran past {request.timeout_seconds}s and was stopped")
        if code != 0:
            return TurnResult(ok=False, exit_state=f"exit {code}", error=f"{argv[0]!r} exited {code}")
        return TurnResult(ok=True, exit_state="exit 0", provider_session_id=self.session_id_of(request, resuming=resuming))


class ClaudeAdapter(ProcessAdapter):
    """`claude -p`, resumed by session id (ADR 0001's proven path).

    The bus arrives through `--mcp-config` with `--strict-mcp-config`, so the
    user's own MCP configuration is never read or written, and the credential
    lives in that file at 0600 rather than on the command line -- argv is
    world-readable through `ps` for the life of the turn."""

    name = "claude"
    #: Only the bus. A managed turn that needs more says so and is blocked.
    ALLOWED_TOOLS = f"mcp__{SERVER_NAME}"
    #: What the user allowed, in Claude's own vocabulary. `default` is not a
    #: no-op: with `--allowedTools` naming only the bus, everything else needs a
    #: permission nobody is there to give, so the turn reports instead of acting.
    PERMISSION_MODES = {"deny": "default", "workspace": "acceptEdits", "accept": "bypassPermissions"}

    def config_path(self, request: TurnRequest) -> Path:
        workspace = request.workspace or Path(request.cwd)
        return Path(workspace) / "mcp.json"

    def prepare(self, request: TurnRequest, *, resuming: bool) -> None:
        path = self.config_path(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(handle, json.dumps({"mcpServers": {SERVER_NAME: {
                "type": "http", "url": request.url,
                "headers": {"Authorization": f"Bearer {request.credential}"},
            }}}).encode("utf-8"))
        finally:
            os.close(handle)

    def clean_up(self, request: TurnRequest) -> None:
        try:
            self.config_path(request).unlink()
        except OSError:
            pass

    def environment(self, request: TurnRequest, *, resuming: bool) -> dict[str, str]:
        env = super().environment(request, resuming=resuming)
        # Claude reads the credential from its config file; nothing else needs
        # a copy, and a copy in the environment is inherited by every child.
        env.pop(TOKEN_ENV, None)
        return env

    def argv(self, request: TurnRequest, *, resuming: bool) -> list[str]:
        """`claude -p [user flags] [--resume ID] --mcp-config F
        --strict-mcp-config --allowedTools T --permission-mode M --output-format
        json PROMPT`.

        The order is not cosmetic. `--allowedTools <tools...>` and
        `--mcp-config <configs...>` are both variadic, so each is followed by a
        single-value option and the prompt comes last, right after
        `--output-format json` -- ADR 0001 recorded the swallowed prompt. The
        user's own flags go early, where they cannot break that pairing."""
        base = list(request.command) or ["claude"]
        argv = base[:1] + ["-p"] + base[1:]
        if resuming and request.provider_session_id:
            argv += ["--resume", request.provider_session_id]
        argv += ["--mcp-config", str(self.config_path(request)), "--strict-mcp-config",
                 "--allowedTools", self.ALLOWED_TOOLS,
                 "--permission-mode", self.PERMISSION_MODES.get(request.approval_policy, "default"),
                 "--output-format", "json"]
        argv.append(request.prompt)
        return argv

    def session_id_of(self, request: TurnRequest, *, resuming: bool) -> Optional[str]:
        """`--output-format json` ends with a result object naming the session
        the turn ran in; that id is what the next turn resumes."""
        for line in reversed(self._tail):
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and isinstance(message.get("session_id"), str):
                return message["session_id"]
        return request.provider_session_id


class CodexAdapter:
    """Codex through the App Server, with `codex exec` as the fallback.

    App Server is the primary path (ADR 0001): it is the one that can answer
    approval requests, and `approvalPolicy: "never"` fails a model-selected MCP
    tool call before it reaches the bus. A worker whose command names `exec`
    takes the fallback, which is a plain subprocess and cannot answer
    approvals."""

    name = "codex"
    #: The sandbox the thread runs in, per policy. `deny` is read-only on
    #: purpose: writes inside the workspace need no approval, so a `deny` worker
    #: with a writable sandbox would edit freely while its docstring says it
    #: reports instead of acting.
    SANDBOX_MODES = {"deny": "read-only", "workspace": "workspace-write", "accept": "workspace-write"}

    def __init__(self) -> None:
        self._server: Optional[AppServer] = None
        self._fallback = _CodexExecAdapter()
        self._lock = threading.Lock()

    # -------------------------------------------------------------- helpers
    @staticmethod
    def uses_exec(request: TurnRequest) -> bool:
        return "exec" in tuple(request.command)[1:]

    @staticmethod
    def overrides(request: TurnRequest) -> list[str]:
        # `-c key=value` applies to this process only and never touches the
        # config.toml in CODEX_HOME: a managed turn cannot rewrite the user's
        # own Codex configuration.
        return [f'mcp_servers.{SERVER_NAME}.url="{request.url}"',
                f'mcp_servers.{SERVER_NAME}.bearer_token_env_var="{TOKEN_ENV}"']

    def argv(self, request: TurnRequest, *, resuming: bool) -> list[str]:
        base = list(request.command) or ["codex"]
        argv = [base[0], "app-server", "--stdio"]
        for override in self.overrides(request):
            argv += ["-c", override]
        dropped = [part for part in base[1:] if part != "app-server"]
        if dropped:
            # `app-server` takes none of `exec`'s flags. Dropping them silently
            # would let a worker run under settings its enrolment says it has.
            request.log.write(f"[dispatcher] the app-server path ignores these worker arguments: {' '.join(dropped)}\n")
        return argv

    def environment(self, request: TurnRequest, *, resuming: bool) -> dict[str, str]:
        env = dict(os.environ)
        env[URL_ENV] = request.url
        env[TOKEN_ENV] = request.credential  # named by the -c override, never argv
        env[AGENT_ENV] = request.agent_id
        return env

    # ------------------------------------------------------------- contract
    def start(self, request: TurnRequest) -> TurnResult:
        return self._turn(request, resuming=False)

    def resume(self, request: TurnRequest) -> TurnResult:
        return self._turn(request, resuming=True)

    def cancel(self) -> None:
        with self._lock:
            server = self._server
        if server is not None:
            server.close()
        self._fallback.cancel()

    def status(self) -> str:
        with self._lock:
            server = self._server
        if server is not None:
            return "running"
        return self._fallback.status()

    def _turn(self, request: TurnRequest, *, resuming: bool) -> TurnResult:
        problem = refusal_for(request)
        if problem is not None:
            return TurnResult(ok=False, exit_state="config_refused", error=problem, permanent=True)
        if self.uses_exec(request):
            return self._fallback.resume(request) if resuming else self._fallback.start(request)
        try:
            server = AppServer(
                self.argv(request, resuming=resuming), env=self.environment(request, resuming=resuming),
                cwd=request.cwd, log=request.log, approval_policy=request.approval_policy,
                on_process=request.on_process,
            )
        except AppServerError as exc:
            return TurnResult(ok=False, exit_state="spawn_failed", error=str(exc), permanent=exc.permanent)
        with self._lock:
            self._server = server
        # Every protocol step is bounded by the turn's own timeout: a provider
        # that answers nothing must not hold the dispatcher past the limit the
        # user set on the turn.
        rpc_timeout = max(5, min(RPC_TIMEOUT, request.timeout_seconds))
        try:
            server.request("initialize", {"clientInfo": {"name": "luciazero-agentd", "version": "0"},
                                          "capabilities": {"experimentalApi": True}}, timeout=rpc_timeout)
            server.notify("initialized")
            thread_id = request.provider_session_id
            if resuming and thread_id:
                server.request("thread/resume", {"threadId": thread_id}, timeout=rpc_timeout)
            else:
                started = server.request("thread/start", {
                    "cwd": request.cwd,
                    "sandbox": self.SANDBOX_MODES.get(request.approval_policy, "read-only"),
                    "approvalPolicy": "on-request",
                }, timeout=rpc_timeout)
                thread = started.get("thread")
                thread_id = thread.get("id") if isinstance(thread, dict) else None
                if not isinstance(thread_id, str) or not thread_id:
                    # The same handshake will return the same nothing next
                    # time: spending the remaining attempts on it is a bill.
                    return TurnResult(ok=False, exit_state="protocol_error", error="thread/start returned no thread id", permanent=True)
            server.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": request.prompt}]}, timeout=rpc_timeout)
            server.collect_until("turn/completed", timeout=request.timeout_seconds)
        except AppServerError as exc:
            return TurnResult(ok=False, exit_state="app_server_error", error=str(exc), permanent=exc.permanent,
                              provider_session_id=request.provider_session_id)
        finally:
            server.close()
            with self._lock:
                self._server = None
        return TurnResult(ok=True, exit_state="turn completed", provider_session_id=thread_id)


class _CodexExecAdapter(ProcessAdapter):
    """`codex exec` / `codex exec resume <thread>`: the tested fallback. It
    cannot answer an approval request, so a turn that needs one ends there."""

    name = "codex-exec"

    def argv(self, request: TurnRequest, *, resuming: bool) -> list[str]:
        """`codex exec [resume ID] -c OVERRIDE... [user flags] PROMPT`.

        `codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]` takes `-c` at the
        subcommand it belongs to, so the overrides follow `exec` (or `resume`)
        and the prompt stays the last positional."""
        base = list(request.command) or ["codex", "exec"]
        extra = [part for part in base[1:] if part != "exec"]
        argv = [base[0], "exec"]
        if resuming and request.provider_session_id:
            argv += ["resume", request.provider_session_id]
        for override in CodexAdapter.overrides(request):
            argv += ["-c", override]
        argv += extra
        argv.append(request.prompt)
        return argv

    def session_id_of(self, request: TurnRequest, *, resuming: bool) -> Optional[str]:
        for line in reversed(self._tail):
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                for key in ("thread_id", "threadId", "session_id"):
                    if isinstance(message.get(key), str):
                        return message[key]
        return request.provider_session_id


def refusal_for(request: TurnRequest) -> Optional[str]:
    """The shared refusal: a worker command that names a flag the dispatcher
    owns is a permanent configuration error, not a turn to retry."""
    taken = reserved_flags_in(request.provider, request.command)
    if taken:
        return (f"the worker command names {', '.join(taken)}, which the dispatcher sets itself; "
                "re-enrol the worker without it (approvals are chosen with `worker add --approve`)")
    dangling = dangling_option(request.provider, request.command)
    if dangling:
        return (f"the worker command ends in {dangling}, an option with no value; it would swallow the "
                "flag the dispatcher appends next. Write it as --flag=value or give it its value")
    return None


ADAPTERS: dict[str, type] = {"other": ProcessAdapter, "claude": ClaudeAdapter, "codex": CodexAdapter}


def adapter_for(provider: str) -> Adapter:
    """The adapter that runs this provider's turns, or a clear refusal. A
    provider with no adapter is a permanent failure, not a retry."""
    factory = ADAPTERS.get(provider)
    if factory is None:
        raise KeyError(provider)
    return factory()  # type: ignore[return-value]

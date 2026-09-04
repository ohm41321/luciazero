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

import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from .runlog import RunLog

URL_ENV = "LUCIAZERO_AGENT_BUS_URL"
TOKEN_ENV = "LUCIAZERO_AGENT_BUS_TOKEN"
PROMPT_ENV = "LUCIAZERO_AGENT_BUS_PROMPT"
AGENT_ENV = "LUCIAZERO_AGENT_BUS_AGENT"
SESSION_ENV = "LUCIAZERO_AGENT_BUS_SESSION"
TERMINATE_GRACE_SECONDS = 5.0


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

    def __init__(self) -> None:
        self._child: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- contract
    def start(self, request: TurnRequest) -> TurnResult:
        return self._run(request, resuming=False)

    def resume(self, request: TurnRequest) -> TurnResult:
        return self._run(request, resuming=True)

    def cancel(self) -> None:
        with self._lock:
            child = self._child
        if child is None or child.poll() is not None:
            return
        child.terminate()
        try:
            child.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=TERMINATE_GRACE_SECONDS)

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

    def session_id_of(self, request: TurnRequest, *, resuming: bool) -> Optional[str]:
        """What to record for the next turn to resume into. A bare command has
        no session of its own, so the dispatcher keeps whatever it had."""
        return request.provider_session_id

    def _run(self, request: TurnRequest, *, resuming: bool) -> TurnResult:
        argv = self.argv(request, resuming=resuming)
        try:
            child = subprocess.Popen(
                argv, cwd=request.cwd, env=self.environment(request, resuming=resuming),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
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


ADAPTERS: dict[str, type] = {"other": ProcessAdapter}


def adapter_for(provider: str) -> Adapter:
    """The adapter that runs this provider's turns, or a clear refusal. A
    provider with no adapter is a permanent failure, not a retry."""
    factory = ADAPTERS.get(provider)
    if factory is None:
        raise KeyError(provider)
    return factory()  # type: ignore[return-value]

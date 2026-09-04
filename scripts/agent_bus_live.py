#!/usr/bin/env python3
"""M6 live smoke gate: one real Codex turn and one real Claude turn, started by
the dispatcher, each reaching exactly one completed logical outcome.

This is the one claim the offline suite cannot make. Everything else about
managed dispatch is proven against scripts the tests write; what no fake can
prove is that the argv we build is the argv these two CLIs actually accept,
that the credential reaches the model through the file or the environment
variable we chose, and that a real provider's exit maps to the outcome we
record. That is what this gate spends quota on.

It refuses to run without `--spend-quota`, because it starts real model turns
that cost the user money. Two turns, one per provider, is the whole budget.

What it isolates, and what it cannot:

* the bus state directory, the worker's working directory and every record are
  disposable temporary directories, and every child is pointed at them, so the
  user's own `~/.luciazero` is never touched;
* the provider homes are *not* redirected. A real turn needs the user's real
  credentials, so `~/.codex` and `~/.claude` are read as they are, and each
  provider writes its own session transcript there as it always does. That is
  inherent to proving anything about the real CLIs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agentd"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_bus_e2e import SKIP_EXIT, Daemon, E2EError  # noqa: E402
from agent_bus_mcp_gate import GateError  # noqa: E402
from luciazero_agentd.store import Store, StoreError  # noqa: E402

ARCHITECT = "codex-architect"
#: One managed worker per provider. Their ids name the provider so a failure
#: report says which CLI it was without cross-referencing anything.
WORKERS = {"codex": "codex-live-worker", "claude": "claude-live-worker",
           "rehearsal": "rehearsal-worker"}
#: The offline gate's worker: a real bus client that spends nothing. Running
#: the gate against it proves every assertion below is satisfiable, which is
#: the cheap half of a gate whose other half costs money.
REHEARSAL_COMMAND = [sys.executable, str(ROOT / "scripts" / "agent_bus_worker.py")]
DEFAULT_TURN_TIMEOUT = 300
# `workspace`, not `deny`: ADR 0001's null result 3 recorded that Codex routes
# a model-selected MCP tool call through the approval flow, and a `deny` worker
# would refuse the bus calls this turn exists to make. `workspace` still
# refuses anything asking to leave the sandbox or naming a path outside the
# turn's own directory, which is the whole point of the middle tier.
POLICY = "workspace"
TASK_TITLE = "Smoke test: acknowledge this delivery, claim the task, complete it, and reply"


class LiveGateError(E2EError):
    pass


def store_of(daemon: Daemon) -> Store:
    store = Store.open(daemon.state_dir / "bus.sqlite3")
    store.migrate()
    store.trust = "system"
    return store


def cli_env(daemon: Daemon) -> dict[str, str]:
    """Every child gets the disposable state directory as its bus home, so a
    missing `--state-dir` anywhere can never reach the user's own bus."""
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "agentd"),
                LUCIAZERO_AGENT_BUS_HOME=str(daemon.state_dir), LZ_WORKER_MODE="work")


def agentd(daemon: Daemon, *args: str, timeout: int = 60) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "luciazero_agentd", *args, "--state-dir", str(daemon.state_dir)],
        cwd=ROOT / "agentd", env=cli_env(daemon), capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise LiveGateError(f"luciazero-agentd {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def enrol(daemon: Daemon, provider: str, command: list[str], cwd: Path, timeout: int) -> None:
    """The human channel enrols the worker; nothing on the bus can.

    Not through `agentd()`: everything after the `--` is the provider command,
    so `--state-dir` has to go before it or the worker is enrolled with the
    dispatcher's own flag in its argv."""
    argv = [sys.executable, "-m", "luciazero_agentd", "worker", "add", WORKERS[provider],
            "other" if provider == "rehearsal" else provider,
            "--cwd", str(cwd), "--max-attempts", "1", "--timeout", str(timeout),
            "--approve", POLICY, "--state-dir", str(daemon.state_dir), "--", *command]
    result = subprocess.run(argv, cwd=ROOT / "agentd", env=cli_env(daemon), capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise LiveGateError(f"worker add failed: {result.stderr.strip()}")


def queue_work(daemon: Daemon, provider: str, run: str) -> dict[str, Any]:
    """The architect, at a real terminal with its own credential, queues one
    task for the worker. The dispatcher is what starts the turn."""
    worker = WORKERS[provider]
    bus = daemon.session(ARCHITECT)
    task = bus.call("task_create", {
        "title": TASK_TITLE, "created_by": ARCHITECT, "assigned_to": worker,
        "payload": {"instructions": "No files to change. Acknowledge, claim, complete, and message "
                                    f"{ARCHITECT} with one sentence saying the bus works."},
        "idempotency_key": f"{run}-{provider}-task",
    })
    bus.call("message_send", {"sender": ARCHITECT, "recipient": worker, "kind": "task",
                              "payload": {"task_id": task["id"]},
                              "idempotency_key": f"{run}-{provider}-msg"})
    with store_of(daemon) as store:
        delivery = store.inbox(worker, states=("queued",))["items"][-1]
    return {"task": task["id"], "delivery": delivery["delivery_id"]}


def dispatch_once(daemon: Daemon, timeout: int) -> str:
    """The shipped dispatcher, as its own process, exactly as a user runs it."""
    result = subprocess.run(
        [sys.executable, "-m", "luciazero_agentd", "dispatch", "--once", "--state-dir", str(daemon.state_dir)],
        cwd=ROOT / "agentd", env=cli_env(daemon), capture_output=True, text=True, timeout=timeout + 120,
    )
    if result.returncode != 0:
        raise LiveGateError(f"dispatch exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def log_tail(run: dict[str, Any], lines: int = 40) -> str:
    """The turn's own log, already redacted at the point it was written."""
    ref = run.get("output_ref")
    if not ref or not Path(str(ref)).exists():
        return "(no run log)"
    body = Path(str(ref)).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(body[-lines:])


def check_turn(daemon: Daemon, provider: str, work: dict[str, Any], turn_dir: Path) -> dict[str, Any]:
    """One turn, judged by the records the worker itself moved."""
    worker = WORKERS[provider]
    with store_of(daemon) as store:
        runs = store.list_runs(agent_id=worker, limit=10)
        if not runs:
            raise LiveGateError(f"{provider}: the dispatcher never started a run")
        run = runs[0]
        delivery = store.get_delivery(work["delivery"])
        task = store.get_task(work["task"])
        binding = store.get_binding(str(run["binding_id"])) if run["binding_id"] else None
        session = store.get_session(str(run["session_id"])) if run["session_id"] else None
        lease = store.lease_on("session", worker)
        # The events table names the actor in `actor`; there is no
        # `actor_agent_id`, and filtering on one matched nothing at all, which
        # is how the first live run failed on an assertion that could never
        # have passed. A rehearsal against the offline worker now proves every
        # assertion here is satisfiable before any quota is spent.
        events, after = [], 0
        while True:
            page = store.events(after=after, limit=500)
            if not page:
                break
            events.extend(e for e in page if str(e.get("actor", "")).endswith(worker))
            after = page[-1]["seq"]
        failures = []
        if run["state"] != "completed":
            failures.append(f"the run is {run['state']} ({run['exit_state']}: {run['error']})")
        if delivery["state"] != "completed":
            failures.append(f"the delivery is {delivery['state']} after {delivery['attempts']} attempt(s)")
        if task["state"] != "completed":
            failures.append(f"the task is {task['state']}")
        if task["assigned_agent_id"] != worker:
            failures.append(f"the task was completed for {task['assigned_agent_id']}, not the worker")
        # The turn is over: nothing it held may still be live.
        if binding is not None and binding["state"] == "active":
            failures.append("the turn's credential outlived the turn")
        if lease is not None:
            failures.append("the session lease outlived the turn")
        if turn_dir.exists():
            failures.append(f"the turn's private directory survived: {turn_dir}")
        if run["approval_policy"] != POLICY:
            failures.append(f"the run recorded policy {run['approval_policy']}, not {POLICY}")
        # M4.5's invariant, unchanged by a real provider: a worker's writes are
        # its bound session's, never an assertion.
        asserted = sorted({e["kind"] for e in events if e["payload"].get("trust") == "asserted"})
        if asserted:
            failures.append(f"the worker's writes were unverified: {asserted}")
        if not any(e["payload"].get("trust") == "bound" for e in events):
            kinds = sorted({f"{e['actor']}:{e['kind']}" for e in events})
            failures.append(f"no write from the worker was recorded as bound (its events: {kinds})")
        body = log_tail(run)
        if failures:
            raise LiveGateError(f"{provider}: " + "; ".join(failures) + f"\n--- last of {run['output_ref']} ---\n{body}")
        return {
            "provider": provider, "run": str(run["id"]), "attempts": delivery["attempts"],
            "exit_state": run["exit_state"], "provider_session_id": session["provider_session_id"] if session else None,
            "kinds": sorted({e["kind"] for e in events}), "log": str(run["output_ref"]),
        }


def one_provider(daemon: Daemon, provider: str, command: list[str], root: Path, run: str, timeout: int, narrate) -> dict[str, Any]:
    worker = WORKERS[provider]
    cwd = root / f"work-{provider}"
    cwd.mkdir(parents=True, exist_ok=True)
    agentd(daemon, "roster", "add", worker, "other" if provider == "rehearsal" else provider,
           "worker", "--capability", "bus")
    enrol(daemon, provider, command, cwd, timeout)
    narrate(f"#   {worker} enrolled: {' '.join(command)} (approvals: {POLICY}, one attempt, {timeout}s)")
    work = queue_work(daemon, provider, run)
    narrate("#   one task queued; starting the turn"
            + (" (no quota: the offline worker)" if provider == "rehearsal" else f" (this spends {provider} quota)"))
    output = dispatch_once(daemon, timeout)
    with store_of(daemon) as store:
        runs = store.list_runs(agent_id=worker, limit=1)
    turn_dir = daemon.state_dir / "turns" / str(runs[0]["id"]) if runs else root / "missing"
    result = check_turn(daemon, provider, work, turn_dir)
    result["dispatch_output"] = output
    narrate(f"#   {provider}: {result['exit_state']}, {result['attempts']} attempt, "
            f"worker wrote {', '.join(result['kinds'])}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spend-quota", action="store_true",
                        help="required: this gate starts real model turns that cost money")
    parser.add_argument("--provider", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--rehearse", action="store_true",
                        help="run the same gate against the offline worker: proves every assertion "
                             "is satisfiable, spends nothing, starts no provider")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TURN_TIMEOUT, help="seconds per turn")
    parser.add_argument("--narrate", action="store_true", default=True)
    parser.add_argument("--quiet", dest="narrate", action="store_false")
    parser.add_argument("--keep", action="store_true", help="keep the temporary state directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    wanted = ("codex", "claude") if args.provider == "both" else (args.provider,)
    if args.rehearse:
        wanted = ("rehearsal",)
    if not (args.spend_quota or args.rehearse):
        print("This gate starts real provider turns and spends the user's quota:", file=sys.stderr)
        for provider in wanted:
            print(f"  1 turn of {provider} (up to {args.timeout}s)", file=sys.stderr)
        print("Re-run with --spend-quota once that is approved.", file=sys.stderr)
        return 64

    commands: dict[str, list[str]] = {}
    missing = []
    for provider in wanted:
        if provider == "rehearsal":
            commands[provider] = list(REHEARSAL_COMMAND)
            continue
        found = shutil.which(provider)
        if found is None:
            missing.append(provider)
        else:
            commands[provider] = [found]
    if missing:
        print(f"skip: provider CLI not found: {', '.join(missing)}", file=sys.stderr)
        return SKIP_EXIT

    dim = "\033[2m" if sys.stdout.isatty() else ""
    off = "\033[0m" if sys.stdout.isatty() else ""

    def narrate(text: str) -> None:
        if args.narrate:
            print(f"{dim}{text}{off}", flush=True)

    root = Path(tempfile.mkdtemp(prefix="luciazero-agent-bus-live-"))
    run = f"live-{uuid.uuid4().hex[:10]}"
    daemon = Daemon(root / "state")
    report: dict[str, Any] = {"root": str(root), "turns": []}
    results: list[dict[str, Any]] = []
    try:
        daemon.start()
        narrate(f"# daemon {daemon.url} on {daemon.state_dir} (disposable; the real bus is untouched)")
        agentd(daemon, "roster", "add", ARCHITECT, "codex", "architect", "--capability", "plan")
        daemon.bind(ARCHITECT, "codex")
        narrate(f"# {ARCHITECT} is bound to this terminal and queues the work")
        for provider in wanted:
            narrate(f"# {provider}: one managed turn")
            result = one_provider(daemon, provider, commands[provider], root, run, args.timeout, narrate)
            results.append(result)
            report["turns"].append(result)
    except (E2EError, GateError, StoreError, subprocess.SubprocessError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        daemon.stop()
        if args.keep:
            print(f"kept {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    for result in results:
        print(f"{result['provider']}: {result['exit_state']} in {result['attempts']} attempt; "
              f"the worker itself wrote {', '.join(result['kinds'])}")
    print("no credential, lease, or turn directory outlived its turn")
    label = "rehearsal, no quota" if args.rehearse else ", ".join(r["provider"] for r in results)
    print(f"PASS  agent bus M6 live smoke gate ({label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

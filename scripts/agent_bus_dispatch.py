#!/usr/bin/env python3
"""M6 dispatch gate: the dispatcher is killed mid-run, restarted, and the work
still reaches exactly one outcome.

What one run proves, all offline and with no model:

1. a managed turn happens at all: the dispatcher starts a worker, and the
   worker -- speaking with its own session credential, not the daemon token --
   does the bus procedure and the daemon names it as the actor;
2. killing the dispatcher mid-turn loses nothing and leaks nothing: the
   abandoned run is recovered, the orphan's credential is revoked, the delivery
   goes back for one more attempt, and the work completes on the retry;
3. while a turn is in flight nobody else can start one for the same session,
   and a stale generation is refused;
4. a lease whose holder is gone is reclaimed instead of waiting out its TTL;
5. a turn that exits cleanly without touching the bus is a failed attempt, not
   a completed one -- the dispatcher never speaks for the worker.

The repository, the state directory and both provider homes are disposable
temporary directories.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agentd"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_bus_e2e import ARCHITECT, REVIEWER, SKIP_EXIT, Daemon, E2EError  # noqa: E402
from agent_bus_mcp_gate import GateError, McpClient  # noqa: E402
from luciazero_agentd.store import ConflictError, GenerationFenced, Store, utcnow  # noqa: E402

WORKER = str(ROOT / "scripts" / "agent_bus_worker.py")
DISPATCH_TIMEOUT = 120


class DispatchGateError(E2EError):
    pass


def store_of(daemon: Daemon) -> Store:
    """The driver's own connection. It stands in for a dispatcher when it
    forces a stale lease, so its writes carry the dispatcher's label rather
    than the unproven default."""
    store = Store.open(daemon.state_dir / "bus.sqlite3")
    store.migrate()
    store.trust = "system"
    return store


def cli_env(daemon: Daemon, **extra: str) -> dict[str, str]:
    """Every child gets the disposable state directory as its bus home too, so
    a missing --state-dir can never reach the user's own bus."""
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "agentd"),
                LUCIAZERO_AGENT_BUS_HOME=str(daemon.state_dir), **extra)


def dispatch(daemon: Daemon, *, mode: str = "work", background: bool = False, timeout: int = DISPATCH_TIMEOUT) -> Any:
    """Run the shipped dispatcher as its own process, the way a user would."""
    env = cli_env(daemon, LZ_WORKER_MODE=mode)
    argv = [sys.executable, "-m", "luciazero_agentd", "dispatch", "--state-dir", str(daemon.state_dir)]
    if background:
        return subprocess.Popen(argv, cwd=ROOT / "agentd", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    result = subprocess.run(argv, cwd=ROOT / "agentd", env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise DispatchGateError(f"dispatch exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def wait_for(condition, *, what: str, timeout: float = 30.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise DispatchGateError(f"timed out waiting for {what}")


def enrol(daemon: Daemon, cwd: Path) -> None:
    """The human channel enrols the worker; nothing on the bus can. `worker
    add` takes the command as a REMAINDER, so every flag goes before the --."""
    argv = [sys.executable, "-m", "luciazero_agentd", "worker", "add", REVIEWER, "other",
            "--cwd", str(cwd), "--max-attempts", "3", "--timeout", "60",
            "--state-dir", str(daemon.state_dir), "--", sys.executable, WORKER]
    result = subprocess.run(argv, cwd=ROOT / "agentd", env=cli_env(daemon), capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise DispatchGateError(f"worker add failed: {result.stderr.strip()}")


def open_work(daemon: Daemon, run: str) -> dict[str, Any]:
    """The architect's own bound session queues one task for the worker."""
    bus = daemon.session(ARCHITECT)
    task = bus.call("task_create", {"title": "Handle one managed turn", "created_by": ARCHITECT,
                                    "assigned_to": REVIEWER, "idempotency_key": f"{run}-task"})
    message = bus.call("message_send", {"sender": ARCHITECT, "recipient": REVIEWER, "kind": "task",
                                        "payload": {"task_id": task["id"]}, "idempotency_key": f"{run}-msg"})
    with store_of(daemon) as store:
        delivery = store.inbox(REVIEWER, states=("queued",))["items"][-1]
    return {"task": task["id"], "message": message["id"], "delivery": delivery["delivery_id"]}


def step_killed_mid_turn(daemon: Daemon, work: dict[str, Any]) -> dict[str, Any]:
    """Kill the dispatcher while the provider is still running."""
    child = dispatch(daemon, mode="hang", background=True)
    try:
        def running() -> Optional[dict[str, Any]]:
            with store_of(daemon) as store:
                runs = store.list_runs(state="running", limit=5)
                return runs[0] if runs else None

        try:
            run = wait_for(running, what="a run to start")
        except DispatchGateError:
            child.kill()
            output = child.stdout.read() if child.stdout else ""
            raise DispatchGateError(f"a run never started; the dispatcher said: {output.strip()[:800]}")
        wait_for(lambda: run.get("provider_pid") or running().get("provider_pid"), what="the provider process to be recorded")
        with store_of(daemon) as store:
            run = store.get_run(str(run["id"]))
            binding = store.get_binding(str(run["binding_id"]))
            if binding["state"] != "active":
                raise DispatchGateError("the turn's credential should be live while the turn is running")
            # Nobody else may start a turn for this session while it is held:
            # the lease refuses, and the delivery is no longer dispatchable.
            try:
                store.acquire_lease("session", REVIEWER, holder="dispatch:intruder", session_id=str(run["session_id"]))
            except ConflictError as exc:
                contended = str(exc)
            else:
                raise DispatchGateError("a second holder took the lease while a turn was in flight")
        dispatch(daemon, mode="work")
        with store_of(daemon) as store:
            if len(store.list_runs(limit=10)) != 1:
                raise DispatchGateError("a second run started while the first was still in flight")
            if store.get_delivery(work["delivery"])["state"] not in ("dispatched", "processing"):
                raise DispatchGateError("the delivery should be marked as being worked while its turn runs")
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()
    return {"run": str(run["id"]), "binding": str(run["binding_id"]), "provider_pid": run["provider_pid"], "contended": contended[:120]}


def step_recovered(daemon: Daemon, killed: dict[str, Any], work: dict[str, Any]) -> dict[str, Any]:
    """The next dispatcher settles the abandoned run and finishes the work."""
    output = dispatch(daemon, mode="work")
    with store_of(daemon) as store:
        abandoned = store.get_run(killed["run"])
        if abandoned["state"] != "abandoned":
            raise DispatchGateError(f"the killed run should be abandoned, it is {abandoned['state']}")
        binding = store.get_binding(killed["binding"])
        if binding["state"] == "active":
            raise DispatchGateError("the orphaned provider's credential outlived the dispatcher that minted it")
        delivery = store.get_delivery(work["delivery"])
        if delivery["state"] != "completed":
            raise DispatchGateError(f"the work should have completed on the retry, the delivery is {delivery['state']}")
        if delivery["attempts"] != 2:
            raise DispatchGateError(f"the work should have cost exactly two attempts, it cost {delivery['attempts']}")
        task = store.get_task(work["task"])
        if task["state"] != "completed" or task["assigned_agent_id"] != REVIEWER:
            raise DispatchGateError(f"the worker should have completed the task itself, it is {task['state']} for {task['assigned_agent_id']}")
    return {"output": output, "attempts": 2}


def step_clean_exit_is_not_progress(daemon: Daemon, run: str) -> dict[str, Any]:
    """A turn that exits 0 without touching the bus is a failed attempt."""
    work = open_work(daemon, run)
    dispatch(daemon, mode="idle")
    with store_of(daemon) as store:
        delivery = store.get_delivery(work["delivery"])
        if delivery["state"] != "retryable_failed":
            raise DispatchGateError(f"a turn that did nothing should leave the delivery retryable, it is {delivery['state']}")
        latest = store.list_runs(limit=1)[0]
        if latest["state"] != "failed" or latest["exit_state"] != "exit 0":
            raise DispatchGateError(f"the run should be failed with a clean exit recorded, it is {latest['state']} / {latest['exit_state']}")
    return {"delivery": work["delivery"], "task": work["task"]}


def step_fencing_and_reclaim(daemon: Daemon, work: dict[str, Any]) -> dict[str, Any]:
    """A stale generation is refused, and a lease whose holder is gone is taken
    rather than waited out."""
    with store_of(daemon) as store:
        session = store.ensure_session(REVIEWER, provider="other")
        stale = store.acquire_lease("session", REVIEWER, holder="dispatch:stale", session_id=session["id"],
                                    holder_pid=424242, holder_started_at=utcnow())
        fresh_generation = int(stale["generation"])
        try:
            store.record_provider_session(str(session["id"]), provider_session_id="thread-old", generation=fresh_generation - 1)
        except GenerationFenced as exc:
            fenced = str(exc)
        else:
            raise DispatchGateError("a stale generation was allowed to write to the session")
        held = store.lease_on("session", REVIEWER)
        if held is None or held["expires_at"] <= utcnow():
            raise DispatchGateError("the stale lease should still be inside its TTL for this test to mean anything")
    # The holder pid is dead, so the dispatcher takes the lease instead of
    # waiting five minutes for it to expire.
    dispatch(daemon, mode="work")
    with store_of(daemon) as store:
        delivery = store.get_delivery(work["delivery"])
        if delivery["state"] != "completed":
            raise DispatchGateError(f"the reclaimed session should have finished the work, the delivery is {delivery['state']}")
    return {"fenced": fenced}


def snapshot(daemon: Daemon) -> dict[str, Any]:
    with store_of(daemon) as store:
        events, after = [], 0
        while True:
            page = store.events(after=after, limit=500)
            if not page:
                break
            events.extend(page)
            after = page[-1]["seq"]
        return {
            "counts": store.counts(),
            "runs": [{"id": r["id"], "state": r["state"], "attempt": r["attempt"], "exit_state": r["exit_state"]} for r in store.list_runs(limit=50)],
            "deliveries": {d["delivery_id"]: d["delivery_state"] for d in store.inbox(REVIEWER, states=("queued", "dispatched", "processing", "acknowledged", "completed", "retryable_failed", "dead_letter"), limit=100)["items"]},
            "event_kinds": [e["kind"] for e in events],
            "trust": sorted({e["payload"].get("trust") for e in events}),
            "asserted_writes": [e["kind"] for e in events if e["payload"].get("trust") == "asserted"],
            "leases": store.list_leases(),
            # Only managed bindings are the dispatcher's to clean up: the
            # architect's own terminal binding is a human's and stays.
            "bindings": [b for b in store.list_bindings(states=("active",), alive=None) if b["ownership"] == "managed"],
        }


REQUIRED_EVENTS = ("worker.enrolled", "lease.acquired", "lease.reclaimed", "delivery.dispatched",
                   "run.started", "run.finished", "delivery.retryable_failed", "binding.revoked")


def assert_outcome(snap: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    for kind in REQUIRED_EVENTS:
        if kind not in snap["event_kinds"]:
            failures.append(f"no {kind} event was recorded")
    if snap["asserted_writes"]:
        failures.append(f"unverified writes reached the log: {sorted(set(snap['asserted_writes']))}")
    if "system" not in snap["trust"]:
        failures.append("the dispatcher's own writes are not labelled system")
    if "bound" not in snap["trust"]:
        failures.append("the worker's writes are not labelled bound; a managed turn must speak with its own credential")
    if snap["leases"]:
        failures.append(f"{len(snap['leases'])} lease(s) outlived the run that took them")
    if snap["bindings"]:
        failures.append(f"{len(snap['bindings'])} credential(s) outlived the turn that minted them")
    abandoned = [r for r in snap["runs"] if r["state"] == "abandoned"]
    completed = [r for r in snap["runs"] if r["state"] == "completed"]
    if len(abandoned) != 1:
        failures.append(f"exactly one run should have been abandoned by the kill, {len(abandoned)} were")
    if not completed:
        failures.append("no run completed; the work never reached an outcome")
    if failures:
        raise DispatchGateError("; ".join(failures))
    return {"runs": len(snap["runs"]), "completed": len(completed), "abandoned": len(abandoned)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--narrate", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if shutil.which("git") is None:
        print("skip: required tool not found: git", file=sys.stderr)
        return SKIP_EXIT

    dim = "\033[2m" if sys.stdout.isatty() else ""
    off = "\033[0m" if sys.stdout.isatty() else ""

    def narrate(text: str) -> None:
        if args.narrate:
            print(f"{dim}{text}{off}", flush=True)

    root = Path(tempfile.mkdtemp(prefix="luciazero-agent-bus-dispatch-"))
    run = f"dsp-{uuid.uuid4().hex[:10]}"
    daemon = Daemon(root / "state")
    report: dict[str, Any] = {"root": str(root), "steps": []}
    try:
        daemon.start()
        narrate(f"# daemon {daemon.url} on {daemon.state_dir}")
        # The architect is a person at a terminal; the reviewer is not bound by
        # hand, because a human-owned session is one the dispatcher may never
        # take (ADR 0001), and this gate is about the ones it may.
        daemon.cli("roster", "add", ARCHITECT, "codex", "architect")
        daemon.cli("roster", "add", REVIEWER, "claude", "reviewer", "--capability", "review")
        daemon.bind(ARCHITECT, "codex")
        narrate(f"#   {ARCHITECT} is bound to this terminal; {REVIEWER} is a managed worker")
        enrol(daemon, root)
        narrate(f"# the user enrolled {REVIEWER} as a managed worker")
        work = open_work(daemon, run)
        report["steps"].append({"step": "queued", **work})
        narrate("# step 1: the dispatcher starts a turn, and is killed while the provider runs")
        killed = step_killed_mid_turn(daemon, work)
        report["steps"].append({"step": "killed mid-turn", **killed})
        narrate("# step 2: the next dispatcher recovers the abandoned run and finishes the work")
        report["steps"].append({"step": "recovered", **step_recovered(daemon, killed, work)})
        narrate("# step 3: a turn that exits cleanly without touching the bus is a failed attempt")
        second = step_clean_exit_is_not_progress(daemon, f"{run}-idle")
        report["steps"].append({"step": "clean exit is not progress", **second})
        narrate("# step 4: a stale generation is fenced, and a dead holder's lease is reclaimed")
        report["steps"].append({"step": "fencing", **step_fencing_and_reclaim(daemon, second)})
        snap = snapshot(daemon)
        report["records"] = snap
        report["outcome"] = assert_outcome(snap)
    except (E2EError, GateError, subprocess.SubprocessError, OSError) as exc:
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
    counts, outcome = snap["counts"], report["outcome"]
    print(f"records: runs {counts['runs']} deliveries {counts['deliveries']} leases {counts['leases']} events {counts['events']}")
    print(f"runs: {outcome['completed']} completed, {outcome['abandoned']} abandoned by the kill; no lease or credential outlived its turn")
    print("PASS  agent bus M6 dispatch gate (fake provider)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

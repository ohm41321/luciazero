#!/usr/bin/env python3
"""M5 workflow gate: a task graph, its stoppers, and artifact provenance,
driven end to end through the shipped daemon with a deterministic fake
provider (no quota, no provider CLIs).

What one run proves:

1. a dependency graph executes in order -- `fix` opens, `verify` and `report`
   wait, and each opens exactly when its own prerequisites complete;
2. a graph containing a cycle is refused before anything is written;
3. an infinite reply loop stops at the daemon's hop cap, and the refusal is
   recorded rather than silently dropped;
4. a per-task budget is a stop: the send that would overspend it exhausts the
   task, dead-letters its queued work, and blocks what waited on it;
5. artifact provenance survives the whole flow: the commit the implementer
   published still names the implementer after the reviewer cites it, and every
   record carries the trust its producer's session had.

Everything runs on disposable temporary directories: the repository, both
worktrees and the bus state directory. Nothing under the user's home is read
or written, and no provider CLI is involved.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agentd"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_bus_e2e import (  # noqa: E402
    ARCHITECT,
    CHECK,
    FIXED,
    IMPLEMENTER,
    REVIEWER,
    SKIP_EXIT,
    Daemon,
    E2EError,
    Workspace,
    git,
    register,
    run_check,
)
from agent_bus_mcp_gate import GateError, McpClient  # noqa: E402
from luciazero_agentd.store import MAX_HOPS, Store  # noqa: E402


def expect_error(bus: McpClient, tool: str, arguments: dict[str, Any], expected: str) -> str:
    """Call a tool that must be refused, and return the refusal text."""
    try:
        bus.call(tool, arguments)
    except GateError as exc:
        if expected not in str(exc):
            raise E2EError(f"{tool} was refused, but not for {expected}: {exc}") from exc
        return str(exc)
    raise E2EError(f"{tool} was accepted; the daemon owes a {expected} refusal")


def states(bus: McpClient, ids: dict[str, str]) -> dict[str, str]:
    return {name: bus.call("task_get", {"task_id": task_id})["state"] for name, task_id in ids.items()}


# --------------------------------------------------------------------- turns
def turn_cycle_is_refused(bus: McpClient, run: str) -> dict[str, Any]:
    """A graph that cannot be executed is refused whole, before any of it is
    written: a half-built graph would leave tasks nothing can ever open."""
    register(bus, ARCHITECT, "codex", "architect", ["plan"])
    before = len(bus.call("task_list", {})["items"])
    message = expect_error(bus, "task_graph_create", {
        "created_by": ARCHITECT,
        "nodes": [
            {"key": "a", "title": "a waits for c", "depends_on": ["c"]},
            {"key": "b", "title": "b waits for a", "depends_on": ["a"]},
            {"key": "c", "title": "c waits for b", "depends_on": ["b"]},
        ],
    }, "cycle")
    after = len(bus.call("task_list", {})["items"])
    if after != before:
        raise E2EError(f"the refused graph left {after - before} task(s) behind")
    return {"refusal": message.split("message")[-1].strip()[:120], "tasks_written": after - before}


def turn_architect_plans(bus: McpClient, ws: Workspace, run: str) -> dict[str, Any]:
    """One transaction creates the whole plan: fix, then verify, then report."""
    tasks = bus.call("task_graph_create", {
        "created_by": ARCHITECT,
        "idempotency_key": f"{run}-plan",
        "nodes": [
            {"key": "fix", "title": "Fix split_fields so quoted segments stay whole",
             "assigned_to": IMPLEMENTER, "requires_worktree": True,
             "payload": {"paths": ["fields.py"], "check": " ".join(CHECK[1:])}},
            {"key": "verify", "title": "Verify the split_fields fix commit",
             "assigned_to": REVIEWER, "requires_worktree": True, "depends_on": ["fix"],
             "payload": {"check": " ".join(CHECK[1:])}},
            {"key": "report", "title": "Report the outcome to the user",
             "assigned_to": ARCHITECT, "depends_on": ["verify"]},
        ],
    })["tasks"]
    ids = {"fix": tasks[0]["id"], "verify": tasks[1]["id"], "report": tasks[2]["id"]}
    if [t["state"] for t in tasks] != ["open", "waiting", "waiting"]:
        raise E2EError(f"a fresh graph must open only its roots, got {[t['state'] for t in tasks]}")
    bus.call("message_send", {"sender": ARCHITECT, "recipient": IMPLEMENTER, "kind": "task",
                              "payload": {"task_id": ids["fix"], "verify_task": ids["verify"]},
                              "idempotency_key": f"{run}-fix-msg"})
    return {"ids": ids}


def turn_implementer_fixes(bus: McpClient, ws: Workspace, run: str, ids: dict[str, str]) -> dict[str, Any]:
    register(bus, IMPLEMENTER, "codex", "implementer", ["edit"])
    bus.call("worktree_bind", {"agent_id": IMPLEMENTER, "path": str(ws.implementer_wt)})
    # The verify task exists and is assigned to a peer, but nothing may claim
    # it while the work it verifies is unfinished.
    refusal = expect_error(bus, "task_claim", {"task_id": ids["verify"], "agent_id": IMPLEMENTER}, "waiting")
    if ids["fix"] not in refusal:
        raise E2EError("a waiting task must name the prerequisite it waits on")
    bus.call("task_claim", {"task_id": ids["fix"], "agent_id": IMPLEMENTER})
    (ws.implementer_wt / "fields.py").write_text(FIXED, encoding="utf-8")
    ok, output = run_check(ws.implementer_wt)
    if not ok:
        raise E2EError(f"fix did not turn the check green:\n{output}")
    git(ws.implementer_wt, "add", "fields.py")
    git(ws.implementer_wt, "commit", "-q", "-m", "fix: keep quoted segments whole in split_fields")
    oid = git(ws.implementer_wt, "rev-parse", "HEAD")
    artifact = bus.call("artifact_publish", {"kind": "commit", "ref": oid, "produced_by": IMPLEMENTER,
                                             "task_id": ids["fix"], "idempotency_key": f"{run}-fix-art"})
    bus.call("task_record_usage", {"task_id": ids["fix"], "agent_id": IMPLEMENTER, "tokens": 1200, "cost_usd": 0.02})
    bus.call("task_complete", {"task_id": ids["fix"], "agent_id": IMPLEMENTER,
                               "result": {"commit": oid, "check": "green"}, "artifacts": [artifact["id"]]})
    after = states(bus, ids)
    if after != {"fix": "completed", "verify": "open", "report": "waiting"}:
        raise E2EError(f"completing the fix must open only the verify task, got {after}")
    bus.call("message_send", {"sender": IMPLEMENTER, "recipient": REVIEWER, "kind": "artifact",
                              "payload": {"artifact": artifact["id"], "task_id": ids["verify"]},
                              "idempotency_key": f"{run}-artifact-msg"})
    return {"artifact": artifact["id"], "commit": oid}


def turn_reviewer_verifies(bus: McpClient, ws: Workspace, run: str, ids: dict[str, str], artifact_id: str) -> dict[str, Any]:
    register(bus, REVIEWER, "claude", "reviewer", ["review", "verify"])
    bus.call("worktree_bind", {"agent_id": REVIEWER, "path": str(ws.reviewer_wt)})
    bus.call("task_claim", {"task_id": ids["verify"], "agent_id": REVIEWER})
    # Provenance is read from the record, not from the message that pointed here.
    listed = bus.call("artifact_list", {"task_id": ids["fix"]})["items"]
    if [a["id"] for a in listed] != [artifact_id]:
        raise E2EError(f"the fix task must carry exactly the published commit, got {[a['id'] for a in listed]}")
    artifact = listed[0]
    if artifact["produced_by_agent_id"] != IMPLEMENTER or artifact["trust"] != "bound":
        raise E2EError(f"artifact provenance is wrong: {artifact['produced_by_agent_id']} / {artifact['trust']}")
    oid = artifact["ref"]
    git(ws.reviewer_wt, "cat-file", "-e", f"{oid}^{{commit}}")
    git(ws.reviewer_wt, "merge", "-q", "--ff-only", oid)
    ok, output = run_check(ws.reviewer_wt)
    if not ok:
        raise E2EError(f"the published commit is not green in the reviewer worktree:\n{output}")
    report = ws.reviewer_wt / "reports" / "verification.md"
    report.write_text(f"# Verification of {oid}\n\nCheck is green on the reviewer worktree.\n", encoding="utf-8")
    published = bus.call("artifact_publish", {"kind": "report", "ref": "reports/verification.md", "produced_by": REVIEWER,
                                              "task_id": ids["verify"], "idempotency_key": f"{run}-verify-art"})
    bus.call("task_complete", {"task_id": ids["verify"], "agent_id": REVIEWER,
                               "result": {"commit": oid, "check": "green"},
                               "artifacts": [artifact_id, published["id"]]})
    after = states(bus, ids)
    if after != {"fix": "completed", "verify": "completed", "report": "open"}:
        raise E2EError(f"completing the verify task must open the report task, got {after}")
    return {"report_artifact": published["id"], "verdict": "green"}


def turn_architect_closes(bus: McpClient, ids: dict[str, str], artifact_id: str) -> dict[str, Any]:
    bus.call("task_claim", {"task_id": ids["report"], "agent_id": ARCHITECT})
    view = bus.call("task_get", {"task_id": ids["verify"]})
    cited = view["result"]["artifacts"]
    if artifact_id not in cited:
        raise E2EError("the verification result does not cite the commit it verified")
    # Citing an artifact never rewrites who produced it.
    commit = bus.call("artifact_get", {"artifact_id": artifact_id})
    if commit["produced_by_agent_id"] != IMPLEMENTER:
        raise E2EError(f"the cited commit changed hands: {commit['produced_by_agent_id']}")
    expect_error(bus, "task_complete", {"task_id": ids["report"], "agent_id": ARCHITECT, "artifacts": ["art_missing"]}, "does not exist")
    bus.call("task_complete", {"task_id": ids["report"], "agent_id": ARCHITECT,
                               "result": {"outcome": "verified"}, "artifacts": cited})
    return {"cited": cited}


def turn_reply_loop_stops(bus: McpClient, peer: McpClient, run: str) -> dict[str, Any]:
    """Two agents answering each other forever: the daemon counts the hops and
    stops the conversation, whatever the models intend."""
    first = bus.call("message_send", {"sender": ARCHITECT, "recipient": REVIEWER, "kind": "question", "payload": {"q": "again?"}})
    correlation = first["correlation_id"]
    sender, other = peer, bus
    names = (REVIEWER, ARCHITECT)
    for hop in range(MAX_HOPS):
        sender.call("message_send", {"sender": names[hop % 2], "recipient": names[(hop + 1) % 2],
                                     "kind": "question", "payload": {"q": "again?"}, "correlation_id": correlation})
        sender, other = other, sender
    refusal = expect_error(sender, "message_send", {
        "sender": names[MAX_HOPS % 2], "recipient": names[(MAX_HOPS + 1) % 2],
        "kind": "question", "payload": {"q": "again?"}, "correlation_id": correlation}, "hop limit")
    return {"correlation_id": correlation, "hops": MAX_HOPS + 1, "refusal": refusal.split("text")[-1][:80]}


def turn_budget_stops_a_task(bus: McpClient, reviewer: McpClient, run: str) -> dict[str, Any]:
    """A budget is a stop, not a warning."""
    bounded = bus.call("task_create", {"title": "Bounded investigation", "created_by": ARCHITECT,
                                       "assigned_to": REVIEWER, "budget": {"turns": 2},
                                       "idempotency_key": f"{run}-bounded"})
    dependent = bus.call("task_create", {"title": "Summarise the investigation", "created_by": ARCHITECT,
                                         "depends_on": [bounded["id"]], "idempotency_key": f"{run}-dependent"})
    for index in range(2):
        bus.call("message_send", {"sender": ARCHITECT, "recipient": REVIEWER, "kind": "task",
                                  "payload": {"task_id": bounded["id"], "turn": index}})
    expect_error(bus, "message_send", {"sender": ARCHITECT, "recipient": REVIEWER, "kind": "task",
                                       "payload": {"task_id": bounded["id"], "turn": 2}}, "budget")
    stopped = bus.call("task_get", {"task_id": bounded["id"]})
    if stopped["state"] != "exhausted" or stopped["result"]["dimension"] != "turns":
        raise E2EError(f"a spent budget must stop the task, got {stopped['state']} {stopped.get('result')}")
    if bus.call("task_get", {"task_id": dependent["id"]})["state"] != "blocked":
        raise E2EError("a task waiting on a stopped task must be blocked, not left waiting forever")
    # The recipient reads its own inbox: a session may not name a peer.
    queued = [i for i in reviewer.call("message_inbox", {"agent_id": REVIEWER})["items"] if i["payload"].get("task_id") == bounded["id"]]
    if queued:
        raise E2EError(f"{len(queued)} queued delivery(ies) survived the stop; nobody should be asked to start that turn")
    expect_error(reviewer, "task_claim", {"task_id": bounded["id"], "agent_id": REVIEWER}, "exhausted")
    return {"task": bounded["id"], "dependent": dependent["id"], "spent": stopped["spent"]}


# ----------------------------------------------------------------- assertions
def snapshot(db: Path) -> dict[str, Any]:
    with Store.open(db) as store:
        store.migrate()
        events, after = [], 0
        while True:  # the hop-limit walk alone writes more events than one page holds
            page = store.events(after=after, limit=500)
            if not page:
                break
            events.extend(page)
            after = page[-1]["seq"]
        tasks = store.list_tasks(limit=100)["items"]
        return {
            "counts": store.counts(),
            "tasks": {t["id"]: t["state"] for t in tasks},
            "event_kinds": [e["kind"] for e in events],
            "asserted_writes": [e["kind"] for e in events if e["payload"].get("trust") == "asserted"],
            "artifacts": store.list_artifacts()["items"],
        }


REQUIRED_EVENTS = ("task_graph.created", "task.unblocked", "task.blocked", "task.exhausted",
                   "conversation.hop_limit", "delivery.dead_letter", "artifact.published")


def assert_outcome(snap: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    for kind in REQUIRED_EVENTS:
        if kind not in snap["event_kinds"]:
            failures.append(f"no {kind} event was recorded")
    if snap["asserted_writes"]:
        failures.append(f"unverified writes reached the log: {sorted(set(snap['asserted_writes']))}")
    unblocked = snap["event_kinds"].count("task.unblocked")
    if unblocked != 2:
        failures.append(f"a three-step graph unblocks twice, not {unblocked} time(s)")
    # verify -> fix, report -> verify, and the budget test's dependent -> bounded
    if snap["counts"]["task_deps"] != 3:
        failures.append(f"the run should record 3 edges, found {snap['counts']['task_deps']}")
    trust = {a["trust"] for a in snap["artifacts"]}
    if trust != {"bound"}:
        failures.append(f"artifacts must record a bound producer, found {sorted(trust)}")
    if failures:
        raise E2EError("; ".join(failures))
    return {"events": len(snap["event_kinds"]), "artifacts": len(snap["artifacts"]), "unblocked": unblocked}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--narrate", action="store_true", help="print each step and a bus status snapshot")
    parser.add_argument("--keep", action="store_true", help="leave the temporary directory behind")
    parser.add_argument("--json", action="store_true", help="print the record snapshot as JSON")
    args = parser.parse_args()
    if shutil.which("git") is None:
        print("skip: required tool not found: git", file=sys.stderr)
        return SKIP_EXIT

    dim = "\033[2m" if sys.stdout.isatty() else ""
    off = "\033[0m" if sys.stdout.isatty() else ""

    def narrate(text: str) -> None:
        if args.narrate:
            print(f"{dim}{text}{off}", flush=True)

    root = Path(tempfile.mkdtemp(prefix="luciazero-agent-bus-workflow-"))
    run = f"wf-{uuid.uuid4().hex[:10]}"
    ws = Workspace(root)
    daemon = Daemon(root / "state")
    report: dict[str, Any] = {"root": str(root), "steps": []}
    try:
        ws.create()
        daemon.start()
        narrate(f"# daemon {daemon.url} on {daemon.state_dir}")
        for line in daemon.roster():
            narrate(f"#   {line}")
        architect = daemon.session(ARCHITECT)
        narrate("# step 1: a graph with a cycle is refused before anything is written")
        report["steps"].append({"step": "cycle refused", **turn_cycle_is_refused(architect, run)})
        narrate("# step 2: the architect plans fix -> verify -> report in one transaction")
        plan = turn_architect_plans(architect, ws, run)
        ids = plan["ids"]
        report["steps"].append({"step": "graph created", **plan})
        narrate("# step 3: the implementer cannot claim the waiting task, fixes, publishes the commit")
        fixed = turn_implementer_fixes(daemon.session(IMPLEMENTER), ws, run, ids)
        report["steps"].append({"step": "fix", **fixed})
        narrate("# step 4: the reviewer reads provenance from the record and verifies")
        verified = turn_reviewer_verifies(daemon.session(REVIEWER), ws, run, ids, fixed["artifact"])
        report["steps"].append({"step": "verify", **verified})
        narrate("# step 5: the architect closes the report task citing the same artifacts")
        report["steps"].append({"step": "close", **turn_architect_closes(architect, ids, fixed["artifact"])})
        narrate("# step 6: a reply loop stops at the hop cap")
        report["steps"].append({"step": "loop stopped", **turn_reply_loop_stops(architect, daemon.session(REVIEWER), run)})
        narrate("# step 7: a spent turn budget stops a task and blocks what waited on it")
        report["steps"].append({"step": "budget stop", **turn_budget_stops_a_task(architect, daemon.session(REVIEWER), run)})
        if args.narrate:
            narrate(daemon.status_text())
        snap = snapshot(daemon.state_dir / "bus.sqlite3")
        report["records"] = snap
        report["outcome"] = assert_outcome(snap)
    except (E2EError, GateError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        print(f"FAIL: {exc}\n{detail}".rstrip(), file=sys.stderr)
        return 1
    finally:
        daemon.stop()
        if args.keep:
            print(f"kept {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    counts = snap["counts"]
    print(f"records: tasks {counts['tasks']} edges {counts['task_deps']} messages {counts['messages']} "
          f"artifacts {counts['artifacts']} events {counts['events']}")
    print(f"graph: {' -> '.join(f'{name} {state}' for name, state in states_of(snap, ids).items())}")
    print(f"stoppers: hop limit {MAX_HOPS} refused one send; a spent turn budget stopped one task and blocked its dependent")
    print("PASS  agent bus M5 workflow gate (fake provider)")
    return 0


def states_of(snap: dict[str, Any], ids: dict[str, str]) -> dict[str, str]:
    return {name: snap["tasks"].get(task_id, "missing") for name, task_id in ids.items()}


if __name__ == "__main__":
    raise SystemExit(main())

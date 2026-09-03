#!/usr/bin/env python3
"""M4 pull-beta vertical slice: the roadmap's outcome flow end to end.

    codex-architect   creates a review task
    claude-reviewer   reads it, reports a finding (report artifact)
    codex-architect   turns the finding into a fix task and a verify task
                      -- daemon restart --
    codex-implementer fixes it in its own worktree, publishes the commit
    claude-reviewer   (new session, same agent id) claims the verify task,
                      checks the commit in its own worktree, reports
    codex-architect   receives the final result

Everything moves through the shipped daemon and its MCP tools: every turn
opens a fresh MCP session and learns what to do only from its inbox, the
task list, and artifact records, never from Python variables of an earlier
turn. Provider homes, the bus state directory, the repository and both
worktrees are disposable temporary directories; nothing under the user's
home is read or written.

Fake provider (default, deterministic, no quota): each turn is a scripted
client that does what the `/lucia-bus` skill tells a model to do.

Live provider (`--live`, opt-in, spends quota): each turn is one real
`codex` App Server turn or one `claude -p` invocation given the same goal
and the skill text; the driver then asserts the bus reached the same state.
Requires `LZ_AGENT_BUS_LIVE=1`. `--live --dry-run` prints the plan only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agentd"))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_bus_spike as spike  # noqa: E402
from agent_bus_mcp_gate import GateError, McpClient  # noqa: E402
from luciazero_agentd.statedir import read_endpoint, read_token  # noqa: E402
from luciazero_agentd.store import Store  # noqa: E402

SERVER_NAME = "luciazero-bus"
TOKEN_ENV = "LUCIAZERO_AGENT_BUS_TOKEN"
ARCHITECT, REVIEWER, IMPLEMENTER = "codex-architect", "claude-reviewer", "codex-implementer"
SKIP_EXIT = 3
CHECK = [sys.executable, "-m", "unittest", "-q", "test_fields"]

GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="agent-bus-demo", GIT_AUTHOR_EMAIL="demo@example.invalid",
    GIT_COMMITTER_NAME="agent-bus-demo", GIT_COMMITTER_EMAIL="demo@example.invalid",
    GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
)

BUGGY = 'def split_fields(record):\n    return record.split(";")\n'
FIXED = '''def split_fields(record):
    """Split on ';' but keep quoted segments whole."""
    fields, current, quoted = [], [], False
    for ch in record:
        if ch == '"':
            quoted = not quoted
        elif ch == ";" and not quoted:
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields
'''
TESTS = '''import unittest

from fields import split_fields


class SplitTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(split_fields("a;b"), ["a", "b"])

    def test_quoted_segment_stays_whole(self):
        self.assertEqual(split_fields('a;"x;y";b'), ["a", "x;y", "b"])


if __name__ == "__main__":
    unittest.main()
'''


class E2EError(RuntimeError):
    pass


def git(path: Path | str, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


def run_check(cwd: Path) -> tuple[bool, str]:
    result = subprocess.run(CHECK, cwd=cwd, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=60)
    return result.returncode == 0, (result.stderr or result.stdout).strip()


# ------------------------------------------------------------------ fixtures
class Workspace:
    """Disposable repository with one worktree per writing worker."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.reviewer_wt = root / "wt-reviewer"
        self.implementer_wt = root / "wt-implementer"

    def create(self) -> None:
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, capture_output=True, env=GIT_ENV)
        (self.repo / "fields.py").write_text(BUGGY, encoding="utf-8")
        (self.repo / "test_fields.py").write_text(TESTS, encoding="utf-8")
        (self.repo / "reports").mkdir()
        (self.repo / "reports" / ".keep").write_text("", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed: split_fields ignores quotes")
        git(self.repo, "worktree", "add", "-q", "-b", "review", str(self.reviewer_wt))
        git(self.repo, "worktree", "add", "-q", "-b", "fix-quoted-fields", str(self.implementer_wt))


class Daemon:
    """The shipped daemon as a subprocess on a disposable state directory."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.proc: Optional[subprocess.Popen[str]] = None
        self.url = ""
        self.token = ""
        self.pids: list[int] = []

    def start(self) -> None:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "agentd"))
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "luciazero_agentd", "serve", "--state-dir", str(self.state_dir), "--port", "0"],
            cwd=ROOT / "agentd", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            endpoint = read_endpoint(self.state_dir)
            if endpoint and endpoint.get("pid") == self.proc.pid:
                self.url = endpoint["url"]
                break
            if self.proc.poll() is not None:
                raise E2EError(f"daemon exited early: {self.proc.stderr.read() if self.proc.stderr else ''}")
            time.sleep(0.05)
        else:
            raise E2EError("daemon did not publish endpoint.json")
        token = read_token(self.state_dir)
        if not token:
            raise E2EError("daemon did not write a token")
        self.token = token
        self.pids.append(self.proc.pid)

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        if self.proc.stderr:
            self.proc.stderr.close()
        self.proc = None

    def restart(self) -> None:
        self.stop()
        if read_endpoint(self.state_dir) is not None:
            raise E2EError("endpoint.json survived a clean stop")
        self.start()

    def session(self) -> McpClient:
        client = McpClient(self.url, self.token)
        client.initialize()
        return client

    def cli(self, *args: str) -> str:
        """The human channel: the same commands the user types."""
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "agentd"))
        result = subprocess.run([sys.executable, "-m", "luciazero_agentd", *args, "--state-dir", str(self.state_dir)], cwd=ROOT / "agentd", env=env, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise E2EError(f"luciazero-agentd {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def status_text(self) -> str:
        return self.cli("status")

    def roster(self) -> list[str]:
        """The user names the team once, so the architect can address peers
        whose sessions the user has not started yet."""
        return [
            self.cli("roster", "add", ARCHITECT, "codex", "architect", "--capability", "plan"),
            self.cli("roster", "add", REVIEWER, "claude", "reviewer", "--capability", "review", "--capability", "verify"),
            self.cli("roster", "add", IMPLEMENTER, "codex", "implementer", "--capability", "edit"),
        ]


# --------------------------------------------------------------- fake turns
def register(bus: McpClient, agent_id: str, provider: str, role: str, capabilities: Optional[list[str]] = None) -> None:
    bus.call("agent_register", {"agent_id": agent_id, "provider": provider, "role": role, "capabilities": capabilities or []})


def inbox_item(bus: McpClient, agent_id: str, kind: str) -> dict[str, Any]:
    items = bus.call("message_inbox", {"agent_id": agent_id})["items"]
    matching = [i for i in items if i["kind"] == kind]
    if not matching:
        raise E2EError(f"{agent_id} expected a queued {kind} message, inbox has {[i['kind'] for i in items]}")
    item = matching[0]
    bus.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": agent_id})
    return item


def finish(bus: McpClient, agent_id: str, item: dict[str, Any]) -> None:
    bus.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": agent_id, "outcome": "completed"})


def turn_architect_opens(bus: McpClient, ws: Workspace, run: str) -> dict[str, Any]:
    register(bus, ARCHITECT, "codex", "architect", ["plan"])
    task = bus.call("task_create", {
        "title": "Review fields.py: split_fields must keep quoted segments whole",
        "created_by": ARCHITECT, "assigned_to": REVIEWER,
        "payload": {"paths": ["fields.py", "test_fields.py"], "check": " ".join(CHECK[1:])},
        "idempotency_key": f"{run}-review",
    })
    sent = bus.call("message_send", {
        "sender": ARCHITECT, "recipient": REVIEWER, "kind": "task",
        "payload": {"task_id": task["id"], "paths": ["fields.py", "test_fields.py"]},
        "idempotency_key": f"{run}-review-msg",
    })
    return {"task": task["id"], "message": sent["id"]}


def turn_reviewer_finds(bus: McpClient, ws: Workspace, run: str) -> dict[str, Any]:
    register(bus, REVIEWER, "claude", "reviewer", ["review", "verify"])
    bus.call("worktree_bind", {"agent_id": REVIEWER, "path": str(ws.reviewer_wt)})
    item = inbox_item(bus, REVIEWER, "task")
    task_id = item["payload"]["task_id"]
    bus.call("task_claim", {"task_id": task_id, "agent_id": REVIEWER})
    ok, output = run_check(ws.reviewer_wt)
    if ok:
        raise E2EError("the seeded bug should make the check fail")
    report = ws.reviewer_wt / "reports" / "finding.md"
    report.write_text(f"# Finding\n\nCheck `{ ' '.join(CHECK[1:]) }` is red in {ws.reviewer_wt.name}:\n\n```\n{output}\n```\n\n`split_fields` splits inside quotes.\n", encoding="utf-8")
    artifact = bus.call("artifact_publish", {"kind": "report", "ref": "reports/finding.md", "produced_by": REVIEWER, "task_id": task_id, "idempotency_key": f"{run}-finding-art"})
    bus.call("task_complete", {"task_id": task_id, "agent_id": REVIEWER, "result": {"outcome": "finding", "artifact": artifact["id"], "check": "red"}})
    bus.call("message_send", {
        "sender": REVIEWER, "recipient": ARCHITECT, "kind": "finding",
        "payload": {"task_id": task_id, "artifact": artifact["id"], "summary": "split_fields splits inside quoted segments; check is red"},
        "reply_to": item["message_id"], "correlation_id": item["correlation_id"], "idempotency_key": f"{run}-finding-msg",
    })
    finish(bus, REVIEWER, item)
    return {"artifact": artifact["id"]}


def turn_architect_dispatches(bus: McpClient, ws: Workspace, run: str) -> dict[str, Any]:
    item = inbox_item(bus, ARCHITECT, "finding")
    fix = bus.call("task_create", {
        "title": "Fix split_fields so quoted segments stay whole", "created_by": ARCHITECT, "assigned_to": IMPLEMENTER,
        "payload": {"finding_artifact": item["payload"]["artifact"], "paths": ["fields.py"], "check": " ".join(CHECK[1:])},
        "requires_worktree": True, "idempotency_key": f"{run}-fix",
    })
    verify = bus.call("task_create", {
        "title": "Verify the split_fields fix commit", "created_by": ARCHITECT, "assigned_to": REVIEWER,
        "payload": {"check": " ".join(CHECK[1:])}, "requires_worktree": True, "idempotency_key": f"{run}-verify",
    })
    bus.call("message_send", {
        "sender": ARCHITECT, "recipient": IMPLEMENTER, "kind": "task",
        "payload": {"task_id": fix["id"], "finding_artifact": item["payload"]["artifact"], "verify_task": verify["id"]},
        "reply_to": item["message_id"], "correlation_id": item["correlation_id"], "idempotency_key": f"{run}-fix-msg",
    })
    finish(bus, ARCHITECT, item)
    return {"fix": fix["id"], "verify": verify["id"]}


def turn_implementer_fixes(bus: McpClient, ws: Workspace, run: str) -> dict[str, Any]:
    register(bus, IMPLEMENTER, "codex", "implementer", ["edit"])
    bus.call("worktree_bind", {"agent_id": IMPLEMENTER, "path": str(ws.implementer_wt)})
    item = inbox_item(bus, IMPLEMENTER, "task")
    task_id = item["payload"]["task_id"]
    bus.call("task_claim", {"task_id": task_id, "agent_id": IMPLEMENTER})
    finding = bus.call("artifact_get", {"artifact_id": item["payload"]["finding_artifact"]})
    producer_wt = bus.call("worktree_get", {"agent_id": finding["produced_by_agent_id"]})["path"]
    finding_text = (Path(producer_wt) / finding["ref"]).read_text(encoding="utf-8")
    if "quotes" not in finding_text:
        raise E2EError("the finding report did not arrive through the bus")
    (ws.implementer_wt / "fields.py").write_text(FIXED, encoding="utf-8")
    ok, output = run_check(ws.implementer_wt)
    if not ok:
        raise E2EError(f"fix did not turn the check green:\n{output}")
    git(ws.implementer_wt, "add", "fields.py")
    git(ws.implementer_wt, "commit", "-q", "-m", "fix: keep quoted segments whole in split_fields")
    oid = git(ws.implementer_wt, "rev-parse", "HEAD")
    artifact = bus.call("artifact_publish", {"kind": "commit", "ref": oid, "produced_by": IMPLEMENTER, "task_id": task_id, "idempotency_key": f"{run}-fix-art"})
    bus.call("task_complete", {"task_id": task_id, "agent_id": IMPLEMENTER, "result": {"artifact": artifact["id"], "commit": oid, "check": "green"}})
    bus.call("message_send", {
        "sender": IMPLEMENTER, "recipient": REVIEWER, "kind": "artifact",
        "payload": {"artifact": artifact["id"], "verify_task": item["payload"]["verify_task"], "fixed_task": task_id},
        "reply_to": item["message_id"], "correlation_id": item["correlation_id"], "idempotency_key": f"{run}-artifact-msg",
    })
    finish(bus, IMPLEMENTER, item)
    return {"commit": oid}


def turn_reviewer_verifies(bus: McpClient, ws: Workspace, run: str) -> dict[str, Any]:
    register(bus, REVIEWER, "claude", "reviewer", ["review", "verify"])  # new session, same stable id
    bus.call("worktree_bind", {"agent_id": REVIEWER, "path": str(ws.reviewer_wt)})
    item = inbox_item(bus, REVIEWER, "artifact")
    open_tasks = bus.call("task_list", {"state": "open", "assigned_to": REVIEWER})["items"]
    verify = next((t for t in open_tasks if t["id"] == item["payload"]["verify_task"]), None)
    if verify is None:
        raise E2EError(f"verify task {item['payload']['verify_task']} is not open for {REVIEWER}: {[t['id'] for t in open_tasks]}")
    bus.call("task_claim", {"task_id": verify["id"], "agent_id": REVIEWER})
    artifact = bus.call("artifact_get", {"artifact_id": item["payload"]["artifact"]})
    oid = artifact["ref"]
    git(ws.reviewer_wt, "cat-file", "-e", f"{oid}^{{commit}}")  # shared object store: visible without a fetch
    export = ws.root / "verify-export"
    export.mkdir()
    archive = export / "tree.tar"
    with open(archive, "wb") as handle:
        subprocess.run(["git", "-C", str(ws.reviewer_wt), "archive", oid], check=True, stdout=handle, env=GIT_ENV)
    with tarfile.open(archive) as tar:
        if hasattr(tarfile, "data_filter"):  # 3.12+: silence the extraction warning, our own archive
            tar.extractall(export, filter="data")
        else:
            tar.extractall(export)  # noqa: S202
    ok, output = run_check(export)
    verdict = "green" if ok else "red"
    report = ws.reviewer_wt / "reports" / "verification.md"
    report.write_text(f"# Verification of {oid}\n\nCheck is {verdict} on the exported tree.\n\n```\n{output}\n```\n", encoding="utf-8")
    published = bus.call("artifact_publish", {"kind": "report", "ref": "reports/verification.md", "produced_by": REVIEWER, "task_id": verify["id"], "idempotency_key": f"{run}-verify-art"})
    bus.call("task_complete", {"task_id": verify["id"], "agent_id": REVIEWER, "result": {"commit": oid, "check": verdict, "artifact": published["id"]}, "outcome": "completed" if ok else "blocked"})
    bus.call("message_send", {
        "sender": REVIEWER, "recipient": ARCHITECT, "kind": "result",
        "payload": {"commit": oid, "check": verdict, "artifact": published["id"], "verify_task": verify["id"]},
        "reply_to": item["message_id"], "correlation_id": item["correlation_id"], "idempotency_key": f"{run}-result-msg",
    })
    finish(bus, REVIEWER, item)
    if not ok:
        raise E2EError(f"verification is red:\n{output}")
    return {"verified_commit": oid}


def turn_architect_receives(bus: McpClient, ws: Workspace, run: str) -> dict[str, Any]:
    item = inbox_item(bus, ARCHITECT, "result")
    finish(bus, ARCHITECT, item)
    return {"correlation_id": item["correlation_id"], "commit": item["payload"]["commit"], "check": item["payload"]["check"]}


Turn = Callable[[McpClient, Workspace, str], dict[str, Any]]
PLAN: list[tuple[str, str, str, Turn]] = [
    (ARCHITECT, "codex", "opens a review task and sends it to the reviewer", turn_architect_opens),
    (REVIEWER, "claude", "reads the inbox, claims, runs the check, publishes a finding report", turn_reviewer_finds),
    (ARCHITECT, "codex", "reads the finding, creates fix + verify tasks, dispatches the fix", turn_architect_dispatches),
    (IMPLEMENTER, "codex", "reads the finding through the bus, fixes in its own worktree, publishes the commit", turn_implementer_fixes),
    (REVIEWER, "claude", "new session, same id: claims the verify task, checks the commit, reports", turn_reviewer_verifies),
    (ARCHITECT, "codex", "receives the final result", turn_architect_receives),
]
RESTART_BEFORE_TURN = 4  # 1-based: between the finding and the fix


# --------------------------------------------------------------- live turns
SKILL_TEXT = (ROOT / "skills" / "lucia-bus" / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[-1].strip()


def live_prompt(agent_id: str, worktree: Optional[Path], goal: str) -> str:
    where = f"Your git worktree is {worktree}; bind it with worktree_bind and work only there. " if worktree else ""
    return (
        f'You are the agent "{agent_id}" on the Luciazero Agent Bus (MCP server "{SERVER_NAME}"). {where}'
        f"Goal for this turn: {goal} Follow the procedure below exactly, then reply with one line: DONE <correlation_id>.\n\n{SKILL_TEXT}"
    )


LIVE_GOALS = {
    1: f"create the task 'Review fields.py: split_fields must keep quoted segments whole' assigned to {REVIEWER} with payload paths [fields.py, test_fields.py] and check 'python3 -m unittest -q test_fields', then message_send it as kind task to {REVIEWER}.",
    2: "acknowledge the task, claim it, run the check in your worktree (it is red), write reports/finding.md describing the failure, publish it as a report artifact, complete the task, and message_send a finding back to the sender with the artifact id.",
    3: f"acknowledge the finding, create a fix task for {IMPLEMENTER} (requires_worktree true, payload finding_artifact and paths [fields.py]) and a verify task for {REVIEWER} (requires_worktree true), then message_send the fix task to {IMPLEMENTER} including finding_artifact and verify_task ids.",
    4: "acknowledge the task, claim it, read the finding report through artifact_get and worktree_get of its producer, fix fields.py so quoted segments stay whole, run the check until green, commit, publish the commit id as a commit artifact, complete the task, and message_send an artifact message to the reviewer with the artifact id and verify_task.",
    5: "acknowledge the artifact message, claim the open verify task assigned to you, read the commit through artifact_get, prove it is green on an export of that commit in your worktree, write reports/verification.md, publish it, complete the verify task, and message_send a result to the architect.",
    6: "acknowledge the result message and mark it completed.",
}


class LiveRunner:
    """One real provider turn per plan step. Codex through App Server (the
    proven M0/M2 path: on-request approvals answered by the adapter), Claude
    through `claude -p` with the bus passed by --mcp-config."""

    def __init__(self, daemon: Daemon, ws: Workspace, dry_run: bool) -> None:
        self.daemon, self.ws, self.dry_run = daemon, ws, dry_run
        self.codex, self.claude = shutil.which("codex"), shutil.which("claude")

    def worktree_for(self, agent_id: str) -> Optional[Path]:
        return {REVIEWER: self.ws.reviewer_wt, IMPLEMENTER: self.ws.implementer_wt}.get(agent_id)

    def run_turn(self, index: int, agent_id: str, provider: str) -> str:
        worktree = self.worktree_for(agent_id)
        prompt = live_prompt(agent_id, worktree, LIVE_GOALS[index])
        cwd = worktree or self.ws.repo
        if self.dry_run:
            return f"[dry-run] {provider} turn {index} for {agent_id} in {cwd}:\n{prompt[:400]}..."
        if provider == "codex":
            return self.codex_turn(prompt, cwd)
        return self.claude_turn(prompt, cwd)

    def codex_turn(self, prompt: str, cwd: Path) -> str:
        assert self.codex
        env = dict(os.environ, **{TOKEN_ENV: self.daemon.token})
        overrides = [f'mcp_servers.{SERVER_NAME}.url="{self.daemon.url}"', f'mcp_servers.{SERVER_NAME}.bearer_token_env_var="{TOKEN_ENV}"']
        with spike.rpc_process(self.codex, env, overrides) as process:
            started = process.request("thread/start", {"cwd": str(cwd), "sandbox": "workspace-write", "approvalPolicy": "on-request"})
            process.request("turn/start", {"threadId": started["thread"]["id"], "input": [{"type": "text", "text": prompt}]}, timeout=60)
            messages = process.collect_until("turn/completed", timeout=600)
        text = json.dumps(spike.items_of_type(messages, {"agentMessage"}), default=str)
        if "DONE" not in text:
            raise E2EError("Codex turn did not report DONE: " + text[:800])
        return text

    def claude_turn(self, prompt: str, cwd: Path) -> str:
        assert self.claude
        mcp_config = json.dumps({"mcpServers": {SERVER_NAME: {"type": "http", "url": self.daemon.url, "headers": {"Authorization": f"Bearer {self.daemon.token}"}}}})
        # `--allowedTools` is variadic: keep a single-value option between it and the prompt.
        result = spike.run([self.claude, "-p", "--permission-mode", "bypassPermissions", "--mcp-config", mcp_config, "--strict-mcp-config", "--output-format", "json", prompt], cwd=cwd, timeout=600)
        text = spike.claude_result_text(result)
        if "DONE" not in text:
            raise E2EError("Claude turn did not report DONE: " + text[:800])
        return text


# ------------------------------------------------------------------ driver
def snapshot(db: Path) -> dict[str, Any]:
    with Store.open(db) as store:
        store.migrate()
        tasks = store.list_tasks(limit=100)["items"]
        events = store.events(limit=500)
        artifacts = [store.get_artifact(e["entity_id"]) for e in events if e["kind"] == "artifact.published"]
        messages = [store.get_message(e["entity_id"]) for e in events if e["kind"] == "message.sent"]
        deliveries = [store.get_delivery(e["payload"]["delivery_id"]) for e in events if e["kind"] == "message.sent"]
        return {
            "counts": store.counts(),
            "tasks": [{"id": t["id"], "title": t["title"], "state": t["state"], "assigned_to": t["assigned_agent_id"], "requires_worktree": t["requires_worktree"]} for t in tasks],
            "messages": [{"id": m["id"], "kind": m["kind"], "from": m["sender_agent_id"], "to": m["recipient_agent_id"], "correlation_id": m["correlation_id"]} for m in messages],
            "deliveries": [{"id": d["id"], "state": d["state"]} for d in deliveries],
            "artifacts": [{"id": a["id"], "kind": a["kind"], "ref": a["ref"], "by": a["produced_by_agent_id"]} for a in artifacts],
            "event_kinds": [e["kind"] for e in events],
            "worktrees": [store.get_worktree(a) for a in (REVIEWER, IMPLEMENTER)],
        }


def assert_outcome(snap: dict[str, Any], daemon: Daemon, ws: Workspace, first_message: str) -> dict[str, Any]:
    failures = []
    if [t["state"] for t in snap["tasks"]] != ["completed"] * 3:
        failures.append(f"tasks: {snap['tasks']}")
    if [t["assigned_to"] for t in snap["tasks"]] != [REVIEWER, IMPLEMENTER, REVIEWER]:
        failures.append(f"task holders: {[t['assigned_to'] for t in snap['tasks']]}")
    if [m["kind"] for m in snap["messages"]] != ["task", "finding", "task", "artifact", "result"]:
        failures.append(f"messages: {[m['kind'] for m in snap['messages']]}")
    correlations = {m["correlation_id"] for m in snap["messages"]}
    if correlations != {first_message}:
        failures.append(f"correlation ids drifted: {correlations}")
    if any(d["state"] != "completed" for d in snap["deliveries"]):
        failures.append(f"deliveries not all completed: {snap['deliveries']}")
    if [a["kind"] for a in snap["artifacts"]] != ["report", "commit", "report"]:
        failures.append(f"artifacts: {snap['artifacts']}")
    if [a["by"] for a in snap["artifacts"]] != [REVIEWER, IMPLEMENTER, REVIEWER]:
        failures.append(f"artifact producers: {[a['by'] for a in snap['artifacts']]}")
    if [m["from"] for m in snap["messages"]] != [ARCHITECT, REVIEWER, ARCHITECT, IMPLEMENTER, REVIEWER]:
        failures.append(f"message senders: {[m['from'] for m in snap['messages']]}")
    if len(daemon.pids) != 2 or daemon.pids[0] == daemon.pids[1]:
        failures.append(f"daemon did not restart: pids {daemon.pids}")
    if snap["event_kinds"].count("worktree.bound") < 3 or "worktree.mismatch" in snap["event_kinds"]:
        failures.append("worktree binding evidence missing or a mismatch occurred")
    expected_worktrees = [os.path.realpath(ws.reviewer_wt), os.path.realpath(ws.implementer_wt)]
    if [w["path"] for w in snap["worktrees"]] != expected_worktrees:
        failures.append(f"writers must hold their own worktrees: {[w['path'] for w in snap['worktrees']]} != {expected_worktrees}")
    if snap["counts"]["approvals"] != 0:
        failures.append("no approval should have been needed")
    if failures:
        raise E2EError("outcome flow did not reach the roadmap state:\n  " + "\n  ".join(failures))
    return {"correlation_id": first_message, "commit": next(a["ref"] for a in snap["artifacts"] if a["kind"] == "commit"), "daemon_pids": daemon.pids, "leases": snap["counts"]["leases"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="real provider turns (needs LZ_AGENT_BUS_LIVE=1)")
    parser.add_argument("--dry-run", action="store_true", help="with --live: print the turn plan and prompts, spend nothing")
    parser.add_argument("--narrate", action="store_true", help="print each turn and a bus status snapshot")
    parser.add_argument("--keep", action="store_true", help="leave the temporary directory behind")
    parser.add_argument("--json", action="store_true", help="print the record snapshot as JSON")
    args = parser.parse_args()
    if args.dry_run and not args.live:
        parser.error("--dry-run only makes sense with --live")
    if args.live and not args.dry_run and os.environ.get("LZ_AGENT_BUS_LIVE") != "1":
        print("live mode spends provider quota: set LZ_AGENT_BUS_LIVE=1 after explicit approval, or use --dry-run", file=sys.stderr)
        return 2
    if shutil.which("git") is None:
        print("skip: required tool not found: git", file=sys.stderr)
        return SKIP_EXIT
    if args.live and not args.dry_run:
        missing = [n for n in ("codex", "claude") if shutil.which(n) is None]
        if missing:
            print(f"skip: required CLI not found: {', '.join(missing)}", file=sys.stderr)
            return SKIP_EXIT

    dim = "\033[2m" if sys.stdout.isatty() else ""
    off = "\033[0m" if sys.stdout.isatty() else ""

    def narrate(text: str) -> None:
        if args.narrate:
            print(f"{dim}{text}{off}", flush=True)

    root = Path(tempfile.mkdtemp(prefix="luciazero-agent-bus-e2e-"))
    run = f"e2e-{uuid.uuid4().hex[:10]}"
    ws = Workspace(root)
    daemon = Daemon(root / "state")
    report: dict[str, Any] = {"mode": "live" if args.live else "fake", "root": str(root), "turns": []}
    try:
        ws.create()
        narrate(f"# disposable repo {ws.repo} with worktrees review/ and fix-quoted-fields/; state dir {daemon.state_dir}")
        daemon.start()
        narrate(f"# daemon {daemon.url} (pid {daemon.pids[-1]})")
        narrate("# the user names the team once (luciazero-agentd roster add ...):")
        for line in daemon.roster():
            narrate(f"#   {line}")
        live = LiveRunner(daemon, ws, args.dry_run) if args.live else None
        first_message: Optional[str] = None
        for index, (agent_id, provider, description, turn) in enumerate(PLAN, start=1):
            if index == RESTART_BEFORE_TURN:
                daemon.restart()
                narrate(f"# daemon restarted between the finding and the fix (pid {daemon.pids[-2]} -> {daemon.pids[-1]}); the queue survived")
            narrate(f"# turn {index}: {agent_id} ({provider}) {description}")
            if live is not None:
                output = live.run_turn(index, agent_id, provider)
                report["turns"].append({"turn": index, "agent": agent_id, "output": output[:400]})
                if args.dry_run:
                    print(output)
                    continue
                if index == 1:
                    with Store.open(daemon.state_dir / "bus.sqlite3") as store:
                        first_message = next(e["entity_id"] for e in store.events(limit=50) if e["kind"] == "message.sent")
            else:
                bus = daemon.session()
                result = turn(bus, ws, run)
                report["turns"].append({"turn": index, "agent": agent_id, **result})
                if index == 1:
                    first_message = result["message"]
            if index == 3:
                narrate("# what the user sees before starting the next turn:")
                narrate(daemon.status_text())
        if args.live and args.dry_run:
            print("PASS  agent bus M4 live plan rendered (nothing spent)")
            return 0
        assert first_message is not None
        snap = snapshot(daemon.state_dir / "bus.sqlite3")
        report["records"] = snap
        report["outcome"] = assert_outcome(snap, daemon, ws, first_message)
    except (E2EError, GateError, spike.SpikeError, subprocess.CalledProcessError) as exc:
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
    outcome = report["outcome"]
    print(f"records: tasks {snap['counts']['tasks']} messages {snap['counts']['messages']} deliveries {snap['counts']['deliveries']} artifacts {snap['counts']['artifacts']} events {snap['counts']['events']} worktrees {snap['counts']['worktrees']} leases {outcome['leases']} (reserved for M6)")
    print(f"final correlation id: {outcome['correlation_id']}   verified commit: {outcome['commit']}   daemon pids: {outcome['daemon_pids']}")
    print("PASS  agent bus M4 pull-beta vertical slice " + ("(live providers)" if args.live else "(fake provider)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

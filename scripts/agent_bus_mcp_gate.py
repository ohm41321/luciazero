#!/usr/bin/env python3
"""M2 exit gate: both real CLIs discover the shipped daemon's tool contract
through disposable homes, and one structured message travels through it.

Offline (default): starts the daemon in-process on a temporary state
directory, registers it in a throwaway CODEX_HOME and CLAUDE_CONFIG_DIR with
the bearer token, checks each CLI initialises against it (Codex must also list
the same tool contract), then runs the pull-beta exchange through a raw MCP
client, including the M3 worktree binding a publish now requires.

Live (--live, opt-in, spends quota): the Codex model sends a message through
message_send and the Claude model reads and acknowledges it through
message_inbox and message_ack. Two turns per provider at most.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agentd"))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_bus_spike as spike  # noqa: E402  (M0 helpers: run, rpc_process, versions)
from luciazero_agentd.server import TOOLS, BusServer  # noqa: E402
from luciazero_agentd.store import Store  # noqa: E402

SERVER_NAME = "luciazero-bus"
TOKEN_ENV = "LUCIAZERO_AGENT_BUS_TOKEN"
SKIP_EXIT = 3
TOOL_NAMES = [t["name"] for t in TOOLS]


class GateError(RuntimeError):
    pass


class McpClient:
    """Raw Streamable HTTP client: enough to prove the exchange without a model."""

    def __init__(self, url: str, token: str) -> None:
        self.url, self.token, self.session, self.counter = url, token, None, 0

    def rpc(self, method: str, params: Optional[dict[str, Any]] = None, *, notify: bool = False) -> Any:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.counter += 1
            payload["id"] = self.counter
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 202:
                return None
            self.session = response.headers.get("Mcp-Session-Id", self.session)
            body = json.loads(response.read())
        if "error" in body:
            raise GateError(f"{method} failed: {body['error']}")
        return body["result"]

    def initialize(self) -> None:
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "agent-bus-mcp-gate", "version": "0"}})
        self.rpc("notifications/initialized", notify=True)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise GateError(f"tool {name} returned an error: {result['content'][0]['text']}")
        return result["structuredContent"]


def codex_discovery(codex: str, url: str, token: str, temporary: Path) -> dict[str, Any]:
    home = temporary / "codex-home"
    home.mkdir()
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    env[TOKEN_ENV] = token
    spike.run([codex, "mcp", "add", SERVER_NAME, "--url", url, "--bearer-token-env-var", TOKEN_ENV], env=env)
    with spike.rpc_process(codex, env) as process:
        result = process.request("mcpServerStatus/list", {"detail": "full"})
    records = [r for r in result.get("data", []) if isinstance(r, dict) and r.get("name") == SERVER_NAME]
    if not records:
        raise GateError("Codex did not report the bus server")
    tools = sorted((records[0].get("tools") or {}).keys())
    if tools != sorted(TOOL_NAMES):
        raise GateError(f"Codex tool list differs from the contract: {tools}")
    return {"tools": len(tools), "server_info": (records[0].get("serverInfo") or {}).get("name")}


def claude_discovery(claude: str, url: str, token: str, temporary: Path) -> dict[str, Any]:
    home = temporary / "claude-home"
    home.mkdir()
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(home)
    spike.run([claude, "mcp", "add", "--scope", "user", "--transport", "http", SERVER_NAME, url, "--header", f"Authorization: Bearer {token}"], env=env)
    listed = spike.run([claude, "mcp", "list"], env=env)
    if SERVER_NAME not in listed.stdout or "Connected" not in listed.stdout:
        raise GateError("Claude did not report the bus server as connected")
    return {"connected": True}


def make_repo(path: Path) -> str:
    """A disposable git repository the reviewer binds as its worktree (M3)."""
    env = dict(os.environ, GIT_AUTHOR_NAME="gate", GIT_AUTHOR_EMAIL="gate@example.invalid", GIT_COMMITTER_NAME="gate",
               GIT_COMMITTER_EMAIL="gate@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    path.mkdir(parents=True, exist_ok=True)
    (path / "reports").mkdir()
    (path / "reports" / "bus.md").write_text("# bus review\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main", "."], ["add", "-A"], ["commit", "-q", "-m", "gate fixture"]):
        spike.run(["git", *args], cwd=path, env=env)
    return os.path.realpath(str(path))


def exchange(client: McpClient, db: str, repo: str) -> dict[str, Any]:
    token = f"lz-m2-{uuid.uuid4().hex[:12]}"
    client.call("agent_register", {"agent_id": "codex-architect", "provider": "codex", "role": "architect"})
    client.call("agent_register", {"agent_id": "claude-reviewer", "provider": "claude", "role": "reviewer"})
    bound = client.call("worktree_bind", {"agent_id": "claude-reviewer", "path": repo})
    if bound.get("path") != repo or bound.get("branch") != "main":
        raise GateError(f"worktree_bind recorded {bound!r}, expected {repo} on main")
    task = client.call("task_create", {"title": "review the bus", "created_by": "codex-architect", "idempotency_key": f"{token}-task"})
    sent = client.call("message_send", {"sender": "codex-architect", "recipient": "claude-reviewer", "kind": "task", "payload": {"task_id": task["id"], "probe": token}, "idempotency_key": f"{token}-msg"})
    replay = client.call("message_send", {"sender": "codex-architect", "recipient": "claude-reviewer", "kind": "task", "payload": {"task_id": task["id"], "probe": token}, "idempotency_key": f"{token}-msg"})
    if replay["id"] != sent["id"]:
        raise GateError("replayed message_send created a second message")
    inbox = client.call("message_inbox", {"agent_id": "claude-reviewer"})
    item = next(i for i in inbox["items"] if i["message_id"] == sent["id"])
    client.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": "claude-reviewer"})
    client.call("task_claim", {"task_id": task["id"], "agent_id": "claude-reviewer"})
    artifact = client.call("artifact_publish", {"kind": "report", "ref": "reports/bus.md", "produced_by": "claude-reviewer", "task_id": task["id"]})
    client.call("task_complete", {"task_id": task["id"], "agent_id": "claude-reviewer", "result": {"artifact": artifact["id"]}})
    reply = client.call("message_send", {"sender": "claude-reviewer", "recipient": "codex-architect", "kind": "result", "payload": {"artifact": artifact["id"]}, "reply_to": sent["id"], "correlation_id": sent["correlation_id"]})
    client.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": "claude-reviewer", "outcome": "completed"})
    with Store.open(db) as store:
        if store.get_task(task["id"])["state"] != "completed" or store.get_delivery(item["delivery_id"])["state"] != "completed":
            raise GateError("store does not reflect the completed exchange")
        events = [e["kind"] for e in store.events(limit=500)]
    return {"correlation_id": reply["correlation_id"], "events": len(events), "final_event": events[-1]}


def codex_live(codex: str, url: str, token: str) -> dict[str, str]:
    env = os.environ.copy()
    env[TOKEN_ENV] = token
    marker = f"lz-codex-bus-{uuid.uuid4().hex[:12]}"
    overrides = [f'mcp_servers.{SERVER_NAME}.url="{url}"', f'mcp_servers.{SERVER_NAME}.bearer_token_env_var="{TOKEN_ENV}"']
    with spike.rpc_process(codex, env, overrides) as process:
        started = process.request("thread/start", {"cwd": str(ROOT), "sandbox": "read-only", "approvalPolicy": "on-request"})
        thread_id = started["thread"]["id"]
        prompt = (
            f'Using the MCP server "{SERVER_NAME}": call message_send with sender "codex-architect", '
            f'recipient "claude-reviewer", kind "finding", payload {{"marker": "{marker}"}}. '
            "Reply with exactly the message id the tool returned and nothing else."
        )
        process.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": prompt}], "clientUserMessageId": marker}, timeout=60)
        messages = process.collect_until("turn/completed", timeout=180)
    agent_text = spike.items_of_type(messages, {"agentMessage"})
    if not spike.find_text(agent_text, "msg_"):
        raise GateError("Codex model did not report a message id; " + json.dumps(spike.items_of_type(messages, {"mcpToolCall", "agentMessage"}), default=str)[:1500])
    return {"marker": marker}


def claude_live(claude: str, url: str, token: str, marker: str) -> dict[str, str]:
    mcp_config = json.dumps({"mcpServers": {SERVER_NAME: {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}}})
    allowed = ",".join(f"mcp__{SERVER_NAME}__{t}" for t in ("agent_register", "message_inbox", "message_ack"))
    prompt = (
        f'Using the MCP server "{SERVER_NAME}": call message_inbox with agent_id "claude-reviewer", find the delivery whose payload '
        'contains a "marker", call message_ack with that delivery_id and agent_id "claude-reviewer", then reply with exactly the marker value and nothing else.'
    )
    result = spike.run([claude, "-p", "--output-format", "json", "--permission-mode", "dontAsk", "--tools", "", "--mcp-config", mcp_config, "--strict-mcp-config", "--allowedTools", allowed, prompt], cwd=ROOT, timeout=180)
    text = spike.claude_result_text(result)
    if marker not in text:
        raise GateError(f"Claude model did not return the marker; got {text[:300]!r}")
    return {"marker": marker}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--only", choices=["codex", "claude"], default=None)
    args = parser.parse_args()
    codex, claude = shutil.which("codex"), shutil.which("claude")
    missing = [n for n, p in (("codex", codex), ("claude", claude)) if p is None]
    if missing:
        print(f"skip: required CLI not found: {', '.join(missing)}", file=sys.stderr)
        return SKIP_EXIT
    assert codex and claude
    report: dict[str, Any] = {"codex_version": spike.command_version("codex"), "claude_version": spike.command_version("claude"), "mode": "live" if args.live else "offline"}
    token = f"lz-gate-{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="luciazero-agent-bus-m2-") as path:
        temporary = Path(path)
        db = str(temporary / "bus.sqlite3")
        with Store.open(db) as store:
            store.migrate()
        with BusServer(db, token, port=0) as server:
            report["daemon"] = server.url
            report["codex_discovery"] = codex_discovery(codex, server.url, token, temporary)
            report["claude_discovery"] = claude_discovery(claude, server.url, token, temporary)
            sessions = server.discovery()
            clients = sorted({str(s["client"]) for s in sessions})
            if not {"codex-mcp-client", "claude-code"} <= set(clients):
                raise GateError(f"daemon saw clients {clients}, expected both CLIs")
            for name in ("codex-mcp-client", "claude-code"):
                methods = {m for s in sessions if s["client"] == name for m in s["methods"]}
                if "tools/list" not in methods:
                    raise GateError(f"{name} initialised but never listed tools: {sorted(methods)}")
            report["daemon_sessions"] = sessions
            client = McpClient(server.url, token)
            client.initialize()
            report["exchange"] = exchange(client, db, make_repo(temporary / "repo"))
            if args.live:
                marker = None
                if args.only in (None, "codex"):
                    marker = codex_live(codex, server.url, token)["marker"]
                    with Store.open(db) as store:
                        inbox = store.inbox("claude-reviewer")["items"]
                    if not any(i["payload"].get("marker") == marker for i in inbox):
                        raise GateError("Codex message did not reach the claude-reviewer inbox")
                    report["codex_live"] = {"marker": marker, "queued_for_claude": True}
                if args.only in (None, "claude"):
                    if marker is None:  # claude-only: seed the inbox through the raw client
                        marker = f"lz-seed-{uuid.uuid4().hex[:12]}"
                        client.call("message_send", {"sender": "codex-architect", "recipient": "claude-reviewer", "kind": "finding", "payload": {"marker": marker}})
                    report["claude_live"] = claude_live(claude, server.url, token, marker)
                    with Store.open(db) as store:
                        acked = [i for i in store.inbox("claude-reviewer", states=("acknowledged", "completed"))["items"] if i["payload"].get("marker") == marker]
                    if not acked:
                        raise GateError("Claude model did not acknowledge the delivery in the store")
                    report["claude_live"]["acknowledged_in_store"] = True
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print("PASS  agent bus M2 " + ("live cross-vendor exchange" if args.live else "offline discovery + exchange"))
    if not args.live:
        print("note  model tool use over the daemon needs --live after approving provider quota")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GateError, spike.SpikeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)

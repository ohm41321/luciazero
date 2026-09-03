#!/usr/bin/env python3
"""M0 protocol spike for Codex App Server, Claude resume, and shared MCP.

The default test exercises only local protocol and configuration surfaces. The
live mode performs two inference turns per provider and therefore requires an
explicit caller opt-in.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


COMMAND_TIMEOUT = 20
RPC_TIMEOUT = 20
SKIP_EXIT = 3


class SpikeError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = COMMAND_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SpikeError(f"command timed out: {command[0]}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise SpikeError(f"command failed ({result.returncode}): {command[0]}{suffix}")
    return result


def command_version(command: str) -> str:
    path = shutil.which(command)
    if path is None:
        raise SpikeError(f"required CLI not found: {command}")
    output = run([path, "--version"]).stdout.strip()
    if not re.search(r"\d+\.\d+", output):
        raise SpikeError(f"could not parse {command} version: {output!r}")
    return output.splitlines()[-1]


class JsonRpcProcess:
    def __init__(self, command: list[str], env: dict[str, str]):
        self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self._process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )
        self._next_id = 1
        self.notifications: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _write(self, payload: dict[str, Any]) -> None:
        if self._process.poll() is not None:
            raise SpikeError(self._process_error("app-server exited"))
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)

    def request(
        self, method: str, params: dict[str, Any] | None = None, timeout: int = RPC_TIMEOUT
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SpikeError(f"app-server request timed out: {method}")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise SpikeError(f"app-server request timed out: {method}") from exc
            if line is None:
                raise SpikeError(self._process_error("app-server closed stdout"))
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise SpikeError(f"{method} failed: {message['error']}")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise SpikeError(f"{method} returned a non-object result")
                return result
            if "id" in message and "method" in message:
                self.requests.append(message)
                self._reply_to_server_request(message)
            else:
                self.notifications.append(message)

    def collect_until(self, method: str, timeout: int = 120) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        collected: list[dict[str, Any]] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SpikeError(f"app-server notification timed out: {method}")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise SpikeError(f"app-server notification timed out: {method}") from exc
            if line is None:
                raise SpikeError(self._process_error("app-server closed stdout"))
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in message and "method" in message:
                self.requests.append(message)
                self._reply_to_server_request(message)
                continue
            collected.append(message)
            self.notifications.append(message)
            if message.get("method") == method:
                return collected

    def _reply_to_server_request(self, message: dict[str, Any]) -> None:
        """Answer server-to-client requests the way a managed-worker adapter
        would under a user-configured "approve MCP tool calls" policy.

        Recorded 2026-09-02 (codex-cli 0.152.1): under approvalPolicy "never"
        an MCP tool call fails with "MCP tool call requires approval, but
        approval policy is never" and never reaches the server. The adapter
        must therefore run "on-request" and answer the approval request
        itself; every request is kept in ``self.requests`` as evidence.
        """
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        result: dict[str, Any]
        if method in ("item/commandExecution/requestApproval", "execCommandApproval",
                      "item/fileChange/requestApproval", "applyPatchApproval"):
            result = {"decision": "accept"}
        elif method == "item/permissions/requestApproval":
            result = {"permissions": params.get("permissions") or {}, "scope": "turn"}
        elif method == "item/tool/requestUserInput":
            result = {"answers": {}}
        elif method == "mcpServer/elicitation/request":
            result = {"action": "accept", "content": {}}
        else:
            result = {}
        self._write({"id": message["id"], "result": result})

    def _process_error(self, prefix: str) -> str:
        self._stderr.seek(0)
        detail = self._stderr.read().strip().splitlines()
        return f"{prefix}: {detail[-1]}" if detail else prefix

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
        self._stderr.close()

    def __enter__(self) -> "JsonRpcProcess":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


TOKEN_ENV = "LZ_AGENT_BUS_SPIKE_TOKEN"
SERVER_NAME = "agent-bus-spike"


class McpProbe:
    """Minimal Streamable HTTP MCP responder.

    When ``token`` is set every request must carry ``Authorization: Bearer
    <token>``; anything else is recorded and answered 401, so a client that
    reaches ``tools/list`` has proven it can deliver the capability token.
    """

    def __init__(self, token: str | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self.token = token
        self._lock = threading.Lock()
        probe = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "LuciazeroMcpSpike/0"

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                if self.path != "/mcp":
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 1024 * 1024:
                        raise ValueError("invalid content length")
                    payload = json.loads(self.rfile.read(length))
                except (ValueError, json.JSONDecodeError):
                    self.send_error(400)
                    return
                method = payload.get("method")
                params = payload.get("params") or {}
                auth_ok = probe.token is None or (
                    self.headers.get("Authorization") == f"Bearer {probe.token}"
                )
                with probe._lock:
                    probe.events.append(
                        {
                            "method": method,
                            "client": (params.get("clientInfo") or {}).get("name"),
                            "user_agent": self.headers.get("User-Agent"),
                            "auth_ok": auth_ok,
                            "token": (params.get("arguments") or {}).get("token")
                            if method == "tools/call"
                            else None,
                        }
                    )
                if not auth_ok:
                    body = json.dumps(
                        {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32001, "message": "unauthorized"}}
                    ).encode("utf-8")
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if "id" not in payload:
                    self.send_response(202)
                    self.end_headers()
                    return
                if method == "initialize":
                    result = {
                        "protocolVersion": payload.get("params", {}).get(
                            "protocolVersion", "2025-06-18"
                        ),
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "luciazero-agent-bus-spike", "version": "0"},
                    }
                elif method == "tools/list":
                    result = {
                        "tools": [
                            {
                                "name": "spike_echo",
                                "description": "Return an M0 correlation token.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"token": {"type": "string"}},
                                    "required": ["token"],
                                    "additionalProperties": False,
                                },
                            }
                        ]
                    }
                elif method == "tools/call":
                    token = payload.get("params", {}).get("arguments", {}).get("token", "")
                    result = {"content": [{"type": "text", "text": token}]}
                elif method == "ping":
                    result = {}
                else:
                    self._json_response(
                        {"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32601, "message": "method not found"}}
                    )
                    return
                self._json_response({"jsonrpc": "2.0", "id": payload["id"], "result": result})

            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                self.send_response(405)
                self.send_header("Allow", "POST")
                self.end_headers()

            def do_DELETE(self) -> None:  # noqa: N802 - stdlib callback name
                self.send_response(200)
                self.end_headers()

            def _json_response(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/mcp"

    def __enter__(self) -> "McpProbe":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def event_count(self) -> int:
        with self._lock:
            return len(self.events)

    def methods_since(self, index: int, *, authenticated: bool = True) -> set[str]:
        with self._lock:
            return {
                str(event["method"])
                for event in self.events[index:]
                if event["auth_ok"] or not authenticated
            }

    def tool_call_tokens(self, index: int = 0) -> list[str]:
        with self._lock:
            return [
                str(event["token"])
                for event in self.events[index:]
                if event["method"] == "tools/call" and event["auth_ok"] and event["token"]
            ]


def negative_control(probe: McpProbe) -> None:
    """Prove the probe rejects a token-less request, so a green discovery
    result cannot be vacuous."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "no-token"}}}
    ).encode("utf-8")
    request = urllib.request.Request(
        probe.url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise SpikeError(f"probe answered a token-less request with {exc.code}, expected 401")
        return
    raise SpikeError("probe accepted a request without the bearer token")


def rpc_process(
    codex: str, env: dict[str, str], overrides: list[str] | None = None
) -> JsonRpcProcess:
    # `-c key=value` overrides apply to this process only and never touch the
    # config.toml in CODEX_HOME, so live mode can point the real, authenticated
    # home at the temporary MCP server without mutating the user's config.
    command = [codex, "app-server", "--stdio"]
    for override in overrides or []:
        command += ["-c", override]
    process = JsonRpcProcess(command, env)
    process.request(
        "initialize",
        {
            "clientInfo": {"name": "luciazero-agent-bus-spike", "version": "0"},
            "capabilities": {"experimentalApi": True},
        },
    )
    process.notify("initialized")
    return process


NO_ROLLOUT = "no rollout found"


def codex_protocol_probe(codex: str, temporary: Path) -> dict[str, Any]:
    """Offline App Server contract check under a disposable CODEX_HOME.

    Recorded null results (codex-cli 0.152.1, 2026-09-02):
    - an ``ephemeral`` thread never persists a rollout, so it can never resume;
    - a non-ephemeral thread persists its rollout on the first turn, not at
      ``thread/start``, so resume before any turn is rejected too.

    Resume is therefore only provable after an inference turn and lives in the
    live probe. Offline, this function proves ``thread/start`` works and that
    resume-before-turn fails with the distinct ``no rollout found`` error the
    dispatcher must classify as permanent rather than retryable.
    """
    codex_home = temporary / "codex-home"
    workspace = temporary / "workspace"
    codex_home.mkdir()
    workspace.mkdir()
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    with rpc_process(codex, env) as process:
        started = process.request(
            "thread/start",
            {"cwd": str(workspace), "sandbox": "read-only"},
        )
        thread = started.get("thread")
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise SpikeError("thread/start did not return a thread id")
        try:
            process.request("thread/resume", {"threadId": thread_id})
        except SpikeError as exc:
            if NO_ROLLOUT not in str(exc):
                raise
            resume_before_turn = f"rejected: {NO_ROLLOUT}"
        else:
            raise SpikeError(
                "thread/resume succeeded before any turn; the recorded null "
                "result no longer holds, re-examine the offline resume proof"
            )
    rollouts = sorted(str(path.relative_to(codex_home)) for path in codex_home.rglob("*.jsonl"))
    return {
        "thread_id": thread_id,
        "resume_before_turn": resume_before_turn,
        "rollout_files_after_start": rollouts,
        "resume_proof": "live-only",
    }


def codex_mcp_overrides(url: str) -> list[str]:
    return [
        f'mcp_servers.{SERVER_NAME}.url="{url}"',
        f'mcp_servers.{SERVER_NAME}.bearer_token_env_var="{TOKEN_ENV}"',
    ]


def codex_mcp_probe(codex: str, probe: McpProbe, temporary: Path) -> None:
    codex_home = temporary / "codex-mcp-home"
    codex_home.mkdir()
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env[TOKEN_ENV] = str(probe.token)
    run(
        [codex, "mcp", "add", SERVER_NAME, "--url", probe.url,
         "--bearer-token-env-var", TOKEN_ENV],
        env=env,
    )
    before = probe.event_count()
    with rpc_process(codex, env) as process:
        result = process.request("mcpServerStatus/list", {"detail": "full"})
        records = result.get("data")
        if not isinstance(records, list) or not any(
            isinstance(item, dict) and item.get("name") == SERVER_NAME
            for item in records
        ):
            raise SpikeError("Codex did not report the configured MCP server")
    methods = probe.methods_since(before)
    if "initialize" not in methods or "tools/list" not in methods:
        seen = sorted(probe.methods_since(before, authenticated=False))
        raise SpikeError(
            f"Codex MCP discovery incomplete with bearer token: {sorted(methods)}; "
            f"unauthenticated or partial: {seen}"
        )


def claude_mcp_probe(claude: str, probe: McpProbe, temporary: Path) -> None:
    claude_home = temporary / "claude-home"
    claude_home.mkdir()
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(claude_home)
    run(
        # --header is variadic and would swallow the positionals, so it goes last.
        [claude, "mcp", "add", "--scope", "user", "--transport", "http",
         SERVER_NAME, probe.url, "--header", f"Authorization: Bearer {probe.token}"],
        env=env,
    )
    before = probe.event_count()
    listed = run([claude, "mcp", "list"], env=env)
    if SERVER_NAME not in listed.stdout or "Connected" not in listed.stdout:
        raise SpikeError("Claude did not report the MCP server as connected")
    methods = probe.methods_since(before)
    if "initialize" not in methods:
        seen = sorted(probe.methods_since(before, authenticated=False))
        raise SpikeError(
            f"Claude MCP discovery incomplete with bearer token: {sorted(methods)}; "
            f"unauthenticated or partial: {seen}"
        )


def find_text(value: Any, token: str) -> bool:
    if isinstance(value, str):
        return token in value
    if isinstance(value, list):
        return any(find_text(item, token) for item in value)
    if isinstance(value, dict):
        return any(find_text(item, token) for item in value.values())
    return False


def items_of_type(messages: list[dict[str, Any]], kinds: set[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for message in messages:
        item = (message.get("params") or {}).get("item")
        if isinstance(item, dict) and item.get("type") in kinds:
            found.append(item)
    return found


def live_diagnostics(
    process: JsonRpcProcess, probe: McpProbe, before: int, messages: list[dict[str, Any]]
) -> str:
    with probe._lock:
        events = [(e["method"], e["auth_ok"], e["token"]) for e in probe.events[before:]]
    server_requests = sorted({str(r.get("method")) for r in process.requests})
    items = items_of_type(messages, {"mcpToolCall", "agentMessage"})
    return json.dumps(
        {
            "probe_events": events,
            "server_requests": server_requests,
            "notification_methods": sorted({str(m.get("method")) for m in messages}),
            "items": items,
        },
        default=str,
    )[:4000]


def tool_prompt(token: str) -> str:
    return (
        f'Call the MCP tool "spike_echo" on server "{SERVER_NAME}" with the '
        f'argument token="{token}", then reply with exactly the text the tool '
        "returned and nothing else."
    )


def codex_live_probe(codex: str, root: Path, probe: McpProbe) -> dict[str, str]:
    """Two real turns on the developer's authenticated CODEX_HOME.

    Turn 1 (start) must make the model select and call the spike tool through
    the bearer-protected server; turn 2 (resume) must echo a fresh token.
    """
    env = os.environ.copy()
    env[TOKEN_ENV] = str(probe.token)
    call_token = f"lz-codex-tool-{uuid.uuid4()}"
    resume_token = f"lz-codex-resume-{uuid.uuid4()}"
    before = probe.event_count()
    with rpc_process(codex, env, codex_mcp_overrides(probe.url)) as process:
        # "never" makes Codex fail MCP tool calls outright (see
        # JsonRpcProcess._reply_to_server_request); "on-request" routes the
        # approval to this client, which is the dispatcher's real contract.
        started = process.request(
            "thread/start",
            {"cwd": str(root), "sandbox": "read-only", "approvalPolicy": "on-request"},
        )
        thread = started.get("thread")
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise SpikeError("live Codex thread/start did not return an id")
        for token, text in (
            (call_token, tool_prompt(call_token)),
            (resume_token, f"Reply with exactly: {resume_token}"),
        ):
            if token == resume_token:
                process.request("thread/resume", {"threadId": thread_id})
            process.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": text}],
                    "clientUserMessageId": token,
                },
                timeout=60,
            )
            messages = process.collect_until("turn/completed", timeout=180)
            # Only the agent's own messages count; the user prompt is echoed
            # back as a userMessage item and would make find_text vacuous.
            agent_items = items_of_type(messages, {"agentMessage"})
            if not find_text(agent_items, token):
                raise SpikeError(
                    f"Codex turn did not return correlation token {token}; "
                    + live_diagnostics(process, probe, before, messages)
                )
            if token == call_token and call_token not in probe.tool_call_tokens(before):
                raise SpikeError(
                    "Codex model did not call spike_echo through the bearer-protected server; "
                    + live_diagnostics(process, probe, before, messages)
                )
        approvals = sorted({str(r.get("method")) for r in process.requests})
    return {"tool_call": call_token, "resume": resume_token,
            "approval_requests_answered": ",".join(approvals) or "none"}


def claude_result_text(result: subprocess.CompletedProcess[str]) -> str:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout
    if isinstance(payload, dict):
        value = payload.get("result")
        if isinstance(value, str):
            return value
    return result.stdout


def claude_live_probe(claude: str, root: Path, probe: McpProbe) -> dict[str, str]:
    """Two real turns on the developer's authenticated Claude login.

    ``--mcp-config`` plus ``--strict-mcp-config`` scope the temporary server to
    this invocation without writing the user's MCP configuration. Turn 1
    (start) must call the spike tool; turn 2 (resume) must echo a fresh token.
    """
    session_id = str(uuid.uuid4())
    call_token = f"lz-claude-tool-{uuid.uuid4()}"
    resume_token = f"lz-claude-resume-{uuid.uuid4()}"
    tool_name = f"mcp__{SERVER_NAME}__spike_echo"
    mcp_config = json.dumps(
        {
            "mcpServers": {
                SERVER_NAME: {
                    "type": "http",
                    "url": probe.url,
                    "headers": {"Authorization": f"Bearer {probe.token}"},
                }
            }
        }
    )
    common = [
        claude,
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--mcp-config",
        mcp_config,
        "--strict-mcp-config",
        "--allowedTools",
        tool_name,
    ]
    before = probe.event_count()
    first = run(
        common + ["--session-id", session_id, tool_prompt(call_token)],
        cwd=root,
        timeout=180,
    )
    if call_token not in claude_result_text(first):
        raise SpikeError("Claude start turn did not return the tool's correlation token")
    if call_token not in probe.tool_call_tokens(before):
        raise SpikeError("Claude model did not call spike_echo through the bearer-protected server")
    resumed = run(
        common + ["--resume", session_id, f"Reply with exactly: {resume_token}"],
        cwd=root,
        timeout=180,
    )
    if resume_token not in claude_result_text(resumed):
        raise SpikeError("Claude resumed turn did not return its correlation token")
    return {"tool_call": call_token, "resume": resume_token}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--only", choices=["codex", "claude"], default=None,
                        help="live mode: exercise one provider only (saves quota while debugging)")
    args = parser.parse_args()
    root = args.root.resolve()
    codex = shutil.which("codex")
    claude = shutil.which("claude")
    missing = [name for name, path in (("codex", codex), ("claude", claude)) if path is None]
    if missing:
        # A gate that cannot run is not green. Exit non-zero with a distinct
        # code and reason so callers can tell "skipped" from "failed".
        print(f"skip: required CLI not found: {', '.join(missing)}", file=sys.stderr)
        return SKIP_EXIT

    report: dict[str, Any] = {
        "codex_version": command_version("codex"),
        "claude_version": command_version("claude"),
        "mode": "live" if args.live else "offline",
    }
    with tempfile.TemporaryDirectory(prefix="luciazero-agent-bus-m0-") as path:
        temporary = Path(path)
        report["codex_app_server"] = codex_protocol_probe(codex, temporary)
        with McpProbe(token=f"lz-spike-{uuid.uuid4().hex}") as probe:
            negative_control(probe)
            codex_mcp_probe(codex, probe, temporary)
            claude_mcp_probe(claude, probe, temporary)
            report["mcp_auth"] = "bearer-required; unauthenticated requests answered 401"
            report["mcp_methods"] = sorted(
                {str(event["method"]) for event in probe.events if event.get("method")}
            )
            report["mcp_clients"] = sorted(
                {
                    str(event["client"] or event["user_agent"] or "unknown")
                    for event in probe.events
                    if event.get("method") == "initialize" and event["auth_ok"]
                }
            )
            report["mcp_unauthenticated_requests"] = sum(
                1 for event in probe.events if not event["auth_ok"]
            )
            report["mcp_negative_control"] = "token-less initialize answered 401"
            if args.live:
                if args.only in (None, "codex"):
                    report["codex_tokens"] = codex_live_probe(codex, root, probe)
                if args.only in (None, "claude"):
                    report["claude_tokens"] = claude_live_probe(claude, root, probe)

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.live:
        print("PASS  agent bus M0 live provider round trips")
    else:
        print("PASS  agent bus M0 offline protocol spike")
        print("note  proves thread/start and bearer-authenticated MCP discovery only")
        print("note  resume and model tool use need a turn; use --live after approving provider quota")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SpikeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)

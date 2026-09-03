"""M2 protocol-conformance suite for the shipped daemon: version negotiation,
session handling, error shapes, notifications, Streamable HTTP details, auth
and bind policy, and every tool through the full pull-beta flow."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from luciazero_agentd import Store
from luciazero_agentd.server import HANDLER_TIMEOUT_SECONDS, MAX_BODY_BYTES, MAX_SESSIONS, PROTOCOL_VERSIONS, TOOLS, BusServer, tool_contract
from luciazero_agentd.statedir import read_endpoint
from tests.fixtures import make_repo

TOKEN = "test-token-0123456789abcdef"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class Http:
    def __init__(self, url: str, token: Optional[str] = TOKEN) -> None:
        self.url = url
        self.token = token
        self.session: Optional[str] = None
        self.counter = 0

    def raw(self, body: bytes, *, method: str = "POST", headers: Optional[dict[str, str]] = None, path: str = "/mcp") -> tuple[int, dict[str, str], bytes]:
        base = self.url[: -len("/mcp")]
        hdrs = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.token is not None:
            hdrs["Authorization"] = f"Bearer {self.token}"
        if self.session:
            hdrs["Mcp-Session-Id"] = self.session
        hdrs.update(headers or {})
        request = urllib.request.Request(base + path, data=body if method in ("POST",) else None, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()

    def rpc(self, method: str, params: Optional[dict[str, Any]] = None, *, rpc_id: Any = "auto", headers: Optional[dict[str, str]] = None) -> tuple[int, dict[str, str], Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if rpc_id == "auto":
            self.counter += 1
            payload["id"] = self.counter
        elif rpc_id is not None:
            payload["id"] = rpc_id
        status, hdrs, body = self.raw(json.dumps(payload).encode("utf-8"), headers=headers)
        return status, hdrs, (json.loads(body) if body else None)

    def initialize(self, version: str = PROTOCOL_VERSIONS[0]) -> dict[str, Any]:
        status, hdrs, body = self.rpc("initialize", {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "conformance", "version": "0"}})
        assert status == 200, (status, body)
        self.session = hdrs.get("mcp-session-id")
        self.rpc("notifications/initialized", rpc_id=None)
        return body["result"]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        status, _, body = self.rpc("tools/call", {"name": name, "arguments": arguments})
        assert status == 200, (status, body)
        return body["result"] if "result" in body else body


class ServerCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-mcp-")
        self.db = str(Path(self._tmp.name) / "bus.sqlite3")
        with Store.open(self.db) as store:
            store.migrate()
        self.server = BusServer(self.db, TOKEN, port=0).start()
        self.client = Http(self.server.url)

    def tearDown(self) -> None:
        self.server.stop()
        self._tmp.cleanup()


class NegotiationAndSessions(ServerCase):
    def test_initialize_negotiates_each_supported_version(self) -> None:
        for version in PROTOCOL_VERSIONS:
            client = Http(self.server.url)
            result = client.initialize(version)
            self.assertEqual(result["protocolVersion"], version)
            self.assertEqual(result["serverInfo"]["name"], "luciazero-agentd")
            self.assertIn("tools", result["capabilities"])
            self.assertTrue(client.session)

    def test_unsupported_version_falls_back_to_latest(self) -> None:
        result = Http(self.server.url).initialize("1999-01-01")
        self.assertEqual(result["protocolVersion"], PROTOCOL_VERSIONS[0])

    def test_initialize_requires_protocol_version(self) -> None:
        status, _, body = self.client.rpc("initialize", {"capabilities": {}})
        self.assertEqual(status, 200)
        self.assertEqual(body["error"]["code"], -32602)

    def test_requests_without_session_are_400_and_unknown_session_404(self) -> None:
        status, _, body = self.client.rpc("ping", {})
        self.assertEqual((status, body["error"]["code"]), (400, -32600))
        self.client.session = "nope"
        status, _, body = self.client.rpc("ping", {})
        self.assertEqual((status, body["error"]["code"]), (404, -32600))

    def test_delete_ends_session(self) -> None:
        self.client.initialize()
        status, _, _ = self.client.raw(b"", method="DELETE")
        self.assertEqual(status, 200)
        status, _, _ = self.client.raw(b"", method="DELETE")
        self.assertEqual(status, 404)
        status, _, body = self.client.rpc("ping", {})
        self.assertEqual(status, 404)

    def test_notifications_are_202_without_body(self) -> None:
        self.client.initialize()
        status, _, body = self.client.rpc("notifications/initialized", rpc_id=None)
        self.assertEqual((status, body), (202, None))
        status, _, body = self.client.rpc("notifications/whatever", rpc_id=None)
        self.assertEqual((status, body), (202, None))

    def test_notification_with_missing_or_unknown_session(self) -> None:
        status, _, body = self.client.rpc("notifications/initialized", rpc_id=None)
        self.assertEqual(status, 400)
        self.client.session = "nope"
        status, _, body = self.client.rpc("notifications/initialized", rpc_id=None)
        self.assertEqual(status, 404)

    def test_unsupported_declared_protocol_version_header_is_400(self) -> None:
        self.client.initialize()
        status, _, _ = self.client.rpc("ping", {}, headers={"MCP-Protocol-Version": "1999-01-01"})
        self.assertEqual(status, 400)
        status, _, _ = self.client.rpc("ping", {}, headers={"MCP-Protocol-Version": PROTOCOL_VERSIONS[0]})
        self.assertEqual(status, 200)

    def test_session_table_is_bounded(self) -> None:
        for _ in range(MAX_SESSIONS + 20):
            Http(self.server.url).initialize()
        self.assertLessEqual(len(self.server.sessions), MAX_SESSIONS)
        self.assertGreaterEqual(len(self.server.seen), MAX_SESSIONS + 20)

    def test_get_mcp_is_405_no_stream_offered(self) -> None:
        status, hdrs, _ = self.client.raw(b"", method="GET")
        self.assertEqual(status, 405)
        self.assertIn("POST", hdrs.get("allow", ""))


class ErrorShapes(ServerCase):
    def test_parse_error(self) -> None:
        status, _, body = self.client.raw(b"{not json")
        self.assertEqual((status, body[:1]), (400, b"{"))
        self.assertEqual(json.loads(body)["error"]["code"], -32700)

    def test_batch_and_invalid_requests(self) -> None:
        status, _, body = self.client.raw(b"[]")
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32600))
        status, _, body = self.client.raw(json.dumps({"jsonrpc": "1.0", "method": "ping", "id": 1}).encode())
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32600))
        status, _, body = self.client.raw(json.dumps({"jsonrpc": "2.0", "method": "ping", "id": 1.5}).encode())
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32600))
        status, _, body = self.client.raw(json.dumps({"jsonrpc": "2.0", "method": "ping", "id": 1, "params": [1]}).encode())
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32600))

    def test_method_not_found_and_unknown_tool(self) -> None:
        self.client.initialize()
        status, _, body = self.client.rpc("tools/nope", {})
        self.assertEqual((status, body["error"]["code"]), (200, -32601))
        status, _, body = self.client.rpc("tools/call", {"name": "nope", "arguments": {}})
        self.assertEqual((status, body["error"]["code"]), (200, -32602))

    def test_tool_argument_errors_are_tool_results_not_protocol_errors(self) -> None:
        self.client.initialize()
        result = self.client.call("agent_register", {"agent_id": "x", "provider": "gpt", "role": "r"})
        self.assertTrue(result["isError"])
        self.assertIn("provider", result["content"][0]["text"])
        result = self.client.call("agent_register", {"agent_id": "x", "provider": "codex", "role": "r", "extra": 1})
        self.assertTrue(result["isError"])
        self.assertIn("unknown keys", result["content"][0]["text"])
        result = self.client.call("message_inbox", {"agent_id": "x", "limit": True})
        self.assertTrue(result["isError"])
        result = self.client.call("task_claim", {"task_id": "tsk_missing", "agent_id": "x"})
        self.assertTrue(result["isError"])
        self.assertIn("NotFound", result["content"][0]["text"])

    def test_pathological_json_is_a_parse_error_not_a_dropped_connection(self) -> None:
        status, _, body = self.client.raw(("[" * 20000 + "]" * 20000).encode())
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, -32700))
        status, _, body = self.client.raw(('{"jsonrpc":"2.0","id":' + "9" * 5000 + ',"method":"ping"}').encode())
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], -32700)

    def test_early_errors_close_the_connection(self) -> None:
        # Review finding: an unread body on a keep-alive connection was parsed
        # as the next request. Every pre-body rejection now says Connection: close.
        for headers, expected in (
            ({"Authorization": "Bearer wrong-token-0123456789abcdef"}, 401),
            ({"Content-Type": "text/plain"}, 415),
            ({"Origin": "https://evil.example"}, 403),
        ):
            status, hdrs, _ = self.client.raw(b"{}", headers=headers)
            self.assertEqual(status, expected)
            self.assertEqual(hdrs.get("connection"), "close", headers)

    def test_handler_has_a_socket_timeout(self) -> None:
        self.assertEqual(HANDLER_TIMEOUT_SECONDS, 30)
        self.assertEqual(self.server._httpd.RequestHandlerClass.timeout, 30)

    def test_content_type_and_body_limits(self) -> None:
        status, _, _ = self.client.raw(b"{}", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _, _ = self.client.raw(b"x" * (MAX_BODY_BYTES + 1))
        self.assertEqual(status, 413)


class AuthAndBind(ServerCase):
    def test_missing_or_wrong_token_is_401(self) -> None:
        for token in (None, "wrong-token-0123456789abcdef"):
            status, hdrs, _ = Http(self.server.url, token).rpc("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0]})
            self.assertEqual(status, 401)
            self.assertEqual(hdrs.get("www-authenticate"), "Bearer")
        status, _, _ = Http(self.server.url, None).raw(b"", method="GET", path="/status")
        self.assertEqual(status, 401)

    def test_foreign_origin_is_403(self) -> None:
        status, _, _ = self.client.rpc("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0]}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.client.rpc("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0]}, headers={"Origin": "http://localhost:3000"})
        self.assertEqual(status, 200)

    def test_foreign_host_header_is_403(self) -> None:
        status, _, _ = self.client.rpc("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0]}, headers={"Host": "bus.example.com"})
        self.assertEqual(status, 403)

    def test_missing_host_header_is_400(self) -> None:
        host, port = self.server._httpd.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=5)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSIONS[0]}})
        conn.putrequest("POST", "/mcp", skip_host=True)
        conn.putheader("Authorization", f"Bearer {TOKEN}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body.encode())
        response = conn.getresponse()
        self.assertEqual(response.status, 400)
        conn.close()

    def test_non_ascii_bearer_is_401_not_a_crash(self) -> None:
        host, port = self.server._httpd.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.putrequest("POST", "/mcp")
        conn.putheader("Authorization", "Bearer caf\xc3\xa9".encode("latin-1"))
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "2")
        conn.endheaders(b"{}")
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()

    def test_non_loopback_bind_is_refused_without_allow_remote_and_token_is_required(self) -> None:
        with self.assertRaises(ValueError):
            BusServer(self.db, TOKEN, host="0.0.0.0", port=0)
        with self.assertRaises(ValueError):
            BusServer(self.db, "short", port=0)

    def test_unknown_paths_404(self) -> None:
        status, _, _ = self.client.raw(b"{}", path="/other")
        self.assertEqual(status, 404)
        status, _, _ = self.client.raw(b"", method="GET", path="/other")
        self.assertEqual(status, 404)


class ToolsContract(ServerCase):
    def test_tools_list_matches_contract_and_schemas_are_closed(self) -> None:
        self.client.initialize()
        status, _, body = self.client.rpc("tools/list", {})
        self.assertEqual(status, 200)
        listed = body["result"]["tools"]
        self.assertEqual([t["name"] for t in listed], [t["name"] for t in TOOLS])
        self.assertEqual(listed, tool_contract())
        for tool in listed:
            self.assertNotIn("handler", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertIn("readOnlyHint", tool["annotations"])
        names = {t["name"] for t in listed}
        expected = {"agent_register", "agent_list", "agent_heartbeat", "message_send", "message_inbox", "message_ack",
                    "task_create", "task_list", "task_claim", "task_complete", "artifact_publish", "artifact_get",
                    "worktree_bind", "worktree_get", "approval_consume"}
        self.assertEqual(names, expected)

    def test_full_pull_beta_flow_through_tools(self) -> None:
        c = self.client
        c.initialize()
        c.call("agent_register", {"agent_id": "codex-architect", "provider": "codex", "role": "architect"})
        c.call("agent_register", {"agent_id": "claude-reviewer", "provider": "claude", "role": "reviewer", "capabilities": ["review"]})
        agents = c.call("agent_list", {})["structuredContent"]["agents"]
        self.assertEqual([a["id"] for a in agents], ["claude-reviewer", "codex-architect"])

        task = c.call("task_create", {"title": "review src/x.py", "created_by": "codex-architect", "payload": {"paths": ["src/x.py"]}, "idempotency_key": "t1"})["structuredContent"]
        again = c.call("task_create", {"title": "review src/x.py", "created_by": "codex-architect", "payload": {"paths": ["src/x.py"]}, "idempotency_key": "t1"})["structuredContent"]
        self.assertEqual(task["id"], again["id"])
        sent = c.call("message_send", {"sender": "codex-architect", "recipient": "claude-reviewer", "kind": "task", "payload": {"task_id": task["id"]}, "idempotency_key": "m1"})["structuredContent"]
        self.assertEqual(sent["kind"], "task")

        inbox = c.call("message_inbox", {"agent_id": "claude-reviewer"})["structuredContent"]
        self.assertEqual(len(inbox["items"]), 1)
        item = inbox["items"][0]
        self.assertEqual(item["payload"], {"task_id": task["id"]})
        acked = c.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": "claude-reviewer"})["structuredContent"]
        self.assertEqual(acked["state"], "acknowledged")
        conflict = c.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": "codex-architect", "outcome": "completed"})
        self.assertTrue(conflict["isError"])
        self.assertIn("ConflictError", conflict["content"][0]["text"])

        claimed = c.call("task_claim", {"task_id": task["id"], "agent_id": "claude-reviewer"})["structuredContent"]
        self.assertEqual(claimed["state"], "claimed")
        lost = c.call("task_claim", {"task_id": task["id"], "agent_id": "codex-architect"})
        self.assertTrue(lost["isError"])
        unbound = c.call("artifact_publish", {"kind": "report", "ref": "reports/x.md", "produced_by": "claude-reviewer", "task_id": task["id"]})
        self.assertTrue(unbound["isError"])  # M3: publishing needs a bound worktree
        repo = make_repo(Path(self._tmp.name) / "repo")
        bound = c.call("worktree_bind", {"agent_id": "claude-reviewer", "path": repo})["structuredContent"]
        self.assertEqual((bound["path"], bound["branch"], bound["dirty"]), (repo, "main", False))
        self.assertEqual(c.call("worktree_get", {"agent_id": "claude-reviewer"})["structuredContent"]["path"], repo)
        art = c.call("artifact_publish", {"kind": "report", "ref": "reports/x.md", "produced_by": "claude-reviewer", "task_id": task["id"]})["structuredContent"]
        self.assertRegex(art["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(c.call("artifact_get", {"artifact_id": art["id"]})["structuredContent"]["ref"], "reports/x.md")
        done = c.call("task_complete", {"task_id": task["id"], "agent_id": "claude-reviewer", "result": {"artifact": art["id"]}, "outcome": "completed"})["structuredContent"]
        self.assertEqual(done["state"], "completed")
        reply = c.call("message_send", {"sender": "claude-reviewer", "recipient": "codex-architect", "kind": "result", "payload": {"artifact": art["id"]}, "reply_to": sent["id"], "correlation_id": sent["correlation_id"]})["structuredContent"]
        self.assertEqual(reply["correlation_id"], sent["correlation_id"])
        completed = c.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": "claude-reviewer", "outcome": "completed"})["structuredContent"]
        self.assertEqual(completed["state"], "completed")
        listing = c.call("task_list", {"state": "completed"})["structuredContent"]
        self.assertEqual([t["id"] for t in listing["items"]], [task["id"]])
        self.assertEqual(c.call("agent_heartbeat", {"agent_id": "claude-reviewer"})["structuredContent"]["id"], "claude-reviewer")

        status, _, body = self.client.raw(b"", method="GET", path="/status")
        self.assertEqual(status, 200)
        summary = json.loads(body)
        self.assertEqual(summary["queued_deliveries"], 1)  # the reply to codex-architect
        self.assertEqual(summary["tasks"]["completed"], 1)

    def test_every_tool_result_carries_text_and_structured_content(self) -> None:
        self.client.initialize()
        result = self.client.call("agent_list", {})
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        self.assertFalse(result["isError"])

    def test_client_connection_resets_are_not_tracebacks(self) -> None:
        # Live gate: the Codex MCP client resets keep-alive connections and
        # socketserver printed a traceback per reset.
        import contextlib
        import io

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            try:
                raise ConnectionResetError(54, "Connection reset by peer")
            except ConnectionResetError:
                self.server._httpd.handle_error(None, ("127.0.0.1", 1))
            try:
                raise RuntimeError("real bug")
            except RuntimeError:
                self.server._httpd.handle_error(None, ("127.0.0.1", 1))
        self.assertNotIn("ConnectionResetError", stderr.getvalue())
        self.assertIn("RuntimeError", stderr.getvalue())  # genuine failures still surface


class DaemonCli(unittest.TestCase):
    def test_serve_status_and_client_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentd-cli-") as tmp:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(PACKAGE_ROOT))
            proc = subprocess.Popen([sys.executable, "-m", "luciazero_agentd", "serve", "--state-dir", tmp, "--port", "0"], cwd=PACKAGE_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                endpoint = None
                for _ in range(100):
                    endpoint = read_endpoint(Path(tmp))
                    if endpoint:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(endpoint, "daemon did not write endpoint.json")
                self.assertTrue(endpoint["url"].startswith("http://127.0.0.1:"))
                self.assertEqual(oct(os.stat(tmp).st_mode & 0o777), "0o700")
                self.assertEqual(oct(os.stat(Path(tmp) / "token").st_mode & 0o777), "0o600")
                status = subprocess.run([sys.executable, "-m", "luciazero_agentd", "status", "--state-dir", tmp, "--json"], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertEqual(json.loads(status.stdout)["queued_deliveries"], 0)
                human = subprocess.run([sys.executable, "-m", "luciazero_agentd", "status", "--state-dir", tmp], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
                self.assertIn("queued deliveries: 0", human.stdout)
                config = subprocess.run([sys.executable, "-m", "luciazero_agentd", "client-config", "--state-dir", tmp], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
                self.assertIn("claude mcp add", config.stdout)
                self.assertIn("--bearer-token-env-var", config.stdout)
                self.assertIn(endpoint["url"], config.stdout)
                refused = subprocess.run([sys.executable, "-m", "luciazero_agentd", "serve", "--state-dir", tmp, "--host", "0.0.0.0", "--port", "0"], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(refused.returncode, 2)
                self.assertIn("--allow-remote", refused.stderr)
                # Review finding: a second daemon on the same state dir used to
                # overwrite endpoint.json and erase it on exit.
                second = subprocess.run([sys.executable, "-m", "luciazero_agentd", "serve", "--state-dir", tmp, "--port", "0"], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(second.returncode, 2)
                self.assertIn("already serves", second.stderr)
                self.assertEqual(read_endpoint(Path(tmp))["url"], endpoint["url"])
                # status honours no proxy: the token must never leave loopback.
                proxied = subprocess.run([sys.executable, "-m", "luciazero_agentd", "status", "--state-dir", tmp, "--json"], cwd=PACKAGE_ROOT, env=dict(env, http_proxy="http://127.0.0.1:1", HTTP_PROXY="http://127.0.0.1:1"), capture_output=True, text=True, timeout=30)
                self.assertEqual(proxied.returncode, 0, proxied.stderr)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                for pipe in (proc.stdout, proc.stderr):
                    if pipe is not None:
                        pipe.close()
            self.assertIsNone(read_endpoint(Path(tmp)), "endpoint.json must be cleared on shutdown")
            no_daemon = subprocess.run([sys.executable, "-m", "luciazero_agentd", "status", "--state-dir", tmp], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(no_daemon.returncode, 0)
            self.assertIn("no running daemon", no_daemon.stderr)

    def test_status_never_mints_a_token_and_client_config_quotes_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentd cli $x-") as tmp:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(PACKAGE_ROOT))
            (Path(tmp) / "endpoint.json").write_text(json.dumps({"url": "http://127.0.0.1:1/mcp", "pid": 1, "started_at": "x"}))
            missing = subprocess.run([sys.executable, "-m", "luciazero_agentd", "status", "--state-dir", tmp], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("token missing", missing.stderr)
            self.assertFalse((Path(tmp) / "token").exists(), "a read-only command must not create a secret")
            config = subprocess.run([sys.executable, "-m", "luciazero_agentd", "client-config", "--state-dir", tmp], cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(config.returncode, 0, config.stderr)
            self.assertIn("'" + str(Path(tmp) / "token") + "'", config.stdout)  # shlex-quoted because of the space and $


if __name__ == "__main__":
    unittest.main()

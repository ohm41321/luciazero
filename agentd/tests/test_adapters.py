"""M6 provider adapters: the command that is built, the credential that must
not outlive the turn, the process group that has to die with it, how a
provider's exit becomes a bus outcome, and what recovery cleans up.

Every fake CLI here is a Python script written by the test. No test in this
repository starts a real `codex` or `claude`: a suite that spends quota, or
touches the user's own provider state, is a suite nobody can run.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from luciazero_agentd.adapters import (
    SERVER_NAME,
    TOKEN_ENV,
    ClaudeAdapter,
    CodexAdapter,
    ProcessAdapter,
    TurnRequest,
    _CodexExecAdapter,
    adapter_for,
)
from luciazero_agentd.appserver import AppServer, AppServerError
from luciazero_agentd.runlog import RunLog

CREDENTIAL = "lzsc_" + "e" * 32
URL = "http://127.0.0.1:65535/mcp"


def script(path: Path, body: str) -> str:
    """An executable stand-in for a provider CLI."""
    path.write_text("#!" + sys.executable + "\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


class AdapterCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-adapters-")
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "turn"
        self.workspace.mkdir()
        self.log = RunLog(self.root / "run.log", literals=(CREDENTIAL,))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def request(self, command: tuple[str, ...], **kwargs: object) -> TurnRequest:
        base = TurnRequest(
            agent_id="claude-reviewer", provider="claude", command=command, cwd=str(self.root),
            prompt="do the turn", credential=CREDENTIAL, url=URL, timeout_seconds=30,
            log=self.log, workspace=self.workspace,
        )
        return replace(base, **kwargs)  # type: ignore[arg-type]

    def logged(self) -> str:
        return Path(self.log.close()).read_text(encoding="utf-8")


class CommandConstructionTests(AdapterCase):
    def test_claude_keeps_a_single_value_option_between_the_variadic_ones_and_the_prompt(self) -> None:
        """ADR 0001: `--allowedTools <tools...>` and `--mcp-config <configs...>`
        are variadic, and a prompt straight after either is swallowed."""
        argv = ClaudeAdapter().argv(self.request(("claude", "--model", "sonnet")), resuming=False)
        self.assertEqual(argv[:2], ["claude", "-p"])
        self.assertEqual(argv[-3:], ["--output-format", "json", "do the turn"])
        self.assertEqual(argv[argv.index("--mcp-config") + 2], "--strict-mcp-config")
        self.assertEqual(argv[argv.index("--allowedTools") + 2], "--permission-mode")
        self.assertIn("--model", argv)
        self.assertLess(argv.index("--model"), argv.index("--mcp-config"))

    def test_claude_resumes_by_session_id_only_when_it_has_one(self) -> None:
        request = self.request(("claude",), provider_session_id="sess-7")
        self.assertNotIn("--resume", ClaudeAdapter().argv(request, resuming=False))
        resumed = ClaudeAdapter().argv(request, resuming=True)
        self.assertEqual(resumed[resumed.index("--resume") + 1], "sess-7")
        self.assertNotIn("--resume", ClaudeAdapter().argv(self.request(("claude",)), resuming=True))

    def test_the_permission_mode_is_the_policy_the_user_chose(self) -> None:
        for policy, mode in (("deny", "default"), ("workspace", "acceptEdits"), ("accept", "bypassPermissions")):
            argv = ClaudeAdapter().argv(self.request(("claude",), approval_policy=policy), resuming=False)
            self.assertEqual(argv[argv.index("--permission-mode") + 1], mode)

    def test_codex_passes_the_bus_as_overrides_that_never_touch_the_users_config(self) -> None:
        argv = CodexAdapter().argv(self.request(("codex",), provider="codex"), resuming=False)
        self.assertEqual(argv[:3], ["codex", "app-server", "--stdio"])
        overrides = [argv[i + 1] for i, part in enumerate(argv) if part == "-c"]
        self.assertEqual(overrides, [f'mcp_servers.{SERVER_NAME}.url="{URL}"',
                                     f'mcp_servers.{SERVER_NAME}.bearer_token_env_var="{TOKEN_ENV}"'])

    def test_the_codex_exec_fallback_resumes_a_session_by_id(self) -> None:
        request = self.request(("codex", "exec", "--skip-git-repo-check"), provider="codex", provider_session_id="thr-9")
        start = _CodexExecAdapter().argv(request, resuming=False)
        self.assertEqual(start[:2], ["codex", "exec"])
        self.assertEqual(start[-1], "do the turn")
        self.assertIn("--skip-git-repo-check", start)
        resumed = _CodexExecAdapter().argv(request, resuming=True)
        self.assertEqual(resumed[1:4], ["exec", "resume", "thr-9"])
        self.assertEqual(resumed[-1], "do the turn")

    def test_a_worker_command_naming_exec_takes_the_fallback(self) -> None:
        self.assertTrue(CodexAdapter.uses_exec(self.request(("codex", "exec"), provider="codex")))
        self.assertFalse(CodexAdapter.uses_exec(self.request(("codex",), provider="codex")))

    def test_no_adapter_puts_the_credential_on_the_command_line(self) -> None:
        """argv is world-readable through `ps` for the life of a turn."""
        request = self.request(("claude",), provider_session_id="sess-1")
        codex = self.request(("codex",), provider="codex", provider_session_id="thr-1")
        exec_request = self.request(("codex", "exec"), provider="codex", provider_session_id="thr-1")
        every = (ClaudeAdapter().argv(request, resuming=True)
                 + CodexAdapter().argv(codex, resuming=True)
                 + _CodexExecAdapter().argv(exec_request, resuming=True))
        self.assertFalse([part for part in every if CREDENTIAL in part])

    def test_a_command_naming_our_own_flags_never_starts_a_provider(self) -> None:
        """Defence in depth. Enrolment refuses these, but a worker enrolled
        before that check existed must not run with its own permission flags
        either -- and the refusal is permanent, because the next attempt would
        build the same command."""
        marker = self.root / "started"
        fake = script(self.root / "fake-cli", f"open({str(marker)!r}, 'w').write('ran')\n")
        for provider, adapter, extra in (
            ("claude", ClaudeAdapter(), ["--dangerously-skip-permissions"]),
            ("claude", ClaudeAdapter(), ["--allowedTools", "Bash"]),
            ("codex", CodexAdapter(), ["-c", "sandbox_mode=danger-full-access"]),
            ("codex", _CodexExecAdapter(), ["exec", "--full-auto"]),
        ):
            result = adapter.start(self.request(tuple([fake, *extra]), provider=provider))
            self.assertFalse(result.ok)
            self.assertTrue(result.permanent)
            self.assertEqual(result.exit_state, "config_refused")
            self.assertFalse(marker.exists(), f"{provider} {extra} started a provider anyway")

    def test_the_registry_names_one_adapter_per_provider(self) -> None:
        self.assertIsInstance(adapter_for("claude"), ClaudeAdapter)
        self.assertIsInstance(adapter_for("codex"), CodexAdapter)
        self.assertIsInstance(adapter_for("other"), ProcessAdapter)
        with self.assertRaises(KeyError):
            adapter_for("gemini")


class CredentialCleanupTests(AdapterCase):
    """The Claude config file is the one place a credential touches disk."""

    def claude(self, body: str, **kwargs: object) -> tuple[ClaudeAdapter, TurnRequest]:
        fake = script(self.root / "claude-fake", body)
        return ClaudeAdapter(), self.request((fake,), **kwargs)

    def test_the_config_carries_the_credential_at_0600_while_the_turn_runs(self) -> None:
        adapter, request = self.claude(
            "import json, os, sys\n"
            "path = [a for a in sys.argv if a.endswith('mcp.json')][0]\n"
            "print(json.dumps({'mode': oct(os.stat(path).st_mode)[-3:], 'body': open(path).read()}))\n"
        )
        result = adapter.start(request)
        self.assertTrue(result.ok, result.error)
        reported = json.loads([line for line in self.logged().splitlines() if line.startswith("{")][-1])
        self.assertEqual(reported["mode"], "600")
        # The log is scrubbed, so the credential shows only as its shape.
        self.assertIn("[redacted]", reported["body"])

    def test_the_config_is_gone_however_the_turn_ends(self) -> None:
        for body, ok in (("print('done')\n", True),
                         ("raise SystemExit(2)\n", False),
                         ("import time; time.sleep(30)\n", False)):
            with self.subTest(body=body):
                self.log = RunLog(self.root / "run.log", literals=(CREDENTIAL,))
                adapter, request = self.claude(body)
                result = adapter.start(replace(request, timeout_seconds=1))
                self.assertEqual(result.ok, ok)
                self.assertFalse((self.workspace / "mcp.json").exists())

    def test_a_provider_that_cannot_start_leaves_no_config_behind(self) -> None:
        adapter = ClaudeAdapter()
        result = adapter.start(self.request(("luciazero-no-such-provider",)))
        self.assertTrue(result.permanent)
        self.assertEqual(result.exit_state, "spawn_failed")
        self.assertFalse((self.workspace / "mcp.json").exists())

    def test_the_credential_never_reaches_claude_through_the_environment(self) -> None:
        adapter, request = self.claude(
            "import os\nprint('token' if os.environ.get('LUCIAZERO_AGENT_BUS_TOKEN') else 'no token')\n"
        )
        adapter.start(request)
        self.assertIn("no token", self.logged())


class ProcessGroupTests(AdapterCase):
    def test_cancelling_a_turn_kills_the_children_the_provider_started(self) -> None:
        """Providers spawn their own children; signalling only the process we
        know about leaves those running with the turn's credential in hand."""
        marker = self.root / "grandchild.pid"
        fake = script(self.root / "provider", (
            "import os, subprocess, sys, time\n"
            f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
            "sys.stdout.flush()\n"
            "time.sleep(120)\n"
        ))
        adapter = ProcessAdapter()
        request = replace(self.request((fake,)), timeout_seconds=1)
        result = adapter.start(request)
        self.assertEqual(result.exit_state, "timeout")
        grandchild = int(marker.read_text())
        for _ in range(50):
            if not _alive(grandchild):
                break
            time.sleep(0.1)
        self.assertFalse(_alive(grandchild), "the provider's own child outlived the turn")


class ExitMappingTests(AdapterCase):
    def test_a_provider_exit_becomes_a_bus_outcome(self) -> None:
        cases = (
            ("print('fine')\n", True, "exit 0", False),
            ("raise SystemExit(1)\n", False, "exit 1", False),
            ("raise SystemExit(127)\n", False, "exit 127", False),
        )
        for body, ok, exit_state, permanent in cases:
            with self.subTest(exit_state=exit_state):
                self.log = RunLog(self.root / "run.log")
                fake = script(self.root / f"p{exit_state.replace(' ', '')}", body)
                result = ProcessAdapter().start(self.request((fake,)))
                self.assertEqual((result.ok, result.exit_state, result.permanent), (ok, exit_state, permanent))

    def test_a_timeout_is_retryable_and_a_missing_binary_is_not(self) -> None:
        fake = script(self.root / "slow", "import time; time.sleep(30)\n")
        timed_out = ProcessAdapter().start(replace(self.request((fake,)), timeout_seconds=1))
        self.assertEqual((timed_out.ok, timed_out.exit_state, timed_out.permanent), (False, "timeout", False))
        missing = ProcessAdapter().start(self.request(("luciazero-no-such-provider",)))
        self.assertEqual((missing.ok, missing.exit_state, missing.permanent), (False, "spawn_failed", True))

    def test_claude_records_the_session_the_turn_ran_in(self) -> None:
        fake = script(self.root / "claude-json", (
            "import json\n"
            "print(json.dumps({'type': 'result', 'session_id': 'sess-42', 'result': 'ok'}))\n"
        ))
        result = ClaudeAdapter().start(self.request((fake,)))
        self.assertTrue(result.ok)
        self.assertEqual(result.provider_session_id, "sess-42")

    def test_a_turn_that_prints_no_session_keeps_the_one_it_had(self) -> None:
        fake = script(self.root / "claude-quiet", "print('nothing structured here')\n")
        result = ClaudeAdapter().start(self.request((fake,), provider_session_id="sess-old"))
        self.assertEqual(result.provider_session_id, "sess-old")


APP_SERVER_FAKE = '''
import json, os, sys

# What this fake asks approval for, and what it was started with: the test
# writes the first and reads the second.
ASKED = json.load(open(sys.argv[0] + ".ask")) if os.path.exists(sys.argv[0] + ".ask") else {"command": ["rm", "-rf", "/"]}

def send(payload):
    sys.stdout.write(json.dumps(payload) + "\\n")
    sys.stdout.flush()

approvals = []
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"id": message["id"], "result": {"userAgent": "fake"}})
    elif method == "thread/start":
        open(sys.argv[0] + ".start", "w").write(json.dumps(message["params"]))
        send({"id": message["id"], "result": {"thread": {"id": "thr-fake"}}})
    elif method == "thread/resume":
        send({"id": message["id"], "result": {"thread": {"id": message["params"]["threadId"]}}})
    elif method == "turn/start":
        send({"id": message["id"], "result": {}})
        # Then ask for something the policy has to answer, and finish.
        send({"id": 9001, "method": "item/commandExecution/requestApproval", "params": ASKED})
    elif method is None and "id" in message:
        approvals.append(message.get("result"))
        send({"method": "turn/completed", "params": {"answers": approvals}})
    elif method == "initialized":
        pass
'''


class AppServerTests(AdapterCase):
    def codex(self, asks: dict | None = None, **kwargs: object) -> tuple[CodexAdapter, TurnRequest]:
        fake = script(self.root / "codex-fake", APP_SERVER_FAKE)
        if asks is not None:
            Path(fake + ".ask").write_text(json.dumps(asks), encoding="utf-8")
        return CodexAdapter(), self.request((fake,), provider="codex", **kwargs)

    def decision(self, policy: str, asks: dict | None = None) -> str:
        """What one policy answers one request, read off the run log."""
        self.log = RunLog(self.root / f"run-{policy}-{time.time_ns()}.log")
        adapter, request = self.codex(asks=asks, approval_policy=policy)
        result = adapter.start(request)
        self.assertTrue(result.ok, result.error)
        body = Path(self.log.close()).read_text(encoding="utf-8")
        self.assertIn(f"answered under policy {policy}", body)
        return "accept" if '"decision": "accept"' in body else "deny"

    def test_a_turn_starts_a_thread_and_records_it_for_the_next_one(self) -> None:
        adapter, request = self.codex()
        result = adapter.start(request)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.provider_session_id, "thr-fake")
        self.assertEqual(result.exit_state, "turn completed")

    def test_resuming_keeps_the_thread_it_was_given(self) -> None:
        adapter, request = self.codex(provider_session_id="thr-earlier")
        result = adapter.resume(request)
        self.assertEqual(result.provider_session_id, "thr-earlier")

    def test_an_approval_is_answered_by_the_policy_the_user_chose(self) -> None:
        inside = {"command": ["touch", "note"], "cwd": str(self.root)}
        for policy, decision in (("deny", "deny"), ("workspace", "accept"), ("accept", "accept")):
            with self.subTest(policy=policy):
                self.assertEqual(self.decision(policy, inside), decision)

    def test_workspace_is_narrower_than_accept_and_not_a_second_name_for_it(self) -> None:
        """Review finding: `workspace` and `accept` answered every execution
        approval identically, so the middle tier -- the one an operator chooses
        to mean "in its own worktree" -- granted whatever was asked. What
        separates them is leaving the sandbox and leaving the directory."""
        escalated = {"command": ["curl", "https://example.invalid"], "cwd": str(self.root),
                     "withEscalatedPermissions": True}
        outside = {"changes": {"/etc/hosts": {"kind": "edit"}}, "cwd": str(self.root)}
        upwards = {"command": ["sh", "-c", "true"], "cwd": str(self.root.parent)}
        confined = {"changes": {str(self.root / "src" / "app.py"): {"kind": "edit"}}, "cwd": str(self.root)}
        for asks in (escalated, outside, upwards):
            self.assertEqual(self.decision("workspace", asks), "deny", asks)
            self.assertEqual(self.decision("accept", asks), "accept", asks)
        self.assertEqual(self.decision("workspace", confined), "accept")

    def test_the_sandbox_the_thread_runs_in_is_the_policy_too(self) -> None:
        """A write inside the workspace needs no approval at all, so `deny`
        cannot be a promise the approval answer keeps on its own."""
        for policy, sandbox in (("deny", "read-only"), ("workspace", "workspace-write"), ("accept", "workspace-write")):
            with self.subTest(policy=policy):
                adapter, request = self.codex(approval_policy=policy)
                self.assertTrue(adapter.start(request).ok)
                started = json.loads(Path(request.command[0] + ".start").read_text(encoding="utf-8"))
                self.assertEqual(started["sandbox"], sandbox)
                self.assertEqual(started["approvalPolicy"], "on-request")

    def test_a_provider_that_cannot_start_is_a_permanent_failure(self) -> None:
        result = CodexAdapter().start(self.request(("luciazero-no-such-codex",), provider="codex"))
        self.assertEqual((result.ok, result.exit_state, result.permanent), (False, "spawn_failed", True))

    def test_a_child_that_dies_mid_protocol_is_retryable(self) -> None:
        fake = script(self.root / "codex-dies", "import sys; sys.exit(3)\n")
        result = CodexAdapter().start(self.request((fake,), provider="codex"))
        self.assertFalse(result.ok)
        self.assertFalse(result.permanent)
        self.assertIn(result.exit_state, ("app_server_error", "spawn_failed"))

    def test_the_app_server_child_dies_with_its_group(self) -> None:
        marker = self.root / "app-grandchild.pid"
        fake = script(self.root / "codex-spawns", (
            "import json, os, subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
            "for line in sys.stdin:\n"
            "    message = json.loads(line)\n"
            "    if message.get('method') == 'initialize':\n"
            "        sys.stdout.write(json.dumps({'id': message['id'], 'result': {}}) + '\\n')\n"
            "        sys.stdout.flush()\n"
            "    time.sleep(60)\n"
        ))
        adapter = CodexAdapter()
        result = adapter.start(replace(self.request((fake,), provider="codex"), timeout_seconds=1))
        self.assertFalse(result.ok)
        grandchild = int(marker.read_text())
        for _ in range(50):
            if not _alive(grandchild):
                break
            time.sleep(0.1)
        self.assertFalse(_alive(grandchild), "the app-server's own child outlived the turn")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    unittest.main()

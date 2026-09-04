"""M7c: how an ordinary `claude` or `codex` session gets an identity.

An MCP client sends its headers once, at connect time, so a session that
opened with the shared token can never present a credential afterwards --
which is why binding a terminal used to mean starting the provider through
`run`. The claim is the way out, and the only reason it is safe is that it
takes two phases in two places:

* the session **asks** (`agent_claim_begin`) and is pinned to the request
  before the request id exists, so the id is a reference and not a bearer
  token: approving it binds the session that asked, never the one that
  presents the id;
* a **person decides**, from a different terminal. Both CLIs can run shell
  commands, so a session able to approve its own request would prove nothing
  at all: the model would be choosing its own identity, and a prompt
  injection would be choosing it for them.

What these tests defend is that pair of properties, plus the ordinary
lifetime rules -- expiry, single use, and an identity that dies with its
binding.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import json
import os
import tempfile
import time
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from luciazero_agentd import approval, procinfo
from luciazero_agentd.__main__ import main
from luciazero_agentd.server import BusServer, session_key
from luciazero_agentd.store import ConflictError, NotFound, Store, ValidationError, utcnow

from tests.test_mcp import TOKEN, Http

ARCHITECT, REVIEWER = "codex-architect", "claude-reviewer"


class ClaimCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-claim-")
        self.state_dir = Path(self._tmp.name)
        self.db = str(self.state_dir / "bus.sqlite3")
        self.store = Store.open(self.db)
        self.store.migrate()
        self.store.trust = "human"
        self.store.register_agent(ARCHITECT, provider="codex", role="architect")
        self.store.register_agent(REVIEWER, provider="claude", role="reviewer")
        self.codes: dict[str, str] = {}

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def key(self, session: str = "session-one") -> str:
        return hashlib.sha256(session.encode("utf-8")).hexdigest()

    def ask(self, agent: str = REVIEWER, session: str = "session-one", **kwargs: Any) -> dict[str, Any]:
        request, code = self.store.open_claim(agent, session_hash=self.key(session), provider="claude", **kwargs)
        self.codes[str(request["id"])] = code
        return request

    def approve(self, request_id: str, **kwargs: Any) -> dict[str, Any]:
        options: dict[str, Any] = {"by": "human:test", "tty": "ttys900", "pid": os.getpid(),
                                   "code": self.codes.get(request_id)}
        options.update(kwargs)
        return self.store.decide_claim(request_id, approve=True, **options)


class AskingTests(ClaimCase):
    def test_asking_grants_nothing_on_its_own(self) -> None:
        request = self.ask()
        self.assertEqual(request["state"], "open")
        self.assertIsNone(request["binding_id"])
        self.assertIsNone(self.store.claim_binding(self.key()),
                          "an unanswered request must not name an identity")

    def test_the_session_id_never_comes_back_out(self) -> None:
        """The request is read by a person; handing its reader the key to that
        session would undo the whole point of pinning it."""
        request = self.ask()
        listed = self.store.list_claims()
        for record in (request, self.store.get_claim(request["id"]), listed[0]):
            self.assertNotIn("session_hash", record)
            self.assertEqual(len(record["session_fingerprint"]), 12)
            self.assertNotIn(self.key(), json.dumps(record))

    def test_an_agent_that_is_already_bound_cannot_be_asked_for(self) -> None:
        self.store.bind_terminal(REVIEWER, provider="claude", by="human:test", tty="ttys001", pid=os.getpid())
        with self.assertRaises(ConflictError):
            self.ask()

    def test_a_second_ask_supersedes_the_first(self) -> None:
        """One request in flight per session, or a person could be shown two
        ids and approve the one that binds the other agent."""
        first = self.ask(REVIEWER)
        second = self.ask(ARCHITECT)
        self.assertEqual(self.store.get_claim(first["id"])["state"], "superseded")
        self.assertEqual([r["id"] for r in self.store.list_claims()], [second["id"]])
        with self.assertRaises(ConflictError):
            self.approve(first["id"])

    def test_an_agent_nobody_put_on_the_roster_cannot_be_claimed(self) -> None:
        """The model proposes an identity; it cannot invent one."""
        with self.assertRaises(NotFound):
            self.store.open_claim("nobody-added-this", session_hash=self.key(), provider="claude")


class DecidingTests(ClaimCase):
    def test_approval_binds_the_session_that_asked_to_the_agent_it_asked_for(self) -> None:
        request = self.ask()
        decided = self.approve(request["id"])
        self.assertEqual(decided["state"], "approved")
        binding = self.store.claim_binding(self.key())
        self.assertIsNotNone(binding)
        self.assertEqual(binding["agent_id"], REVIEWER)
        self.assertEqual(binding["ownership"], "human")
        self.assertIsNone(self.store.claim_binding(self.key("another-session")),
                          "the identity belongs to the session that asked, not to anyone holding the id")

    def test_denial_leaves_the_session_exactly_as_it_was(self) -> None:
        request = self.ask()
        decided = self.store.decide_claim(request["id"], approve=False, by="human:test")
        self.assertEqual(decided["state"], "denied")
        self.assertIsNone(decided["binding_id"])
        self.assertIsNone(self.store.claim_binding(self.key()))

    def test_a_decision_is_made_once(self) -> None:
        request = self.ask()
        self.approve(request["id"])
        with self.assertRaises(ConflictError):
            self.approve(request["id"])
        with self.assertRaises(ConflictError):
            self.store.decide_claim(request["id"], approve=False, by="human:test")

    def test_an_expired_request_cannot_be_approved_and_says_so(self) -> None:
        request = self.ask(ttl_seconds=30)
        gone = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="microseconds")
        self.store._conn.execute("UPDATE claim_requests SET expires_at = ? WHERE id = ?", (gone, request["id"]))
        self.store._conn.commit()
        self.assertEqual(self.store.get_claim(request["id"])["state"], "expired",
                         "a request past its deadline reads as expired before anybody acts on it")
        with self.assertRaises(ConflictError):
            self.approve(request["id"])
        self.assertIsNone(self.store.claim_binding(self.key()))

    def test_the_identity_dies_with_its_binding(self) -> None:
        """Approving is not a permanent grant: it is a binding, and detaching
        or expiring one takes the identity away at once."""
        request = self.ask()
        decided = self.approve(request["id"])
        self.store.revoke_binding(str(decided["binding_id"]), by="human:test", reason="detached")
        self.assertIsNone(self.store.claim_binding(self.key()))

    def test_who_decided_is_recorded(self) -> None:
        request = self.ask()
        self.approve(request["id"], by="human:tester", tty="ttys777", pid=4321)
        record = self.store.get_claim(request["id"])
        self.assertEqual((record["decided_by"], record["decided_tty"], record["decided_pid"]),
                         ("human:tester", "ttys777", 4321))
        kinds = [e for e in self.store.events(limit=200) if e["entity_id"] == request["id"]]
        self.assertEqual([e["kind"] for e in kinds], ["claim.opened", "claim.approved"])
        self.assertEqual(kinds[-1]["payload"]["tty"], "ttys777")


class TheCodeIsTheBoundaryTests(ClaimCase):
    """What the second phase actually rests on.

    Not process ancestry: both CLIs can run shell commands, and one
    `( cmd & )` orphans the process so no ancestry check can see where it came
    from, while `script` supplies a pty that satisfies any isatty gate. The
    code is printed on the daemon's own console and nowhere else, which is the
    one thing a process on this machine cannot read without being that
    process.
    """

    def test_the_right_code_is_required(self) -> None:
        request = self.ask()
        with self.assertRaises(ValidationError):
            self.approve(request["id"], code="00000000")
        self.assertEqual(self.store.get_claim(request["id"])["state"], "open")
        self.assertIsNone(self.store.claim_binding(self.key()))
        self.approve(request["id"])
        self.assertIsNotNone(self.store.claim_binding(self.key()))

    def test_no_code_at_all_is_not_a_shortcut(self) -> None:
        request = self.ask()
        for missing in (None, "", "   "):
            with self.assertRaises(ValidationError):
                self.approve(request["id"], code=missing)

    def test_guessing_kills_the_request(self) -> None:
        """8 hex characters is only out of reach if a shell loop cannot keep
        trying."""
        request = self.ask()
        for _ in range(5):
            with self.assertRaises(ValidationError):
                self.approve(request["id"], code="deadbeef")
        self.assertEqual(self.store.get_claim(request["id"])["state"], "denied")
        with self.assertRaises(ConflictError):
            self.approve(request["id"])

    def test_the_code_is_not_in_the_store_in_the_clear(self) -> None:
        request = self.ask()
        code = self.codes[request["id"]]
        dump = "".join(str(r) for r in self.store._conn.execute("SELECT * FROM claim_requests").fetchall())
        self.assertNotIn(code, dump)
        for record in (self.store.get_claim(request["id"]), self.store.list_claims()[0]):
            self.assertNotIn("code_hash", record)
            self.assertNotIn(code, json.dumps(record))

    def test_denying_needs_no_code(self) -> None:
        """A person who cannot find the code must still be able to say no."""
        request = self.ask()
        decided = self.store.decide_claim(request["id"], approve=False, by="human:test")
        self.assertEqual(decided["state"], "denied")


class NoTakeoverTests(ClaimCase):
    def test_a_claim_cannot_take_an_identity_bound_after_it_was_asked_for(self) -> None:
        """The window between asking and approving is five minutes long. A
        request made while the agent was free must not, later, revoke the
        terminal the user has since started."""
        request = self.ask()
        binding, credential = self.store.bind_terminal(REVIEWER, provider="claude", by="human:test",
                                                       tty="ttys001", pid=os.getpid())
        with self.assertRaises(ConflictError):
            self.approve(request["id"])
        self.assertEqual(self.store.get_binding(str(binding["id"]))["state"], "active")
        self.assertIsNotNone(self.store.resolve_credential(credential),
                             "the user's own session must still work")
        self.assertIsNone(self.store.claim_binding(self.key()))

    def test_two_requests_for_one_agent_cannot_both_be_approved(self) -> None:
        first = self.ask(REVIEWER, session="session-one")
        second = self.ask(REVIEWER, session="session-two")
        self.approve(first["id"])
        with self.assertRaises(ConflictError):
            self.approve(second["id"])
        self.assertIsNotNone(self.store.claim_binding(self.key("session-one")))
        self.assertIsNone(self.store.claim_binding(self.key("session-two")))


class ThroughTheDaemonTests(ClaimCase):
    """The property that matters end to end: the session that asked becomes
    verified, in place, without reconnecting -- and nothing else does."""

    def setUp(self) -> None:
        super().setUp()
        # The shipped default: an unverified session may not act. The claim is
        # how a session started as plain `claude` stops being unverified.
        # Console mode: this class is about the claim itself, and the
        # on-screen route has its own tests with an injected runner.
        self.server = BusServer(self.db, TOKEN, port=0, allow_unattributed=False,
                                approve_with="console").start()
        self.addCleanup(self.server.stop)
        self.client = Http(self.server.url)
        self.client.initialize()

    def ask(self, agent: str = REVIEWER) -> tuple[dict[str, Any], str]:
        """Phase one through the real daemon, and the code it printed.

        The capture is the assertion: the code must reach the daemon's own
        console and must not be in the answer the session gets back.
        """
        console = io.StringIO()
        with redirect_stdout(console):
            asked = self.content(self.client.call("agent_claim_begin", {"agent_id": agent}))
        printed = console.getvalue()
        match = re.search(r"--code ([0-9a-f]{8})", printed)
        self.assertIsNotNone(match, f"the daemon must print the code on its own console: {printed!r}")
        code = match.group(1)
        self.assertNotIn(code, json.dumps(asked), "the code must never come back through MCP")
        self.assertIn(asked["claim_id"], printed)
        return asked, code

    def human_decides(self, claim_id: str, code: Optional[str], *, approve: bool = True) -> dict[str, Any]:
        """The other terminal: a different process, holding the same store."""
        with Store.open(self.db) as human:
            human.migrate()
            human.trust = "human"
            return human.decide_claim(claim_id, approve=approve, by="human:test", code=code)

    def content(self, result: dict[str, Any]) -> dict[str, Any]:
        """Success carries structuredContent; a refusal is JSON in the text
        block with isError, and both are answers this suite reads."""
        if "structuredContent" in result:
            return result["structuredContent"]
        return json.loads(result["content"][0]["text"])

    def test_an_unverified_session_is_told_how_to_ask(self) -> None:
        who = self.content(self.client.call("agent_whoami", {}))
        self.assertFalse(who["verified"])
        self.assertIn("agent_claim_begin", who["how"])

    def test_asking_changes_nothing_and_hands_the_session_nothing_it_could_use(self) -> None:
        asked, _ = self.ask()
        self.assertTrue(asked["claim_id"].startswith("clm_"))
        self.assertIn("the window where it is running", asked["tell_the_user"])
        self.assertNotIn("--code", json.dumps(asked))
        self.assertFalse(self.content(self.client.call("agent_whoami", {}))["verified"])
        sent = self.content(self.client.call("message_send", {
            "sender": REVIEWER, "recipient": ARCHITECT, "kind": "question", "payload": {"text": "before approval"}}))
        self.assertEqual(sent["error"], "IdentityRequired")

    def test_the_session_that_asked_becomes_verified_in_place(self) -> None:
        asked, code = self.ask()
        pending = self.content(self.client.call("agent_whoami", {}))["pending_claim"]
        self.assertEqual(pending["claim_id"], asked["claim_id"])
        self.human_decides(asked["claim_id"], code)
        who = self.content(self.client.call("agent_whoami", {}))
        self.assertTrue(who["verified"], "no reconnect: the same MCP session is now bound")
        self.assertEqual(who["agent_id"], REVIEWER)
        sent = self.content(self.client.call("message_send", {
            "recipient": ARCHITECT, "kind": "question", "payload": {"text": "after approval"}}))
        self.assertEqual(sent["sender_agent_id"], REVIEWER)

    def test_a_different_session_does_not_get_the_identity(self) -> None:
        asked, code = self.ask()
        self.human_decides(asked["claim_id"], code)
        other = Http(self.server.url)
        other.initialize()
        self.assertFalse(self.content(other.call("agent_whoami", {}))["verified"],
                         "approval binds the session that asked, not whoever connects next")

    def test_a_denied_session_stays_unverified(self) -> None:
        asked, code = self.ask()
        self.human_decides(asked["claim_id"], code, approve=False)
        self.assertFalse(self.content(self.client.call("agent_whoami", {}))["verified"])

    def test_a_session_that_is_already_somebody_cannot_ask_to_be_somebody_else(self) -> None:
        asked, code = self.ask()
        self.human_decides(asked["claim_id"], code)
        self.client.call("agent_whoami", {})
        again = self.content(self.client.call("agent_claim_begin", {"agent_id": ARCHITECT}))
        self.assertEqual(again["error"], "AlreadyBound")

    def test_taking_the_binding_away_ends_the_session_rather_than_downgrading_it(self) -> None:
        """The upgrade is allowed in one direction only. A session that loses
        its binding must not quietly carry on as an unverified caller."""
        asked, code = self.ask()
        decided = self.human_decides(asked["claim_id"], code)
        self.assertTrue(self.content(self.client.call("agent_whoami", {}))["verified"])
        with Store.open(self.db) as human:
            human.migrate()
            human.trust = "human"
            human.revoke_binding(str(decided["binding_id"]), by="human:test", reason="detached")
        status, _, _ = self.client.rpc("tools/call", {"name": "agent_whoami", "arguments": {}})
        self.assertEqual(status, 401)

    def test_the_identity_ends_with_the_session_it_was_given_to(self) -> None:
        """A claim binding has no terminal and no pid, so nothing else would
        ever reap it: it would sit active for its whole TTL, blocking a fresh
        claim for that agent and, being human-owned, blocking managed dispatch
        for it too."""
        asked, code = self.ask()
        decided = self.human_decides(asked["claim_id"], code)
        self.assertTrue(self.content(self.client.call("agent_whoami", {}))["verified"])
        status, _, _ = self.client.raw(b"", method="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(self.store.get_binding(str(decided["binding_id"]))["state"], "revoked")
        # And the agent is free again, which is the point.
        fresh = Http(self.server.url)
        fresh.initialize()
        console = io.StringIO()
        with redirect_stdout(console):
            again = self.content(fresh.call("agent_claim_begin", {"agent_id": REVIEWER}))
        self.assertTrue(again["claim_id"].startswith("clm_"))

    def test_a_claim_binding_does_not_outlive_an_evicted_session(self) -> None:
        asked, code = self.ask()
        decided = self.human_decides(asked["claim_id"], code)
        self.assertTrue(self.content(self.client.call("agent_whoami", {}))["verified"])
        # Idle it out, then make the server evict on the next initialize.
        with self.server._lock:
            for record in self.server.sessions.values():
                record["last_seen"] = 0.0
        Http(self.server.url).initialize()
        self.assertEqual(self.store.get_binding(str(decided["binding_id"]))["state"], "revoked")

    def test_the_writes_it_makes_are_recorded_as_bound_not_asserted(self) -> None:
        """The point of doing this at all: evidence from a claimed session is
        worth what evidence from `run` is worth."""
        asked, code = self.ask()
        self.human_decides(asked["claim_id"], code)
        self.client.call("message_send", {"recipient": ARCHITECT, "kind": "question", "payload": {"text": "hello"}})
        sent = [e for e in self.store.events(limit=200) if e["kind"] == "message.sent"]
        self.assertEqual([e["payload"]["trust"] for e in sent], ["bound"])


class OnScreenTests(ClaimCase):
    """M7d: the same decision, asked somewhere that costs the user nothing.

    No test opens a real window: the runner is injected, which is also what
    lets these assert the shape of what the daemon would have run.
    """

    def setUp(self) -> None:
        super().setUp()
        self.asked: list[list[str]] = []

    @contextmanager
    def env(self, **values: Optional[str]):
        previous = {k: os.environ.get(k) for k in values}
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def runner(self, answer: str, *, returncode: int = 0):
        class Result:
            def __init__(self, code: int, out: str) -> None:
                self.returncode, self.stdout = code, out

        def run(argv: list[str], timeout: int) -> Result:
            self.asked.append(argv)
            return Result(returncode, answer)
        return run

    def server_with(self, answer: str, *, returncode: int = 0, approve_with: str = "dialog") -> Any:
        server = BusServer(self.db, TOKEN, port=0, allow_unattributed=False,
                           approve_with=approve_with, dialog_seconds=1,
                           dialog_runner=self.runner(answer, returncode=returncode)).start()
        self.addCleanup(server.stop)
        return server

    def claim_through(self, server: Any, agent: str = REVIEWER) -> tuple[Http, dict[str, Any], str]:
        client = Http(server.url)
        client.initialize()
        console = io.StringIO()
        with redirect_stdout(console):
            asked = client.call("agent_claim_begin", {"agent_id": agent})["structuredContent"]
        # The dialog is raised on a thread; give it its moment.
        for _ in range(200):
            if self.asked or self.store.get_claim(asked["claim_id"])["state"] != "open":
                break
            time.sleep(0.01)
        time.sleep(0.05)
        return client, asked, console.getvalue()

    def test_clicking_allow_verifies_the_session_with_nothing_typed(self) -> None:
        server = self.server_with("button returned:Allow\n")
        client, asked, console = self.claim_through(server)
        self.assertEqual(self.store.get_claim(asked["claim_id"])["state"], "approved")
        who = client.call("agent_whoami", {})["structuredContent"]
        self.assertTrue(who["verified"])
        self.assertEqual(who["agent_id"], REVIEWER)
        self.assertIn("answer the dialog", console)
        self.assertNotIn("--code", console, "no code is printed when the question was asked on screen")

    def test_the_question_names_what_is_being_approved(self) -> None:
        server = self.server_with("button returned:Allow\n")
        _, asked, _ = self.claim_through(server)
        script = self.asked[0][-1]
        self.assertIn(REVIEWER, script)
        self.assertIn(asked["claim_id"], script)
        self.assertIn("Allow", script)
        self.assertIn("Deny", script)

    def test_clicking_deny_leaves_it_unverified(self) -> None:
        server = self.server_with("button returned:Deny\n")
        client, asked, _ = self.claim_through(server)
        self.assertEqual(self.store.get_claim(asked["claim_id"])["state"], "denied")
        self.assertFalse(client.call("agent_whoami", {})["structuredContent"]["verified"])

    def test_a_dialog_nobody_answers_decides_nothing(self) -> None:
        server = self.server_with("gave up:true\n")
        client, asked, _ = self.claim_through(server)
        self.assertEqual(self.store.get_claim(asked["claim_id"])["state"], "open")
        self.assertFalse(client.call("agent_whoami", {})["structuredContent"]["verified"])

    def test_a_machine_with_no_dialog_falls_back_to_the_console_code(self) -> None:
        server = self.server_with("", approve_with="console")
        _, asked, console = self.claim_through(server)
        self.assertEqual(self.asked, [], "console mode must not raise a window")
        self.assertRegex(console, r"--code [0-9a-f]{8}")
        self.assertEqual(self.store.get_claim(asked["claim_id"])["state"], "open")

    def test_no_approval_code_exists_in_anything_the_session_can_see(self) -> None:
        server = self.server_with("button returned:Allow\n")
        _, asked, console = self.claim_through(server)
        self.assertNotRegex(json.dumps(asked), r"\b[0-9a-f]{8}\b")
        self.assertNotIn("--code", console)

    def test_peer_text_cannot_escape_the_script_it_is_quoted_into(self) -> None:
        """The client name reaches this from the session that is asking. A
        quote in it would end the AppleScript string and start running
        whatever followed."""
        hostile = 'x" & (do shell script "touch /tmp/pwned") & "'
        script = approval.applescript("title", f"client: {hostile}", "Allow", "Deny", 10)
        # With every escaped quote removed, no unescaped quote may still be
        # followed by AppleScript's concatenation operator.
        self.assertNotIn('" & (', script.replace('\\"', ""))
        self.assertIn('\\"', script)
        self.assertTrue(script.startswith("display dialog "))

    def test_every_desktop_gets_a_backend_and_a_headless_one_gets_none(self) -> None:
        """One question, four ways to ask it, and no way to pretend a machine
        that cannot show a window has answered."""
        self.assertEqual([b.name for b in approval.backends_for("darwin")], ["osascript"])
        self.assertEqual([b.name for b in approval.backends_for("linux")], ["zenity", "kdialog"])
        self.assertEqual([b.name for b in approval.backends_for("win32")], ["powershell"])
        self.assertEqual([b.name for b in approval.backends_for("freebsd13")], ["zenity", "kdialog"])
        installed = {"zenity": "/usr/bin/zenity", "kdialog": "/usr/bin/kdialog"}
        # The suite arms the kill switch; this test is about what happens when
        # it is not armed.
        with self.env(DISPLAY=":0", **{approval.NO_DIALOG_ENV: None}):
            self.assertEqual(approval.pick("linux", installed.get).name, "zenity")
            self.assertEqual(approval.pick("linux", lambda b: installed["kdialog"] if b == "kdialog" else None).name,
                             "kdialog")
            self.assertIsNone(approval.pick("linux", lambda _: None), "neither installed: no dialog")
        with self.env(DISPLAY=None, WAYLAND_DISPLAY=None, **{approval.NO_DIALOG_ENV: None}):
            self.assertIsNone(approval.pick("linux", installed.get), "no display: nothing to draw on")

    def test_the_windows_command_carries_the_text_where_no_shell_can_read_it(self) -> None:
        """PowerShell quoting is not a boundary anyone should have to reason
        about, so the command is base64 UTF-16LE and nothing parses it."""
        hostile = "'; Start-Process calc; '"
        argv = approval._powershell("title", f"client: {hostile}", "Allow", "Deny", 10)
        self.assertEqual(argv[:4], ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand"])
        decoded = base64.b64decode(argv[4]).decode("utf-16-le")
        self.assertIn("MessageBox", decoded)
        # With the doubled quotes removed -- PowerShell's only escape inside a
        # single-quoted string -- the two delimiters are the only quotes left,
        # so the peer's text contributed none of its own.
        argument = decoded.split("MessageBox]::Show(")[1].split(", 'title'")[0]
        stripped = argument.replace("''", "")
        self.assertEqual(stripped.count("'"), 2, stripped)
        self.assertTrue(stripped.startswith("'") and stripped.endswith("'"))
        self.assertIn("''; Start-Process calc; ''", decoded)

    def test_the_linux_backends_pass_text_as_arguments_not_as_a_command_line(self) -> None:
        body = "--fake-option $(touch /tmp/pwned)"
        for argv in (approval._zenity("t", body, "Allow", "Deny", 10),
                     approval._kdialog("t", body, "Allow", "Deny", 10)):
            self.assertIn(body, argv, "the text is one argument, so no shell ever sees it")
            self.assertEqual(argv.count(body), 1)

    def test_a_yes_that_prints_nothing_still_reads_as_yes(self) -> None:
        """zenity and kdialog answer with the exit code and no output; a
        parser written for osascript alone would read that as a refusal."""
        for name in ("zenity", "kdialog"):
            backend = next(b for b in approval.BACKENDS if b.name == name)
            self.assertIs(approval.ask("t", "b", seconds=1, backend=backend,
                                       runner=self.runner("", returncode=0)), True)
            self.assertIs(approval.ask("t", "b", seconds=1, backend=backend,
                                       runner=self.runner("", returncode=1)), False)
            self.assertIsNone(approval.ask("t", "b", seconds=1, backend=backend,
                                           runner=self.runner("", returncode=5)),
                              "a backend that could not run has not answered")

    def test_the_kill_switch_stops_any_window_being_raised(self) -> None:
        """Armed by the test suite itself; also the answer for a headless or
        remote macOS session."""
        self.assertFalse(approval.dialog_available())


class TheOtherTerminalTests(ClaimCase):
    """Phase two has to happen somewhere the asking session cannot reach."""

    def run_cli(self, *argv: str, stdin_tty: bool = True, stdout_tty: bool = True,
                answer: str = "y", inside: Optional[dict[str, Any]] = None) -> tuple[int, str, str]:
        import builtins
        import sys as real_sys

        class Tty(io.StringIO):
            """A buffer that answers isatty(), because whether this is a
            person's terminal is the thing being tested."""

            def __init__(self, tty: bool) -> None:
                super().__init__()
                self._tty = tty

            def isatty(self) -> bool:
                return self._tty

        out, err, stdin = Tty(stdout_tty), Tty(True), Tty(stdin_tty)
        real_input, real_provider, real_stdin = builtins.input, procinfo.provider_above, real_sys.stdin
        builtins.input = lambda *_: answer  # type: ignore[assignment]
        procinfo.provider_above = lambda pid: inside  # type: ignore[assignment]
        real_sys.stdin = stdin
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["claim", *argv, "--state-dir", str(self.state_dir)])
        finally:
            builtins.input = real_input  # type: ignore[assignment]
            procinfo.provider_above = real_provider  # type: ignore[assignment]
            real_sys.stdin = real_stdin
        return code, out.getvalue(), err.getvalue()

    def test_approving_from_inside_the_session_that_asked_is_refused(self) -> None:
        """Both CLIs can run shell commands. Without this the model approves
        its own request and the second phase proves nothing."""
        request = self.ask()
        code, _, err = self.run_cli("approve", request["id"], "--code", self.codes[request["id"]],
                                    inside={"pid": 1234, "tty": "ttys001", "provider": "claude"})
        self.assertEqual(code, 2)
        self.assertIn("claude session", err)
        self.assertEqual(self.store.get_claim(request["id"])["state"], "open")

    def test_a_pipe_is_refused(self) -> None:
        request = self.ask()
        code, _, err = self.run_cli("approve", request["id"], "--code", self.codes[request["id"]],
                                    stdin_tty=False)
        self.assertEqual(code, 2)
        self.assertIn("a person decides this", err)

    def test_approving_from_a_terminal_of_your_own_works_and_shows_what_is_being_asked(self) -> None:
        request = self.ask()
        code, out, _ = self.run_cli("approve", request["id"], "--code", self.codes[request["id"]])
        self.assertEqual(code, 0)
        self.assertIn(REVIEWER, out)
        self.assertIn("without reconnecting", out)
        self.assertEqual(self.store.get_claim(request["id"])["state"], "approved")

    def test_answering_anything_but_yes_changes_nothing(self) -> None:
        request = self.ask()
        code, _, _ = self.run_cli("approve", request["id"], answer="")
        self.assertEqual(code, 1)
        self.assertEqual(self.store.get_claim(request["id"])["state"], "open")

    def test_listing_shows_what_is_waiting_without_leaking_the_session(self) -> None:
        request = self.ask()
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn(request["id"], out)
        self.assertIn(REVIEWER, out)
        self.assertNotIn(self.key(), out)


if __name__ == "__main__":
    unittest.main()

"""M4.5 identity suite (ADR 0004): terminal bindings, session credentials,
the actor-field matrix, and the invariant that an unattributed request never
reads as a proven one.

The store half proves minting, exclusivity, revocation and reaping. The
server half drives real HTTP requests, because the whole point of a session
credential is that it travels on the wire.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from luciazero_agentd import Store
from luciazero_agentd.store import BINDING_MAX_LIFETIME_SECONDS
from luciazero_agentd import procinfo
from luciazero_agentd.redact import CREDENTIAL_PATTERN, CREDENTIAL_PREFIX, DEFAULT as DEFAULT_REDACTOR
from luciazero_agentd.server import ACTOR_FIELDS, TOOL_INDEX, BusServer, tool_contract
from luciazero_agentd.store import ConflictError, NotFound, UnsafeReference
from tests.test_mcp import TOKEN, Http

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ALIVE = lambda *_: True          # noqa: E731 - the process is there
GONE = lambda *_: False          # noqa: E731 - the process is not


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-identity-")
        self.db = str(Path(os.path.realpath(self._tmp.name)) / "bus.sqlite3")
        self.store = Store.open(self.db)
        self.store.migrate()
        self.store.trust = "human"
        for agent, provider in (("claude-reviewer", "claude"), ("codex-architect", "codex")):
            self.store.register_agent(agent, provider=provider, role=agent.split("-")[1])
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.store.close)

    def bind(self, agent="claude-reviewer", **kw):
        kw.setdefault("provider", "claude")
        kw.setdefault("by", "human:test")
        return self.store.bind_terminal(agent, **kw)


class Bindings(StoreCase):
    def test_credential_shape_is_minted_once_and_never_stored(self) -> None:
        binding, credential = self.bind(tty="ttys100", pid=os.getpid())
        self.assertTrue(CREDENTIAL_PATTERN.fullmatch(credential))
        self.assertNotIn("credential_hash", binding)
        row = self.store._conn.execute("SELECT credential_hash FROM bindings WHERE id = ?", (binding["id"],)).fetchone()
        self.assertNotIn(credential, str(row["credential_hash"]))
        self.assertEqual(self.store.resolve_credential(credential, alive=ALIVE)["agent_id"], "claude-reviewer")

    def test_unknown_and_malformed_credentials_resolve_to_nobody(self) -> None:
        for value in (None, 42, "", "bearer", CREDENTIAL_PREFIX + "0" * 32, CREDENTIAL_PREFIX + "zz", "lzap_" + "0" * 32):
            self.assertIsNone(self.store.resolve_credential(value, alive=ALIVE), value)

    def test_a_takeover_replaces_the_previous_binding_for_that_agent(self) -> None:
        """What a takeover does once it has been asked for: the old
        credential dies, the new one answers, and the generation moves so the
        two are never confused for each other."""
        first, cred1 = self.bind(tty="ttys101", pid=os.getpid())
        second, cred2 = self.bind(tty="ttys102", pid=os.getpid(), replace_live_human=True)
        self.assertIsNone(self.store.resolve_credential(cred1, alive=ALIVE))
        self.assertEqual(self.store.resolve_credential(cred2, alive=ALIVE)["id"], second["id"])
        self.assertEqual(self.store.get_binding(first["id"])["state"], "revoked")
        self.assertGreater(second["generation"], first["generation"])

    def test_one_terminal_cannot_answer_as_two_agents(self) -> None:
        reviewer, cred_reviewer = self.bind("claude-reviewer", tty="ttys103", pid=os.getpid())
        architect, cred_architect = self.bind("codex-architect", provider="codex", tty="ttys103", pid=os.getpid())
        self.assertIsNone(self.store.resolve_credential(cred_reviewer, alive=ALIVE))
        self.assertEqual(self.store.resolve_credential(cred_architect, alive=ALIVE)["agent_id"], "codex-architect")
        live = [b["agent_id"] for b in self.store.list_bindings(alive=None)]
        self.assertEqual(live, ["codex-architect"])

    def test_a_second_launcher_is_refused_instead_of_handed_the_id(self) -> None:
        """The id belongs to whoever is sitting at the terminal that holds it.
        A launcher that finds it taken says so; it does not end the session
        that is using it and take its place."""
        _, working = self.bind(tty="ttys120", pid=os.getpid())
        with self.assertRaises(ConflictError) as caught:
            self.bind(tty="ttys121", pid=os.getpid())
        self.assertIn("already bound", str(caught.exception))
        self.assertIn("detach", str(caught.exception), "a refusal names the way out")
        self.assertEqual("claude-reviewer",
                         self.store.resolve_credential(working, alive=ALIVE)["agent_id"])

    def test_a_takeover_happens_only_when_it_is_asked_for(self) -> None:
        """`attach` is a person naming a terminal and an agent in one breath.
        That sentence is allowed to replace what was there."""
        _, first = self.bind(tty="ttys122", pid=os.getpid())
        _, second = self.bind(tty="ttys123", pid=os.getpid(), replace_live_human=True)
        self.assertIsNone(self.store.resolve_credential(first, alive=ALIVE))
        self.assertEqual("claude-reviewer",
                         self.store.resolve_credential(second, alive=ALIVE)["agent_id"])

    def test_a_binding_whose_time_ran_out_does_not_hold_the_id(self) -> None:
        """The refusal is about a live session, not about a row. An expired
        binding proves nobody is there any more."""
        binding, _ = self.bind(tty="ttys124", pid=os.getpid())
        self.store._conn.execute(
            "UPDATE bindings SET expires_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="microseconds"),
             binding["id"]))
        self.store._conn.commit()
        _, credential = self.bind(tty="ttys125", pid=os.getpid())
        self.assertEqual("claude-reviewer",
                         self.store.resolve_credential(credential, alive=ALIVE)["agent_id"])

    def test_two_launchers_racing_leave_one_binding_and_one_refusal(self) -> None:
        """Reaping happens outside the transaction, so both launchers can
        walk past a free-looking id at the same moment. What makes the second
        one refuse is the transaction, not the check before it."""
        import threading

        ready = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def launch(tty: str) -> None:
            try:
                with Store.open(self.db) as store:
                    store.migrate()
                    store.trust = "human"
                    ready.wait(timeout=10)
                    store.bind_terminal("claude-reviewer", provider="claude", by="human:test",
                                        tty=tty, pid=os.getpid())
                outcome = "bound"
            except ConflictError:
                outcome = "refused"
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=launch, args=(tty,)) for tty in ("ttys126", "ttys127")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(["bound", "refused"], sorted(outcomes))
        live = [b for b in self.store.list_bindings(alive=None) if b["agent_id"] == "claude-reviewer"]
        self.assertEqual(1, len(live), "one id, one live binding, however many launchers ask")

    def test_detach_kills_the_credential(self) -> None:
        binding, credential = self.bind(tty="ttys104", pid=os.getpid())
        self.store.revoke_binding(binding["id"], by="human:test")
        self.assertIsNone(self.store.resolve_credential(credential, alive=ALIVE))
        with self.assertRaises(ConflictError):
            self.store.revoke_binding(binding["id"], by="human:test")

    def test_a_dead_process_makes_the_binding_stale_on_the_next_request(self) -> None:
        binding, credential = self.bind(tty="ttys105", pid=os.getpid(), process_started_at="then")
        self.assertIsNone(self.store.resolve_credential(credential, alive=GONE))
        self.assertEqual(self.store.get_binding(binding["id"])["state"], "stale")
        self.assertIsNone(self.store.resolve_credential(credential, alive=ALIVE))
        kinds = [e["kind"] for e in self.store.events(limit=50)]
        self.assertIn("binding.stale", kinds)

    def test_a_credential_in_use_is_renewed_before_it_can_expire(self) -> None:
        """The session that broke this was fifteen hours into its own work when
        the daemon stopped answering it: the terminal was alive, the process
        check passed, and the twelve-hour window had simply run out."""
        binding, credential = self.bind(tty="ttys120", pid=os.getpid(), ttl_seconds=3600)
        soon = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="microseconds")
        self.store._conn.execute("UPDATE bindings SET expires_at = ? WHERE id = ?", (soon, binding["id"]))
        resolved = self.store.resolve_credential(credential, alive=ALIVE)
        self.assertIsNotNone(resolved)
        self.assertGreater(str(resolved["expires_at"]), soon)
        self.assertIn("binding.renewed", [e["kind"] for e in self.store.events(limit=50)])

    def test_renewal_keeps_the_window_the_binding_was_created_with(self) -> None:
        """A short `--ttl` is a decision, not a starting point: renewing it by
        the default would hand a session twelve hours it was denied on purpose."""
        binding, credential = self.bind(tty="ttys121", pid=os.getpid(), ttl_seconds=60)
        soon = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat(timespec="microseconds")
        self.store._conn.execute("UPDATE bindings SET expires_at = ? WHERE id = ?", (soon, binding["id"]))
        resolved = self.store.resolve_credential(credential, alive=ALIVE)
        window = datetime.fromisoformat(str(resolved["expires_at"])) - datetime.now(timezone.utc)
        self.assertLessEqual(window, timedelta(seconds=60))

    def test_renewal_never_carries_a_binding_past_its_ceiling(self) -> None:
        """Renewal must not make a binding immortal on a machine nobody reboots."""
        binding, credential = self.bind(tty="ttys122", pid=os.getpid(), ttl_seconds=3600)
        born = datetime.now(timezone.utc) - timedelta(seconds=BINDING_MAX_LIFETIME_SECONDS)
        soon = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="microseconds")
        self.store._conn.execute("UPDATE bindings SET created_at = ?, expires_at = ? WHERE id = ?",
                                 (born.isoformat(timespec="microseconds"), soon, binding["id"]))
        resolved = self.store.resolve_credential(credential, alive=ALIVE)
        self.assertEqual(str(resolved["expires_at"]), soon)
        self.store._conn.execute("UPDATE bindings SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (binding["id"],))
        self.assertIsNone(self.store.resolve_credential(credential, alive=ALIVE))

    def test_an_expired_credential_is_refused_even_while_the_process_lives(self) -> None:
        binding, credential = self.bind(tty="ttys106", pid=os.getpid(), ttl_seconds=60)
        self.store._conn.execute("UPDATE bindings SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (binding["id"],))
        self.assertIsNone(self.store.resolve_credential(credential, alive=ALIVE))
        self.assertEqual(self.store.get_binding(binding["id"])["ended_reason"], "expired")

    def test_listing_reaps_what_it_walks_past(self) -> None:
        binding, credential = self.bind(tty="ttys107", pid=os.getpid())
        self.assertEqual(len(self.store.list_bindings(alive=GONE)), 0)
        self.assertEqual(self.store.get_binding(binding["id"])["state"], "stale")

    def test_binding_an_unknown_agent_is_refused(self) -> None:
        with self.assertRaises(NotFound):
            self.bind("nobody-here")

    def test_process_identity_is_filled_in_once(self) -> None:
        binding, _ = self.bind(tty="ttys108")
        self.assertIsNone(binding["pid"])
        filled = self.store.bind_process(binding["id"], pid=os.getpid(), process_started_at="t0", cwd="/tmp")
        self.assertEqual(filled["pid"], os.getpid())
        with self.assertRaises(ConflictError):
            self.store.bind_process(binding["id"], pid=1, process_started_at="t1")

    def test_a_credential_shape_cannot_be_smuggled_through_a_binding_field(self) -> None:
        with self.assertRaises(UnsafeReference):
            self.bind(tty=CREDENTIAL_PREFIX + "a" * 32)

    def test_the_credential_shape_is_scrubbed_and_refused_like_a_nonce(self) -> None:
        text, hits = DEFAULT_REDACTOR.text("here is " + CREDENTIAL_PREFIX + "f" * 32)
        self.assertEqual(hits, 1)
        self.assertNotIn(CREDENTIAL_PREFIX + "f" * 32, text)
        self.assertEqual(DEFAULT_REDACTOR.scan(CREDENTIAL_PREFIX + "f" * 32), ["session-credential"])

    def test_status_marks_every_agent_verified_or_not(self) -> None:
        self.bind("claude-reviewer", tty="ttys109", pid=os.getpid())
        status = self.store.status()
        by_id = {a["id"]: a for a in status["agents"]}
        self.assertTrue(by_id["claude-reviewer"]["verified"])
        self.assertFalse(by_id["codex-architect"]["verified"])
        self.assertEqual(status["unverified_agents"], ["codex-architect"])
        self.assertEqual(by_id["claude-reviewer"]["binding"]["tty"], "ttys109")

    def test_status_stops_calling_an_agent_verified_when_its_credential_dies(self) -> None:
        # a real pid with its real start time, so liveness is not what decides
        binding, _ = self.bind("claude-reviewer", tty="ttys111", pid=os.getpid(), process_started_at=procinfo.started_at(os.getpid()))
        self.assertTrue({a["id"]: a for a in self.store.status()["agents"]}["claude-reviewer"]["verified"])
        self.store._conn.execute("UPDATE bindings SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (binding["id"],))
        status = self.store.status()
        self.assertFalse({a["id"]: a for a in status["agents"]}["claude-reviewer"]["verified"])
        self.assertIn("claude-reviewer", status["unverified_agents"])

    def test_status_stops_calling_an_agent_verified_when_its_process_is_gone(self) -> None:
        self.bind("claude-reviewer", tty="ttys112", pid=os.getpid(), process_started_at="then")
        self.assertIsNone(self.store.binding_of("claude-reviewer", alive=GONE))
        self.assertIsNotNone(self.store.binding_of("claude-reviewer", alive=ALIVE))
        # reporting only: a read-only status view must not write
        self.assertEqual(self.store.get_binding(self.store.list_bindings(alive=None)[0]["id"])["state"], "active")

    def test_every_event_says_how_much_the_actor_is_trusted(self) -> None:
        self.bind("claude-reviewer", tty="ttys110", pid=os.getpid())
        self.store.trust = "asserted"
        self.store.send_message(sender="claude-reviewer", recipient="codex-architect", kind="finding", payload={"a": 1})
        trusts = {e["kind"]: e["payload"].get("trust") for e in self.store.events(limit=50)}
        self.assertEqual(trusts["binding.created"], "human")
        self.assertEqual(trusts["message.sent"], "asserted")
        self.assertNotIn(None, trusts.values())


class ServerCase(unittest.TestCase):
    """One daemon, one bound agent, one unbound agent."""

    allow_unattributed = True  # subclasses that test the shipped default set this False

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-identity-http-")
        self.state = Path(os.path.realpath(self._tmp.name))
        self.db = str(self.state / "bus.sqlite3")
        with Store.open(self.db) as store:
            store.migrate()
            store.trust = "human"
            store.register_agent("claude-reviewer", provider="claude", role="reviewer")
            store.register_agent("codex-architect", provider="codex", role="architect")
            self.binding, self.credential = store.bind_terminal(
                "claude-reviewer", provider="claude", by="human:test",
                tty=None, pid=os.getpid(), process_started_at=None, cwd=str(self.state),
            )
        self.server = BusServer(self.db, TOKEN, port=0, allow_unattributed=self.allow_unattributed).start()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.server.stop)

    def bound(self) -> Http:
        client = Http(self.server.url, token=self.credential)
        client.initialize()
        return client

    def unbound(self) -> Http:
        client = Http(self.server.url)
        client.initialize()
        return client

    @staticmethod
    def payload(result: dict) -> dict:
        return json.loads(result["content"][0]["text"])

    def events(self) -> list[dict]:
        with Store.open(self.db) as store:
            return store.events(limit=200)


class WhoAmI(ServerCase):
    def test_a_bound_session_is_told_who_it_is(self) -> None:
        answer = self.payload(self.bound().call("agent_whoami", {}))
        self.assertTrue(answer["verified"])
        self.assertEqual(answer["agent_id"], "claude-reviewer")
        self.assertEqual(answer["binding_id"], self.binding["id"])
        self.assertEqual(answer["pid"], os.getpid())

    def test_an_unbound_session_is_told_it_is_unverified_and_never_guessed_at(self) -> None:
        answer = self.payload(self.unbound().call("agent_whoami", {}))
        self.assertFalse(answer["verified"])
        self.assertIsNone(answer["agent_id"])
        self.assertIn("no terminal credential", answer["reason"])
        self.assertIn("attach", answer["how"])
        # the store holds exactly one bound agent and one worktree-less peer:
        # a guess would have been easy, and is refused anyway.
        self.assertNotIn("claude-reviewer", json.dumps(answer))


class ActorFields(ServerCase):
    def test_the_daemon_fills_in_the_actor_field(self) -> None:
        client = self.bound()
        sent = self.payload(client.call("message_send", {"recipient": "codex-architect", "kind": "finding", "payload": {"ok": True}}))
        self.assertEqual(sent["sender_agent_id"], "claude-reviewer")

    def test_naming_another_agent_is_refused_and_recorded(self) -> None:
        client = self.bound()
        result = client.call("message_send", {"sender": "codex-architect", "recipient": "codex-architect", "kind": "finding", "payload": {}})
        self.assertTrue(result["isError"])
        body = self.payload(result)
        self.assertEqual(body["error"], "IdentityMismatch")
        refusals = [e for e in self.events() if e["kind"] == "session.identity_refused"]
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["payload"]["claimed"], "codex-architect")
        self.assertEqual(refusals[0]["payload"]["field"], "sender")
        self.assertEqual(refusals[0]["payload"]["tool"], "message_send")
        self.assertEqual(refusals[0]["payload"]["trust"], "bound")

    def test_every_actor_field_of_every_writing_tool_is_enforced(self) -> None:
        client = self.bound()
        for tool, field in ACTOR_FIELDS.items():
            with self.subTest(tool=tool):
                args = {field: "codex-architect"}
                for name, spec in TOOL_INDEX[tool]["inputSchema"]["properties"].items():
                    if name == field or name not in TOOL_INDEX[tool]["inputSchema"].get("required", []):
                        continue
                    args[name] = {"string": "x", "object": {}, "integer": 1, "boolean": True, "array": []}[spec.get("type", "string")]
                body = self.payload(client.call(tool, args))
                self.assertEqual(body.get("error"), "IdentityMismatch", (tool, body))

    def test_a_read_only_query_may_still_name_a_peer(self) -> None:
        client = self.bound()
        body = self.payload(client.call("worktree_get", {"agent_id": "codex-architect"}))
        self.assertEqual(body["error"], "NotFound")  # no worktree, not an identity refusal
        self.assertEqual([e for e in self.events() if e["kind"] == "session.identity_refused"], [])

    def test_the_published_contract_stops_requiring_what_the_daemon_fills(self) -> None:
        _, _, listed = self.bound().rpc("tools/list")
        required = {t["name"]: t["inputSchema"].get("required", []) for t in listed["result"]["tools"]}
        for tool, field in ACTOR_FIELDS.items():
            self.assertNotIn(field, required[tool], tool)
        self.assertIn("recipient", required["message_send"])
        # the module-level contract is untouched for unverified sessions
        self.assertIn("sender", [t for t in tool_contract() if t["name"] == "message_send"][0]["inputSchema"]["required"])

    def test_an_unbound_session_still_works_when_unattributed_is_allowed(self) -> None:
        sent = self.payload(self.unbound().call("message_send", {"sender": "codex-architect", "recipient": "claude-reviewer", "kind": "finding", "payload": {}}))
        self.assertEqual(sent["sender_agent_id"], "codex-architect")
        trusts = {e["kind"]: e["payload"].get("trust") for e in self.events()}
        self.assertEqual(trusts["message.sent"], "asserted")


class RequireBinding(ServerCase):
    allow_unattributed = False

    def test_the_shipped_daemon_refuses_unverified_acting_by_default(self) -> None:
        """The M4.5 decision: identity is the base M5 builds dispatch on, so
        the default is not a bus where agents may wear each other's names."""
        default = BusServer(self.db, TOKEN, port=0).start()
        self.addCleanup(default.stop)
        self.assertFalse(default.allow_unattributed)
        client = Http(default.url)
        client.initialize()
        result = client.call("task_create", {"title": "x", "created_by": "codex-architect"})
        self.assertTrue(result["isError"])
        self.assertEqual(self.payload(result)["error"], "IdentityRequired")

    def test_actor_calls_need_a_credential(self) -> None:
        result = self.unbound().call("message_send", {"sender": "codex-architect", "recipient": "claude-reviewer", "kind": "finding", "payload": {}})
        self.assertTrue(result["isError"])
        self.assertEqual(self.payload(result)["error"], "IdentityRequired")

    def test_read_only_tools_and_whoami_still_answer(self) -> None:
        client = self.unbound()
        self.assertIn("agents", self.payload(client.call("agent_list", {})))
        self.assertFalse(self.payload(client.call("agent_whoami", {}))["verified"])

    def test_the_flag_changes_what_is_permitted_not_what_is_claimed(self) -> None:
        """The ADR 0004 invariant, asserted on both settings of the flag."""
        strict = self.payload(self.unbound().call("agent_whoami", {}))
        self.server.stop()
        self.server = BusServer(self.db, TOKEN, port=0, allow_unattributed=True).start()
        lenient = self.payload(self.unbound().call("agent_whoami", {}))
        self.assertEqual(strict["verified"], lenient["verified"], "the label must not depend on the flag")
        self.assertEqual(strict["agent_id"], lenient["agent_id"])
        self.assertNotEqual(strict["unattributed_allowed"], lenient["unattributed_allowed"])


class ApprovalsAlwaysNeedABinding(ServerCase):
    allow_unattributed = True  # even here, an approval may not be spent unverified

    def test_spending_an_approval_is_refused_without_a_binding(self) -> None:
        with Store.open(self.db) as store:
            store.migrate()
            store.trust = "human"
            task = store.create_task(title="ship it", created_by="codex-architect")
            store.claim_task(task["id"], "claude-reviewer")
            _, nonce = store.grant_approval(task["id"], "delete", granted_by="human:test")
        args = {"task_id": task["id"], "operation": "delete", "nonce": nonce, "agent_id": "claude-reviewer"}
        blocked = self.payload(self.unbound().call("approval_consume", args))
        self.assertEqual(blocked["error"], "IdentityRequired")
        self.assertIn("always needs one", blocked["message"])
        with Store.open(self.db) as store:
            self.assertEqual(len(store.pending_approvals()), 1)  # nothing was spent
        spent = self.payload(self.bound().call("approval_consume", args))
        self.assertEqual(spent["consumed_by"], "claude-reviewer")


class Revocation(ServerCase):
    def test_a_revoked_credential_stops_working_on_the_next_request(self) -> None:
        client = self.bound()
        self.assertTrue(self.payload(client.call("agent_whoami", {}))["verified"])
        with Store.open(self.db) as store:
            store.migrate()
            store.trust = "human"
            store.revoke_binding(self.binding["id"], by="human:test")
        status, _, body = client.rpc("tools/list")
        self.assertEqual(status, 401)

    def test_swapping_the_credential_of_a_live_session_ends_it(self) -> None:
        client = self.bound()
        with Store.open(self.db) as store:
            store.migrate()
            store.trust = "human"
            _, other = store.bind_terminal("claude-reviewer", provider="claude", by="human:test",
                                           tty=None, pid=os.getpid(), replace_live_human=True)
        client.token = other  # same MCP session, different binding
        status, _, body = client.rpc("tools/list")
        self.assertEqual(status, 401)
        self.assertIn("initialize again", json.dumps(body) if body else "")

    def test_an_unknown_credential_never_reaches_a_tool(self) -> None:
        client = Http(self.server.url, token=CREDENTIAL_PREFIX + "0" * 32)
        status, _, _ = client.rpc("initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(status, 401)


class HumanCommands(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-identity-cli-")
        self.state = Path(os.path.realpath(self._tmp.name))
        with Store.open(self.state / "bus.sqlite3") as store:
            store.migrate()
            store.trust = "human"
            store.register_agent("claude-reviewer", provider="claude", role="reviewer")
        self.addCleanup(self._tmp.cleanup)

    def cli(self, *args: str, stdin: str = "", raw: bool = False) -> subprocess.CompletedProcess:
        argv = list(args) if raw else [*args, "--state-dir", str(self.state)]
        return subprocess.run(
            [sys.executable, "-m", "luciazero_agentd", *argv],
            cwd=str(PACKAGE_ROOT), input=stdin, capture_output=True, text=True, timeout=60,
            # the env var is the second guard: no test may reach the real bus
            # home even if an argument lands in the wrong place.
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "LUCIAZERO_AGENT_BUS_HOME": str(self.state)},
        )

    def test_terminal_list_reports_sessions_and_bindings(self) -> None:
        done = self.cli("terminal", "list", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        payload = json.loads(done.stdout)
        self.assertIn("sessions", payload)
        self.assertEqual(payload["bindings"], [])

    def test_attach_refuses_a_pipe(self) -> None:
        done = self.cli("attach", "--agent", "claude-reviewer", "--tty", "ttys999")
        self.assertEqual(done.returncode, 2)
        self.assertIn("refusing non-interactive input", done.stderr)

    def test_sessions_and_whoami_say_unverified_when_nothing_is_bound(self) -> None:
        self.assertIn("no live binding", self.cli("sessions").stdout)
        whoami = self.cli("whoami")
        self.assertEqual(whoami.returncode, 1)
        self.assertIn("not bound", whoami.stdout)

    def test_detach_ends_a_binding_by_agent(self) -> None:
        with Store.open(self.state / "bus.sqlite3") as store:
            store.migrate()
            store.trust = "human"
            binding, _ = store.bind_terminal("claude-reviewer", provider="claude", by="human:test", tty="ttys998", pid=os.getpid())
        done = self.cli("detach", "--agent", "claude-reviewer")
        self.assertEqual(done.returncode, 0, done.stderr)
        with Store.open(self.state / "bus.sqlite3") as store:
            self.assertEqual(store.get_binding(binding["id"])["state"], "revoked")
        self.assertEqual(self.cli("detach", "--agent", "claude-reviewer").returncode, 2)

    def _sleeper(self) -> Path:
        """A provider stand-in that ignores the flags `run` adds."""
        script = self.state / "sleeper.sh"
        script.write_text("#!/bin/sh\nexec sleep 30\n")
        script.chmod(0o755)
        return script

    def _bindings(self, states=("active", "revoked", "stale")) -> list[dict]:
        with Store.open(self.state / "bus.sqlite3") as store:
            store.migrate()
            return store.list_bindings(states=states, alive=None)

    def _stop_daemon(self, state: Optional[Path] = None) -> None:
        from luciazero_agentd.statedir import read_endpoint

        endpoint = read_endpoint(self.state if state is None else state)
        if endpoint is None or not isinstance(endpoint.get("pid"), int):
            return
        try:
            os.kill(endpoint["pid"], __import__("signal").SIGTERM)
        except OSError:
            pass

    def test_run_starts_the_daemon_a_first_terminal_does_not_have(self) -> None:
        """Setup step one is "start the daemon in a terminal you can leave
        open", which is a window to lose and a thing to know. `run` needs a
        daemon, so `run` starts one."""
        from luciazero_agentd.statedir import read_endpoint

        self.addCleanup(self._stop_daemon)
        self.assertIsNone(read_endpoint(self.state))
        done = self.cli("run", "--agent", "claude-reviewer", "--provider", "claude",
                        "--state-dir", str(self.state), "--", "/bin/echo", "hello", raw=True)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        endpoint = read_endpoint(self.state)
        self.assertIsNotNone(endpoint, done.stderr)
        self.assertIn("hello", done.stdout)

    def test_no_autostart_leaves_the_old_refusal_in_place(self) -> None:
        """Automation that wants to know a daemon was already running keeps
        the answer it had."""
        done = self.cli("run", "--no-autostart", "--agent", "claude-reviewer", "--provider", "claude",
                        "--state-dir", str(self.state), "--", "/bin/echo", "hello", raw=True)
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("no running daemon", done.stderr)

    def test_an_autostarted_daemon_does_not_claim_the_service_port(self) -> None:
        """A second state directory is a second daemon, and two daemons cannot
        share a port. Claiming 8765 makes the second one die with `Errno 48`
        in a log nobody reads -- green on a machine with no daemon, red on the
        developer's, which is the flakiness this asserts away.

        The port the service uses is not held here on purpose: a test that
        occupied 8765 would be the same environment-dependent test again.
        What is asserted is that the autostarted daemon did not ask for it."""
        from urllib.parse import urlsplit

        from luciazero_agentd.statedir import read_endpoint

        self.addCleanup(self._stop_daemon)
        done = self.cli("run", "--agent", "claude-reviewer", "--provider", "claude",
                        "--state-dir", str(self.state), "--", "/bin/echo", "hello", raw=True)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        endpoint = read_endpoint(self.state)
        self.assertIsNotNone(endpoint, done.stderr)
        port = urlsplit(endpoint["url"]).port
        self.assertNotEqual(8765, port, "the stable port belongs to the installed service")

        second = Path(os.path.realpath(tempfile.mkdtemp(prefix="agentd-identity-second-")))
        self.addCleanup(self._stop_daemon, second)
        with Store.open(second / "bus.sqlite3") as store:
            store.migrate()
            store.trust = "human"
            store.register_agent("claude-reviewer", provider="claude", role="reviewer")
        done = self.cli("run", "--agent", "claude-reviewer", "--provider", "claude",
                        "--state-dir", str(second), "--", "/bin/echo", "hello", raw=True)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        other = read_endpoint(second)
        self.assertIsNotNone(other, done.stderr)
        self.assertNotEqual(port, urlsplit(other["url"]).port,
                            "two daemons on one machine need two ports")

    def test_a_daemon_that_dies_is_reported_at_once_and_with_the_reason(self) -> None:
        """The wait is for a daemon that is coming up, not for one that is
        already gone. A child that exits in the first second used to cost the
        full timeout and then say only that nothing was recorded, which names
        the symptom and not one cause."""
        import time as _time

        broken = Path(os.path.realpath(tempfile.mkdtemp(prefix="agentd-identity-broken-")))
        (broken / "bus.sqlite3").mkdir()  # sqlite cannot open a directory
        started = _time.monotonic()
        done = self.cli("run", "--agent", "claude-reviewer", "--provider", "claude",
                        "--state-dir", str(broken), "--", "/bin/echo", "hello", raw=True)
        waited = _time.monotonic() - started
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertLess(waited, 10, "a dead child is not worth a twenty second wait")
        self.assertIn("exited", done.stderr)
        self.assertIn("unable to open database", done.stderr)

    def test_a_quoted_log_is_bounded_and_never_carries_the_token(self) -> None:
        """The log is quoted into an error message, and the token sits in the
        same directory."""
        from luciazero_agentd.__main__ import LOG_TAIL_LINES, _log_tail

        token = "s" * 40
        (self.state / "token").write_text(token, encoding="utf-8")
        (self.state / "daemon.log").write_text(
            "\n".join(f"line {i} token={token}" for i in range(100)), encoding="utf-8")
        tail = _log_tail(self.state)
        self.assertNotIn(token, tail)
        self.assertIn("[redacted]", tail)
        self.assertLessEqual(len(tail.splitlines()), LOG_TAIL_LINES)

    def test_run_puts_an_agent_nobody_named_on_the_roster(self) -> None:
        """`roster add` before a first session is a step whose only job is to
        make the next command work; the id `run` is starting is the name."""
        from luciazero_agentd.statedir import read_endpoint

        self.addCleanup(self._stop_daemon)
        done = self.cli("run", "--agent", "claude-newcomer", "--provider", "claude",
                        "--state-dir", str(self.state), "--", "/bin/echo", "hello", raw=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        with Store.open(self.state / "bus.sqlite3") as store:
            store.migrate()
            self.assertEqual(store.get_agent("claude-newcomer")["provider"], "claude")
        self.assertIn("claude-newcomer", done.stderr + done.stdout)

    def test_a_provider_that_never_starts_leaves_no_live_credential(self) -> None:
        from luciazero_agentd.statedir import write_endpoint

        write_endpoint(self.state, "http://127.0.0.1:1/mcp", os.getpid(), "now")
        done = self.cli(
            "run", "--agent", "claude-reviewer", "--provider", "claude", "--state-dir", str(self.state),
            "--", str(self.state / "no-such-binary"), raw=True,
        )
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        bindings = self._bindings()
        self.assertEqual([b["state"] for b in bindings], ["revoked"])
        self.assertEqual(bindings[0]["ended_reason"], "spawn failed")

    def test_terminating_run_takes_the_child_and_the_credential_with_it(self) -> None:
        import signal
        import time

        from luciazero_agentd.statedir import write_endpoint

        write_endpoint(self.state, "http://127.0.0.1:1/mcp", os.getpid(), "now")
        cli = subprocess.Popen(
            [sys.executable, "-m", "luciazero_agentd", "run", "--agent", "claude-reviewer",
             "--provider", "claude", "--state-dir", str(self.state), "--", str(self._sleeper())],
            cwd=str(PACKAGE_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "LUCIAZERO_AGENT_BUS_HOME": str(self.state)},
        )
        self.addCleanup(cli.kill)
        for stream in (cli.stdout, cli.stderr):
            self.addCleanup(stream.close)
        child_pid = None
        for _ in range(100):  # wait for the binding to name its process
            live = [b for b in self._bindings(states=("active",)) if b["pid"]]
            if live:
                child_pid = int(live[0]["pid"])
                break
            time.sleep(0.05)
        self.assertIsNotNone(child_pid, "run never recorded its child")
        cli.send_signal(signal.SIGTERM)
        cli.wait(timeout=30)
        bindings = self._bindings()
        self.assertEqual([b["state"] for b in bindings], ["revoked"], "SIGTERM must not leave a live credential")
        self.assertEqual(bindings[0]["ended_reason"], "run exited")
        for _ in range(100):
            if not procinfo.owned(child_pid):
                break
            time.sleep(0.05)
        self.assertFalse(procinfo.owned(child_pid), "the provider child was orphaned")

    def test_run_binds_spawns_and_ends_the_binding(self) -> None:
        from luciazero_agentd.statedir import write_endpoint

        write_endpoint(self.state, "http://127.0.0.1:1/mcp", os.getpid(), "now")
        # `run` takes the command after `--`, and REMAINDER swallows any flag
        # placed after it, so the state directory has to come first.
        done = self.cli(
            "run", "--agent", "claude-reviewer", "--provider", "claude", "--state-dir", str(self.state),
            "--", "/bin/echo", "started", raw=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        # the child was handed a path, never the secret itself: argv is
        # readable through `ps` for the life of the session
        self.assertIn("--mcp-config", done.stdout)
        self.assertNotIn(CREDENTIAL_PREFIX, done.stdout)
        self.assertNotIn(CREDENTIAL_PREFIX, done.stderr)
        config = [w for w in done.stdout.split() if w.endswith("mcp.json")]
        self.assertTrue(config, done.stdout)
        self.assertFalse(Path(config[0]).exists(), "the config file must not outlive the command")
        with Store.open(self.state / "bus.sqlite3") as store:
            store.migrate()
            bindings = store.list_bindings(states=("active", "revoked", "stale"), alive=None)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["state"], "revoked")
        self.assertEqual(bindings[0]["ended_reason"], "run exited")


if __name__ == "__main__":
    unittest.main()

"""M1 store contract: migrations, pragmas, transitions, atomic claims,
idempotent replays, immutable history."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from luciazero_agentd import ConflictError, IdempotencyConflict, NotFound, Store, StoreError, ValidationError
from luciazero_agentd import migrations
from luciazero_agentd.migrations import LATEST_VERSION
from tests.fixtures import git, make_repo


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-store-")
        self.db = str(Path(self._tmp.name) / "bus.sqlite3")
        self.store = Store.open(self.db)
        self.store.migrate()
        self.store.register_agent("codex-architect", provider="codex", role="architect")
        self.store.register_agent("claude-reviewer", provider="claude", role="reviewer", capabilities=["review", "verify"])

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()


class MigrationTests(StoreCase):
    def test_fresh_database_reaches_latest_version_and_is_repeatable(self) -> None:
        self.assertEqual(self.store.schema_version(), LATEST_VERSION)
        self.assertEqual(self.store.migrate(), LATEST_VERSION)
        self.assertEqual(self.store.schema_version(), LATEST_VERSION)

    def test_the_task_rebuild_carries_the_autoincrement_mark(self) -> None:
        """M5 schema v4 rebuilds `tasks` by copying rows, which sets the new
        table's AUTOINCREMENT mark from the copied seq values. A mark standing
        above the surviving rows must be carried across: seq is the paging
        cursor, so handing one out twice makes `after` skip or repeat a task."""
        path = str(Path(self._tmp.name) / "v3.sqlite3")
        shipped = list(migrations.MIGRATIONS)
        migrations.MIGRATIONS[:] = [entry for entry in shipped if entry[0] <= 3]
        try:
            with Store.open(path) as old:
                old.migrate()
                old.register_agent("codex-architect", provider="codex", role="architect")
                # Seeded through SQL: the shipped code writes v4 columns the v3
                # table does not have, which is the point of the migration.
                for title in ("one", "two"):
                    old._conn.execute(
                        """INSERT INTO tasks (id, title, created_by_agent_id, state, created_at, updated_at)
                           VALUES (?, ?, 'codex-architect', 'open', '2026-09-04T00:00:00.000000+00:00', '2026-09-04T00:00:00.000000+00:00')""",
                        (f"tsk_{title}", title),
                    )
                mark = int(old._conn.execute("SELECT seq FROM tasks WHERE id = 'tsk_two'").fetchone()[0])
                old._conn.execute("DELETE FROM tasks WHERE id = 'tsk_two'")
        finally:
            migrations.MIGRATIONS[:] = shipped
        with Store.open(path) as new:
            self.assertEqual(new.migrate(), LATEST_VERSION)
            fresh = new.create_task(title="three", created_by="codex-architect")
            self.assertGreater(int(fresh["seq"]), mark)

    def test_pragmas(self) -> None:
        pragmas = self.store.pragmas()
        self.assertEqual(pragmas["journal_mode"], "wal")
        self.assertEqual(pragmas["foreign_keys"], 1)
        self.assertEqual(pragmas["busy_timeout"], 5000)

    def test_newer_schema_is_refused(self) -> None:
        raw = sqlite3.connect(self.db)
        raw.execute(f"PRAGMA user_version = {LATEST_VERSION + 1}")
        raw.close()
        with self.assertRaises(StoreError):
            with Store.open(self.db) as newer:
                newer.migrate()

    def test_concurrent_migrate_on_a_fresh_database_poisons_no_connection(self) -> None:
        # Review finding: the loser of the migration race used to be left
        # inside a failed transaction and every later call on it broke.
        fresh = str(Path(self._tmp.name) / "fresh.sqlite3")
        gate = threading.Barrier(4)
        errors: list[BaseException] = []
        usable: list[bool] = []

        def opener() -> None:
            try:
                store = Store.open(fresh)
                gate.wait(timeout=10)
                store.migrate()
                store.register_agent("probe", provider="other", role="probe")  # connection must still work
                usable.append(True)
                store.close()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=opener) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(usable, [True] * 4)
        with Store.open(fresh) as check:
            self.assertEqual(check.schema_version(), LATEST_VERSION)

    def test_concurrent_open_on_a_fresh_database_switches_to_wal(self) -> None:
        # Review finding: the first WAL switch bypasses the busy handler and
        # could fail with "database is locked" under concurrent opens.
        for trial in range(10):
            fresh = str(Path(self._tmp.name) / f"open-{trial}.sqlite3")
            gate = threading.Barrier(4)
            errors: list[BaseException] = []

            def opener() -> None:
                try:
                    gate.wait(timeout=10)
                    with Store.open(fresh) as store:
                        self.assertEqual(store.pragmas()["journal_mode"], "wal")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=opener) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            self.assertEqual(errors, [], f"trial {trial}")

    def test_reserved_structures_exist_without_rows(self) -> None:
        counts = self.store.counts()
        self.assertEqual(counts["runs"], 0)
        self.assertEqual(counts["leases"], 0)
        columns = {r[1] for r in self.store._conn.execute("PRAGMA table_info(tasks)")}
        self.assertIn("depends_on", columns)
        columns = {r[1] for r in self.store._conn.execute("PRAGMA table_info(sessions)")}
        self.assertIn("generation", columns)


class AgentTests(StoreCase):
    def test_register_is_an_upsert_and_heartbeat_touches_last_seen(self) -> None:
        first = self.store.get_agent("claude-reviewer")
        again = self.store.register_agent("claude-reviewer", provider="claude", role="verifier")
        self.assertEqual(again["role"], "verifier")
        self.assertEqual(len(self.store.list_agents()), 2)
        beat = self.store.heartbeat("claude-reviewer")
        self.assertGreaterEqual(beat["last_seen_at"], first["last_seen_at"])
        with self.assertRaises(NotFound):
            self.store.heartbeat("nobody")

    def test_validation(self) -> None:
        with self.assertRaises(ValidationError):
            self.store.register_agent("bad id", provider="codex", role="x")
        with self.assertRaises(ValidationError):
            self.store.register_agent("worker\n", provider="codex", role="x")  # trailing newline
        with self.assertRaises(ValidationError):
            self.store.register_agent("ok", provider="codex", role="x", ttl_seconds=True)  # bool is not an int
        with self.assertRaises(ValidationError):
            self.store.register_agent("ok", provider="codex", role="x", capabilities="review")  # str is not a list
        # Review finding: peers are untrusted and status output reaches a terminal.
        with self.assertRaises(ValidationError):
            self.store.register_agent("ok", provider="codex", role="r\x1b]0;pwned\x07")
        with self.assertRaises(ValidationError):
            self.store.register_agent("ok", provider="codex", role="r", capabilities=["a\x00b"])
        with self.assertRaises(ValidationError):
            self.store.create_task(title="t\r\x1b[2Knext: rm -rf ~", created_by="codex-architect")
        with self.assertRaises(ValidationError):
            self.store.publish_artifact(kind="report", ref="x\x7f", produced_by="claude-reviewer")
        with self.assertRaises(ValidationError):
            self.store.register_agent("ok", provider="gpt", role="x")
        with self.assertRaises(ValidationError):
            self.store.register_agent("ok", provider="codex", role="x", ttl_seconds=0)


class MessageTests(StoreCase):
    def test_send_creates_message_delivery_and_event_together(self) -> None:
        before = self.store.counts()
        message = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"review": "src/x.py"})
        after = self.store.counts()
        self.assertEqual(after["messages"], before["messages"] + 1)
        self.assertEqual(after["deliveries"], before["deliveries"] + 1)
        self.assertEqual(after["events"], before["events"] + 1)
        self.assertEqual(message["correlation_id"], message["id"])
        inbox = self.store.inbox("claude-reviewer")
        self.assertEqual([i["message_id"] for i in inbox["items"]], [message["id"]])
        self.assertEqual(inbox["items"][0]["delivery_state"], "queued")
        self.assertEqual(self.store.inbox("codex-architect")["items"], [])

    def test_unknown_agents_and_bad_input_are_rejected(self) -> None:
        with self.assertRaises(NotFound):
            self.store.send_message(sender="codex-architect", recipient="ghost", kind="task", payload={})
        with self.assertRaises(ValidationError):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="gossip", payload={})
        with self.assertRaises(ValidationError):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"big": "x" * 70000})
        with self.assertRaises(NotFound):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={}, reply_to="msg_missing")
        with self.assertRaises(ValidationError):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"x": float("nan")})
        with self.assertRaises(ValidationError):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"x": {1, 2}})
        with self.assertRaises(TypeError):
            # M5: hop_count is measured by the daemon, never accepted from the
            # sender -- a sender that set its own could reset a loop forever.
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={}, hop_count=0)
        with self.assertRaises(ValidationError):
            self.store.inbox("claude-reviewer", limit=0)
        with self.assertRaises(ValidationError):
            self.store.events(limit=-1)
        with self.assertRaises(ValidationError):
            self.store.events(after="x")  # type: ignore[arg-type]

    def test_inbox_pagination_is_stable(self) -> None:
        ids = [self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="finding", payload={"n": n})["id"] for n in range(5)]
        page1 = self.store.inbox("claude-reviewer", limit=2)
        self.assertTrue(page1["has_more"])
        page2 = self.store.inbox("claude-reviewer", limit=2, after=page1["next_after"])
        page3 = self.store.inbox("claude-reviewer", limit=2, after=page2["next_after"])
        seen = [i["message_id"] for p in (page1, page2, page3) for i in p["items"]]
        self.assertEqual(seen, ids)
        self.assertFalse(page3["has_more"])

    def test_delivery_transitions_are_guarded(self) -> None:
        message = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="question", payload={})
        delivery_id = self.store.inbox("claude-reviewer")["items"][0]["delivery_id"]
        with self.assertRaises(ConflictError):
            self.store.ack_delivery(delivery_id, "codex-architect")  # not the recipient
        with self.assertRaises(ConflictError):
            self.store.complete_delivery(delivery_id, "claude-reviewer")  # not acknowledged yet
        acked = self.store.ack_delivery(delivery_id, "claude-reviewer")
        self.assertEqual(acked["state"], "acknowledged")
        with self.assertRaises(ConflictError):
            self.store.ack_delivery(delivery_id, "claude-reviewer")  # second ack
        done = self.store.complete_delivery(delivery_id, "claude-reviewer")
        self.assertEqual(done["state"], "completed")
        self.assertEqual(self.store.inbox("claude-reviewer")["items"], [])
        self.assertEqual(self.store.get_message(message["id"])["kind"], "question")
        kinds = [e["kind"] for e in self.store.events()]
        self.assertEqual(kinds[-3:], ["message.sent", "delivery.acknowledged", "delivery.completed"])

    def test_messages_are_immutable(self) -> None:
        message = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="finding", payload={"a": 1})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._conn.execute("UPDATE messages SET payload = '{}' WHERE id = ?", (message["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._conn.execute("DELETE FROM messages WHERE id = ?", (message["id"],))


class IdempotencyTests(StoreCase):
    def test_replayed_send_returns_the_same_message_and_creates_nothing(self) -> None:
        kwargs = dict(sender="codex-architect", recipient="claude-reviewer", kind="result", payload={"r": 1}, idempotency_key="send-1")
        first = self.store.send_message(**kwargs)
        before = self.store.counts()
        second = self.store.send_message(**kwargs)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.store.counts(), before)

    def test_same_key_different_request_conflicts(self) -> None:
        self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="result", payload={"r": 1}, idempotency_key="k")
        with self.assertRaises(IdempotencyConflict):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="result", payload={"r": 2}, idempotency_key="k")
        with self.assertRaises(IdempotencyConflict):
            self.store.create_task(title="t", created_by="codex-architect", idempotency_key="k")

    def test_keys_are_namespaced_per_actor(self) -> None:
        # Review finding: a global key namespace let one agent squat another's key.
        a = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="result", payload={"r": 1}, idempotency_key="shared")
        b = self.store.send_message(sender="claude-reviewer", recipient="codex-architect", kind="result", payload={"r": 2}, idempotency_key="shared")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.store.counts()["messages"], 2)

    def test_replayed_task_and_artifact(self) -> None:
        task = self.store.create_task(title="review", created_by="codex-architect", idempotency_key="task-1")
        again = self.store.create_task(title="review", created_by="codex-architect", idempotency_key="task-1")
        self.assertEqual(task["id"], again["id"])
        self.assertEqual(self.store.counts()["tasks"], 1)
        self.store.bind_worktree("claude-reviewer", make_repo(Path(self._tmp.name) / "repo"))  # M3: publishing needs a worktree
        art = self.store.publish_artifact(kind="report", ref="reports/x.md", produced_by="claude-reviewer", task_id=task["id"], idempotency_key="art-1")
        again = self.store.publish_artifact(kind="report", ref="reports/x.md", produced_by="claude-reviewer", task_id=task["id"], idempotency_key="art-1")
        self.assertEqual(art["id"], again["id"])
        self.assertEqual(self.store.counts()["artifacts"], 1)


class TaskTests(StoreCase):
    def test_claim_and_complete_lifecycle(self) -> None:
        task = self.store.create_task(title="review x", created_by="codex-architect", priority=5)
        self.assertEqual(task["state"], "open")
        claimed = self.store.claim_task(task["id"], "claude-reviewer")
        self.assertEqual((claimed["state"], claimed["assigned_agent_id"], claimed["version"]), ("claimed", "claude-reviewer", 2))
        with self.assertRaises(ConflictError):
            self.store.claim_task(task["id"], "codex-architect")
        with self.assertRaises(ConflictError):
            self.store.complete_task(task["id"], "codex-architect")  # not the holder
        done = self.store.complete_task(task["id"], "claude-reviewer", result={"finding": "none"}, outcome="completed")
        self.assertEqual((done["state"], done["result"], done["version"]), ("completed", {"finding": "none"}, 3))
        with self.assertRaises(ConflictError):
            self.store.complete_task(task["id"], "claude-reviewer")
        listing = self.store.list_tasks(state="completed")
        self.assertEqual([t["id"] for t in listing["items"]], [task["id"]])

    def test_preassigned_task_accepts_only_its_assignee(self) -> None:
        task = self.store.create_task(title="fix", created_by="codex-architect", assigned_to="claude-reviewer")
        with self.assertRaises(ConflictError):
            self.store.claim_task(task["id"], "codex-architect")
        self.assertEqual(self.store.claim_task(task["id"], "claude-reviewer")["state"], "claimed")

    def test_blocked_outcome(self) -> None:
        task = self.store.create_task(title="fix", created_by="codex-architect")
        self.store.claim_task(task["id"], "claude-reviewer")
        blocked = self.store.complete_task(task["id"], "claude-reviewer", result={"why": "needs approval"}, outcome="blocked")
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(self.store.events()[-1]["kind"], "task.blocked")

    def test_concurrent_claimers_produce_exactly_one_winner(self) -> None:
        task = self.store.create_task(title="contested", created_by="codex-architect")
        agents = [f"worker-{n}" for n in range(16)]
        for agent in agents:
            self.store.register_agent(agent, provider="other", role="worker")
        winners: list[str] = []
        losers: list[str] = []
        errors: list[BaseException] = []
        gate = threading.Barrier(len(agents))

        def attempt(agent: str) -> None:
            store = Store.open(self.db)
            try:
                gate.wait(timeout=10)
                store.claim_task(task["id"], agent)
                winners.append(agent)
            except ConflictError:
                losers.append(agent)
            except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
                errors.append(exc)
            finally:
                store.close()

        threads = [threading.Thread(target=attempt, args=(a,)) for a in agents]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(winners), 1, winners)
        self.assertEqual(len(losers), len(agents) - 1)
        final = self.store.get_task(task["id"])
        self.assertEqual((final["state"], final["assigned_agent_id"], final["version"]), ("claimed", winners[0], 2))
        self.assertEqual(sum(1 for e in self.store.events() if e["kind"] == "task.claimed"), 1)


class HistoryTests(StoreCase):
    def test_events_are_append_only(self) -> None:
        seq = self.store.events()[0]["seq"]
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._conn.execute("UPDATE events SET kind = 'forged' WHERE seq = ?", (seq,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._conn.execute("DELETE FROM events WHERE seq = ?", (seq,))

    def test_artifact_validation(self) -> None:
        with self.assertRaises(ValidationError):
            self.store.publish_artifact(kind="binary", ref="x", produced_by="claude-reviewer")
        with self.assertRaises(ValidationError):
            self.store.publish_artifact(kind="commit", ref="abc", produced_by="claude-reviewer", sha256="nothex")
        repo = make_repo(Path(self._tmp.name) / "repo")
        self.store.bind_worktree("claude-reviewer", repo)
        with self.assertRaises(NotFound):
            self.store.publish_artifact(kind="commit", ref=git(repo, "rev-parse", "HEAD"), produced_by="claude-reviewer", task_id="tsk_missing")


class CancellationTests(StoreCase):
    """M4: the human channel can cancel open or claimed work; the holder
    finds out through a conflict on its next transition."""

    def test_cancel_open_and_claimed_tasks(self) -> None:
        open_task = self.store.create_task(title="later", created_by="codex-architect")
        claimed = self.store.create_task(title="now", created_by="codex-architect")
        self.store.claim_task(claimed["id"], "claude-reviewer")
        self.assertEqual(self.store.cancel_task(open_task["id"], "human:test")["state"], "cancelled")
        record = self.store.cancel_task(claimed["id"], "human:test", reason="scope changed; password=hunter2hunter2")
        self.assertEqual(record["state"], "cancelled")
        self.assertEqual(record["assigned_agent_id"], "claude-reviewer")  # history kept
        self.assertEqual(record["result"], {"cancelled_by": "human:test", "reason": "scope changed; password=[redacted]"})
        with self.assertRaises(ConflictError):
            self.store.complete_task(claimed["id"], "claude-reviewer", result={"late": True})
        with self.assertRaises(ConflictError):
            self.store.claim_task(open_task["id"], "claude-reviewer")
        with self.assertRaises(ConflictError):
            self.store.cancel_task(claimed["id"], "human:test")  # already cancelled
        with self.assertRaises(NotFound):
            self.store.cancel_task("tsk_missing", "human:test")
        kinds = [e["kind"] for e in self.store.events(limit=100)]
        self.assertEqual(kinds.count("task.cancelled"), 2)
        self.assertEqual(self.store.status()["tasks"]["cancelled"], 2)

    def test_cancel_dead_letters_queued_task_messages_but_keeps_read_ones(self) -> None:
        # Review finding: a cancelled task left its queued task message
        # behind, so `bus status` kept asking for a turn nobody should start.
        task = self.store.create_task(title="doomed", created_by="codex-architect")
        other = self.store.create_task(title="alive", created_by="codex-architect")
        queued = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        unrelated = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": other["id"]})
        read = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        read_delivery = self.store.inbox("claude-reviewer")["items"][-1]["delivery_id"]
        self.store.ack_delivery(read_delivery, "claude-reviewer")
        self.store.cancel_task(task["id"], "human:test")
        states = {i["message_id"]: i["delivery_state"] for i in self.store.inbox("claude-reviewer", states=("queued", "acknowledged", "dead_letter"))["items"]}
        self.assertEqual(states[queued["id"]], "dead_letter")
        self.assertEqual(states[unrelated["id"]], "queued")
        self.assertEqual(states[read["id"]], "acknowledged")
        self.assertEqual(self.store.status()["queued_deliveries"], 1)  # only the unrelated task still asks for a turn
        event = next(e for e in self.store.events(limit=100) if e["kind"] == "task.cancelled")
        self.assertEqual(len(event["payload"]["dead_lettered"]), 1)
        self.assertEqual(self.store.complete_delivery(read_delivery, "claude-reviewer")["state"], "completed")

    def test_completed_tasks_cannot_be_cancelled(self) -> None:
        task = self.store.create_task(title="done", created_by="codex-architect")
        self.store.claim_task(task["id"], "claude-reviewer")
        self.store.complete_task(task["id"], "claude-reviewer")
        with self.assertRaises(ConflictError):
            self.store.cancel_task(task["id"], "human:test")


if __name__ == "__main__":
    unittest.main()

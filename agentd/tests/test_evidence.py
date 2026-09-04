"""The evidence exporter, against a real store.

`scripts/agent_bus_evidence.py` is what turns the M4 decision gate's "record
set kept" from a promise into a file, so the things worth defending are that it
collects one conversation whole, leaves every other conversation out, and
cannot change the database it reads -- evidence a tool can rewrite is not
evidence.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_bus_evidence as evidence  # noqa: E402

from luciazero_agentd.store import Store  # noqa: E402

ARCHITECT, REVIEWER = "codex-architect", "claude-reviewer"


class EvidenceCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-evidence-")
        self.root = Path(self._tmp.name)
        self.store = Store.open(str(self.root / "bus.sqlite3"))
        self.store.migrate()
        self.store.trust = "bound"
        self.store.register_agent(ARCHITECT, provider="codex", role="architect")
        self.store.register_agent(REVIEWER, provider="claude", role="reviewer")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def conversation(self, title: str) -> tuple[str, str]:
        """One task and the message that carries it, answered once."""
        task = self.store.create_task(title=title, created_by=ARCHITECT, assigned_to=REVIEWER)
        opened = self.store.send_message(sender=ARCHITECT, recipient=REVIEWER, kind="task",
                                         payload={"task_id": task["id"]})
        delivery = self.store.inbox(REVIEWER, states=("queued",))["items"][-1]
        self.store.ack_delivery(delivery["delivery_id"], REVIEWER)
        self.store.claim_task(task["id"], REVIEWER)
        self.store.complete_task(task["id"], REVIEWER)
        self.store.send_message(sender=REVIEWER, recipient=ARCHITECT, kind="result",
                                payload={"task_id": task["id"]}, reply_to=opened["id"])
        return str(opened["correlation_id"] or opened["id"]), str(task["id"])

    def connect(self) -> sqlite3.Connection:
        return evidence.connect(self.root)


class ExportTests(EvidenceCase):
    def test_one_conversation_comes_out_whole(self) -> None:
        correlation, task_id = self.conversation("the workflow being recorded")
        with self.connect() as conn:
            record = evidence.record_set(conn, correlation)
        self.assertEqual([m["correlation_id"] for m in record["messages"]], [correlation, correlation])
        self.assertEqual([t["id"] for t in record["tasks"]], [task_id])
        self.assertEqual(sorted(record["agents"]), [REVIEWER, ARCHITECT])
        self.assertEqual(len(record["deliveries"]), 2)
        self.assertTrue(record["events"], "the events that mention these records belong to the evidence")
        self.assertTrue(all(e["entity_id"] in
                            {m["id"] for m in record["messages"]}
                            | {d["id"] for d in record["deliveries"]}
                            | {task_id}
                            for e in record["events"]))

    def test_another_conversation_is_not_swept_in(self) -> None:
        wanted, wanted_task = self.conversation("the one being recorded")
        other, other_task = self.conversation("somebody else's work")
        self.assertNotEqual(wanted, other)
        with self.connect() as conn:
            record = evidence.record_set(conn, wanted)
        self.assertEqual([t["id"] for t in record["tasks"]], [wanted_task])
        self.assertNotIn(other_task, [t["id"] for t in record["tasks"]])
        self.assertTrue(all(m["correlation_id"] == wanted for m in record["messages"]))

    def test_a_conversation_that_does_not_exist_is_an_error_not_an_empty_file(self) -> None:
        self.conversation("something else entirely")
        with self.connect() as conn:
            with self.assertRaises(evidence.EvidenceError):
                evidence.record_set(conn, "msg_" + "0" * 32)

    def test_the_export_cannot_change_what_it_reads(self) -> None:
        """A tool that can rewrite the evidence is not a tool for evidence."""
        correlation, _ = self.conversation("read-only, and provably so")
        with self.connect() as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM messages")
            evidence.record_set(conn, correlation)
        self.assertEqual(len(self.store.inbox(ARCHITECT, states=("queued",))["items"]), 1)

    def test_a_missing_database_says_so(self) -> None:
        with self.assertRaises(evidence.EvidenceError):
            evidence.connect(self.root / "not-a-state-dir")


class LedgerTests(EvidenceCase):
    def test_the_summary_counts_what_the_gate_asks_about(self) -> None:
        correlation, _ = self.conversation("the workflow being recorded")
        with self.connect() as conn:
            summary = evidence.summarise(evidence.record_set(conn, correlation))
        self.assertEqual(summary["correlation_id"], correlation)
        self.assertEqual((summary["messages"], summary["tasks"]), (2, 1))
        self.assertEqual(summary["task_states"], ["completed"])
        # No run carried it, which is exactly what the decision gate is about:
        # in the pull beta the user started every turn by hand.
        self.assertEqual(summary["turns"], "user-started")
        self.assertEqual(summary["unverified_writes"], [])

    def test_an_unverified_write_is_named_in_the_summary(self) -> None:
        """M4.5's invariant survives the export: a write that was only
        asserted must not read as evidence of a bound session's work."""
        self.store.trust = "asserted"
        correlation, _ = self.conversation("recorded without a binding")
        with self.connect() as conn:
            summary = evidence.summarise(evidence.record_set(conn, correlation))
        self.assertTrue(summary["unverified_writes"])

    def test_the_wait_a_user_started_turn_cost_is_measured_not_remembered(self) -> None:
        """The gate's second criterion asks for the wait on a user-started turn.
        Nothing acknowledges a delivery until a human opens that agent's
        session, so the gap between the send and the acknowledgement is that
        cost -- and it is in the records rather than in somebody's memory."""
        correlation, task_id = self.conversation("the workflow being recorded")
        # A second delivery, acknowledged an hour after it was sent.
        opened = self.store.send_message(sender=ARCHITECT, recipient=REVIEWER, kind="finding",
                                         payload={"task_id": task_id}, correlation_id=correlation)
        delivery = self.store.inbox(REVIEWER, states=("queued",))["items"][-1]
        self.store.ack_delivery(delivery["delivery_id"], REVIEWER)
        later = datetime.fromisoformat(str(opened["created_at"])) + timedelta(hours=1)
        self.store._conn.execute("UPDATE deliveries SET acknowledged_at = ? WHERE id = ?",
                                 (later.isoformat(), delivery["delivery_id"]))
        self.store._conn.commit()
        with self.connect() as conn:
            summary = evidence.summarise(evidence.record_set(conn, correlation))
        self.assertEqual(summary["user_started_turns"], 2)
        self.assertAlmostEqual(float(summary["longest_wait_seconds"]), 3600, delta=5)
        self.assertIn("longest 60m", evidence.ledger_row(summary, label="w", path=None))

    def test_the_wait_is_split_at_the_recipients_first_bus_call(self) -> None:
        """A pull-beta turn has no `turn_started_at`, so the wait is two
        unlabelled things at once: nobody records the moment a person gave the
        session its turn. What the records can separate is the stretch with no
        call from that agent at all from the part it was demonstrably working,
        and the first half is a ceiling on the user-trigger delay rather than a
        measurement of it."""
        correlation, task_id = self.conversation("the workflow being recorded")
        opened = self.store.send_message(sender=ARCHITECT, recipient=REVIEWER, kind="finding",
                                         payload={"task_id": task_id}, correlation_id=correlation)
        delivery = self.store.inbox(REVIEWER, states=("queued",))["items"][-1]
        sent = datetime.fromisoformat(str(opened["created_at"]))
        conn = self.store._conn
        # Acknowledged an hour later, and the session's first call 50 minutes
        # in: written by hand because the point is the shape of a real turn,
        # which no test can wait an hour for. Events are append-only -- the
        # fixture adds one rather than rewriting the recipient's history.
        conn.execute("UPDATE deliveries SET state = 'acknowledged', acknowledged_by = ?, acknowledged_at = ? WHERE id = ?",
                     (REVIEWER, (sent + timedelta(hours=1)).isoformat(), delivery["delivery_id"]))
        conn.execute("INSERT INTO events (at, actor, kind, entity_type, entity_id, payload) "
                     "VALUES (?, ?, 'agent.registered', 'agent', ?, '{}')",
                     ((sent + timedelta(minutes=50)).isoformat(), REVIEWER, REVIEWER))
        conn.commit()
        with self.connect() as conn:
            summary = evidence.summarise(evidence.record_set(conn, correlation))
        wait = [w for w in summary["waits"] if w["delivery_id"] == delivery["delivery_id"]][0]
        self.assertAlmostEqual(wait["seconds"], 3600, delta=5)
        self.assertAlmostEqual(wait["silent_seconds"], 3000, delta=5)
        self.assertAlmostEqual(wait["agent_seconds"], 600, delta=5)
        self.assertAlmostEqual(float(summary["longest_silent_seconds"]), 3000, delta=5)
        self.assertIn("unattributed", evidence.ledger_row(summary, label="w", path=None))

    def test_a_wait_with_nothing_to_split_it_reports_no_split_rather_than_a_guess(self) -> None:
        correlation, _ = self.conversation("the workflow being recorded")
        with self.connect() as conn:
            summary = evidence.summarise(evidence.record_set(conn, correlation))
        # The halves always add up to the whole, and where the record is
        # missing the answer is "not known", never a made-up number.
        for wait in summary["waits"]:
            if wait["silent_seconds"] is None:
                self.assertIsNone(wait["agent_seconds"])
            else:
                self.assertAlmostEqual(wait["silent_seconds"] + wait["agent_seconds"], wait["seconds"], delta=0.01)
                self.assertGreaterEqual(wait["agent_seconds"], 0.0,
                                        "an acknowledgement that was the session's first call splits at itself")

    def test_a_delivery_nobody_opened_yet_is_not_a_measured_wait(self) -> None:
        correlation, _ = self.conversation("the workflow being recorded")
        self.store.send_message(sender=ARCHITECT, recipient=REVIEWER, kind="finding",
                                payload={}, correlation_id=correlation)
        with self.connect() as conn:
            summary = evidence.summarise(evidence.record_set(conn, correlation))
        # Three deliveries exist; only the one somebody opened a turn for has
        # a wait. The reply to the architect and the new finding are still owed.
        self.assertEqual((summary["deliveries"], summary["user_started_turns"]), (3, 1))

    def test_the_ledger_row_is_ready_to_paste(self) -> None:
        correlation, _ = self.conversation("the workflow being recorded")
        with self.connect() as conn:
            summary = evidence.summarise(evidence.record_set(conn, correlation))
        row = evidence.ledger_row(summary, label="a real workflow", path=Path("/tmp/evidence.json"))
        self.assertTrue(row.startswith("| a real workflow | `" + correlation + "` |"))
        self.assertEqual(row.count("|"), 8)
        self.assertIn("user-started", row)


if __name__ == "__main__":
    unittest.main()

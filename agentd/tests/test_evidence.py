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

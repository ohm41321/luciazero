"""Kill the process at every point around COMMIT for each pull-beta transition
and prove the store restarts either fully before or fully after it."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from luciazero_agentd import Store
from luciazero_agentd.crashsim import KILL_EXIT

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def run_child(db: str, op: str, point: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(PACKAGE_ROOT))
    return subprocess.run(
        [sys.executable, "-m", "luciazero_agentd.crashsim", db, op, point, *args],
        cwd=PACKAGE_ROOT, env=env, text=True, capture_output=True, timeout=60, check=False,
    )


class CrashCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-crash-")
        self.db = str(Path(self._tmp.name) / "bus.sqlite3")
        with Store.open(self.db) as store:
            store.migrate()
            store.register_agent("sender", provider="codex", role="architect")
            store.register_agent("worker", provider="claude", role="reviewer")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def reopen(self) -> Store:
        store = Store.open(self.db)
        self.assertEqual(store.migrate(), store.schema_version())  # restart never re-applies
        return store

    def assert_killed(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, KILL_EXIT, result.stderr)
        self.assertNotIn("completed-without-crash", result.stdout)

    def test_send_message_before_and_after_commit(self) -> None:
        with self.reopen() as store:
            before = store.counts()
        self.assert_killed(run_child(self.db, "send_message", "before_commit:send_message", "sender", "worker", "key-1"))
        with self.reopen() as store:
            self.assertEqual(store.counts(), before, "a crash before COMMIT must leave nothing behind")
        self.assert_killed(run_child(self.db, "send_message", "after_commit:send_message", "sender", "worker", "key-1"))
        with self.reopen() as store:
            after = store.counts()
            self.assertEqual(after["messages"], before["messages"] + 1)
            self.assertEqual(after["deliveries"], before["deliveries"] + 1)
            self.assertEqual(after["events"], before["events"] + 1)
            self.assertEqual(after["idempotency"], before["idempotency"] + 1)
            # replaying the same request after the crash creates nothing more
            replay = store.send_message(sender="sender", recipient="worker", kind="finding", payload={"crash": "after_commit:send_message"}, idempotency_key="key-1")
            self.assertEqual(store.counts(), after)
            self.assertEqual(store.inbox("worker")["items"][0]["message_id"], replay["id"])

    def test_delivery_ack_and_complete(self) -> None:
        with self.reopen() as store:
            store.send_message(sender="sender", recipient="worker", kind="task", payload={})
            delivery_id = store.inbox("worker")["items"][0]["delivery_id"]
            before = store.counts()
        self.assert_killed(run_child(self.db, "ack", "before_commit:delivery_acknowledged", delivery_id, "worker"))
        with self.reopen() as store:
            self.assertEqual(store.get_delivery(delivery_id)["state"], "queued")
            self.assertEqual(store.counts(), before)
        self.assert_killed(run_child(self.db, "ack", "after_commit:delivery_acknowledged", delivery_id, "worker"))
        with self.reopen() as store:
            self.assertEqual(store.get_delivery(delivery_id)["state"], "acknowledged")
            self.assertEqual(store.counts()["events"], before["events"] + 1)
            mid = store.counts()
        self.assert_killed(run_child(self.db, "complete_delivery", "before_commit:delivery_completed", delivery_id, "worker"))
        with self.reopen() as store:
            self.assertEqual(store.get_delivery(delivery_id)["state"], "acknowledged")
            self.assertEqual(store.counts(), mid)
        self.assert_killed(run_child(self.db, "complete_delivery", "after_commit:delivery_completed", delivery_id, "worker"))
        with self.reopen() as store:
            self.assertEqual(store.get_delivery(delivery_id)["state"], "completed")
            self.assertEqual(store.counts()["events"], mid["events"] + 1)
            self.assertEqual(store.inbox("worker")["items"], [])

    def test_task_create_claim_complete(self) -> None:
        with self.reopen() as store:
            before = store.counts()
        self.assert_killed(run_child(self.db, "create_task", "before_commit:create_task", "sender", "task-key"))
        with self.reopen() as store:
            self.assertEqual(store.counts(), before)
        self.assert_killed(run_child(self.db, "create_task", "after_commit:create_task", "sender", "task-key"))
        with self.reopen() as store:
            self.assertEqual(store.counts()["tasks"], before["tasks"] + 1)
            task = store.create_task(title="crash task", created_by="sender", idempotency_key="task-key")
            self.assertEqual(store.counts()["tasks"], before["tasks"] + 1, "replay after crash must not duplicate")
            task_id = task["id"]
            created = store.counts()
        self.assert_killed(run_child(self.db, "claim_task", "before_commit:claim_task", task_id, "worker"))
        with self.reopen() as store:
            self.assertEqual((store.get_task(task_id)["state"], store.get_task(task_id)["version"]), ("open", 1))
            self.assertEqual(store.counts(), created)
        self.assert_killed(run_child(self.db, "claim_task", "after_commit:claim_task", task_id, "worker"))
        with self.reopen() as store:
            t = store.get_task(task_id)
            self.assertEqual((t["state"], t["assigned_agent_id"], t["version"]), ("claimed", "worker", 2))
            claimed = store.counts()
        self.assert_killed(run_child(self.db, "complete_task", "before_commit:complete_task", task_id, "worker"))
        with self.reopen() as store:
            self.assertEqual(store.get_task(task_id)["state"], "claimed")
            self.assertEqual(store.counts(), claimed)
        self.assert_killed(run_child(self.db, "complete_task", "after_commit:complete_task", task_id, "worker"))
        with self.reopen() as store:
            t = store.get_task(task_id)
            self.assertEqual((t["state"], t["result"], t["version"]), ("completed", {"ok": True}, 3))
            self.assertEqual(store.counts()["events"], claimed["events"] + 1)

    def test_completion_and_unblocking_commit_together(self) -> None:
        """M5: a dependent opens inside the prerequisite's own transaction. A
        kill between the two would otherwise leave a task that is complete with
        something still waiting on it, and nothing would ever move it."""
        with self.reopen() as store:
            fix = store.create_task(title="fix", created_by="sender")
            verify = store.create_task(title="verify", created_by="sender", depends_on=[fix["id"]])
            store.claim_task(fix["id"], "worker")
            self.assertEqual(store.get_task(verify["id"])["state"], "waiting")
        self.assert_killed(run_child(self.db, "complete_task", "before_commit:complete_task", fix["id"], "worker"))
        with self.reopen() as store:
            self.assertEqual(store.get_task(fix["id"])["state"], "claimed")
            self.assertEqual(store.get_task(verify["id"])["state"], "waiting")
        self.assert_killed(run_child(self.db, "complete_task", "after_commit:complete_task", fix["id"], "worker"))
        with self.reopen() as store:
            self.assertEqual(store.get_task(fix["id"])["state"], "completed")
            self.assertEqual(store.get_task(verify["id"])["state"], "open")

    def test_child_without_crash_point_completes(self) -> None:
        result = run_child(self.db, "create_task", "never", "sender", "k")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("completed-without-crash", result.stdout)


if __name__ == "__main__":
    unittest.main()


class WorktreeAndApprovalCrashes(CrashCase):
    """M3 transitions are as atomic as the M1 ones."""

    def test_bind_worktree_before_and_after_commit(self) -> None:
        from tests.fixtures import make_repo

        repo = make_repo(Path(self._tmp.name) / "repo")
        self.assert_killed(run_child(self.db, "bind_worktree", "before_commit:bind_worktree", "worker", repo))
        with self.reopen() as store:
            self.assertEqual(store.counts()["worktrees"], 0)
        self.assert_killed(run_child(self.db, "bind_worktree", "after_commit:bind_worktree", "worker", repo))
        with self.reopen() as store:
            self.assertEqual(store.get_worktree("worker")["path"], repo)
            self.assertEqual(store.counts()["worktrees"], 1)

    def test_consume_approval_before_and_after_commit(self) -> None:
        from luciazero_agentd import ApprovalRefused

        with Store.open(self.db) as store:
            task = store.create_task(title="crash approval", created_by="sender")
            store.claim_task(task["id"], "worker")
            _, nonce = store.grant_approval(task["id"], "delete", granted_by="human:test")
        self.assert_killed(run_child(self.db, "consume_approval", "before_commit:consume_approval", task["id"], "delete", nonce, "worker"))
        with self.reopen() as store:
            self.assertEqual(len(store.pending_approvals()), 1)  # still unused after the crash
        self.assert_killed(run_child(self.db, "consume_approval", "after_commit:consume_approval", task["id"], "delete", nonce, "worker"))
        with self.reopen() as store:
            self.assertEqual(store.pending_approvals(), [])
            with self.assertRaises(ApprovalRefused):
                store.consume_approval(task["id"], "delete", nonce, "worker")

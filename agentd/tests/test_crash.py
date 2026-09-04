"""Kill the process at every point around COMMIT for each transition and prove
the store restarts either fully before or fully after it.

The pull-beta transitions came first (M1). The dispatch ones (M6) are the same
discipline applied to the state that spends money: a managed turn holds a live
credential and an attempt, so every commit point in dispatching, settling and
recovering a turn is killed here, and what has to survive is that the delivery
still reaches exactly one outcome, that the attempt is counted once, and that
no credential or lease outlives the dispatcher that minted it."""

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


class CrashFixture(unittest.TestCase):
    """A disposable store with the two agents every case needs."""

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


class CrashCase(CrashFixture):
    """The pull-beta transitions (M1)."""

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


class DispatchCrashCase(CrashFixture):
    """One queued delivery for a managed worker, with the session, lease and
    managed binding a dispatcher would hold while running its turn."""

    def setUp(self) -> None:
        super().setUp()
        with self.reopen() as store:
            store.trust = "system"
            store.enrol_worker("worker", provider="other", command=["true"], max_attempts=2, by="human:test")
            store.send_message(sender="sender", recipient="worker", kind="task", payload={})
            delivery = store.inbox("worker", states=("queued",))["items"][-1]
            session = store.ensure_session("worker", provider="other")
            # The holder pid is dead from the start: this fixture is always the
            # dispatcher that did not come back.
            lease = store.acquire_lease("session", "worker", holder="dispatch:dead", session_id=str(session["id"]),
                                        holder_pid=424242, holder_started_at=None)
            binding, credential = store.bind_terminal("worker", provider="other", by="dispatch:dead", ownership="managed")
            self.delivery = str(delivery["delivery_id"])
            self.session = str(session["id"])
            self.lease = str(lease["id"])
            self.generation = str(lease["generation"])
            self.binding = str(binding["id"])
            self.credential = credential

    # helpers
    def begin_turn(self) -> str:
        """A turn in flight, committed: what a kill interrupts."""
        result = run_child(self.db, "begin_turn", "none", self.delivery, "worker",
                           self.lease, self.generation, self.session, self.binding)
        self.assertIn("completed-without-crash", result.stdout, result.stderr)
        with self.reopen() as store:
            return str(store.list_runs(limit=1)[0]["id"])

    def recover(self) -> None:
        result = run_child(self.db, "recover", "none")
        self.assertIn("completed-without-crash", result.stdout, result.stderr)

    def assert_one_outcome(self, *, attempts: int, delivery_state: str) -> None:
        """What must be true after any kill, once recovery has run: the turn is
        settled once, the attempt is counted once, and nothing the dispatcher
        held is still live."""
        with self.reopen() as store:
            delivery = store.get_delivery(self.delivery)
            self.assertEqual(delivery["state"], delivery_state)
            self.assertEqual(delivery["attempts"], attempts)
            self.assertEqual([r["state"] for r in store.list_runs(state="running", limit=10)], [])
            self.assertEqual(store.get_binding(self.binding)["state"], "revoked")
            self.assertIsNone(store.resolve_credential(self.credential),
                              "an orphaned provider's credential must not survive recovery")
            self.assertIsNone(store.lease_on("session", "worker"))

    def test_begin_turn_before_and_after_commit(self) -> None:
        """Counting the attempt and recording the run are one transaction, so a
        kill between them cannot strand the delivery with an attempt spent."""
        with self.reopen() as store:
            before = store.counts()
        self.assert_killed(run_child(self.db, "begin_turn", "before_commit:begin_turn", self.delivery, "worker",
                                     self.lease, self.generation, self.session, self.binding))
        with self.reopen() as store:
            self.assertEqual(store.counts()["runs"], before["runs"])
            self.assertEqual(store.get_delivery(self.delivery)["state"], "queued")
            self.assertEqual(store.get_delivery(self.delivery)["attempts"], 0)
        self.assert_killed(run_child(self.db, "begin_turn", "after_commit:begin_turn", self.delivery, "worker",
                                     self.lease, self.generation, self.session, self.binding))
        with self.reopen() as store:
            self.assertEqual(store.counts()["runs"], before["runs"] + 1)
            delivery = store.get_delivery(self.delivery)
            self.assertEqual((delivery["state"], delivery["attempts"]), ("processing", 1))
            self.assertEqual(store.list_runs(limit=1)[0]["state"], "running")

    def test_finish_run_before_and_after_commit(self) -> None:
        run = self.begin_turn()
        self.assert_killed(run_child(self.db, "finish_run", "before_commit:finish_run", run, "completed"))
        with self.reopen() as store:
            self.assertEqual(store.get_run(run)["state"], "running")
            self.assertEqual(store.get_delivery(self.delivery)["state"], "processing")
        self.assert_killed(run_child(self.db, "finish_run", "after_commit:finish_run", run, "completed"))
        with self.reopen() as store:
            # The worker never touched the delivery, so a clean provider exit is
            # still a failed attempt -- and the settlement is one transaction.
            self.assertEqual(store.get_run(run)["state"], "failed")
            self.assertEqual(store.get_delivery(self.delivery)["state"], "retryable_failed")

    def test_recovery_finishes_from_any_point_it_was_killed_at(self) -> None:
        """The matrix. Recovery is three transactions -- release the lease,
        revoke the credential, settle the run -- so a kill lands between two of
        them; the next dispatcher must finish the job rather than inherit a
        half-recovered turn."""
        for point in ("before_commit:release_lease", "after_commit:release_lease",
                      "before_commit:revoke_binding", "after_commit:revoke_binding",
                      "before_commit:finish_run", "after_commit:finish_run"):
            with self.subTest(point=point):
                self._tmp.cleanup()  # the previous point's store; tearDown takes the last
                self.setUp()  # a fresh turn in flight for each point
                self.begin_turn()
                self.assert_killed(run_child(self.db, "recover", point))
                self.recover()
                self.assert_one_outcome(attempts=1, delivery_state="retryable_failed")
                # Running it again changes nothing: recovery is idempotent.
                self.recover()
                self.assert_one_outcome(attempts=1, delivery_state="retryable_failed")

    def test_a_crash_costs_one_attempt_and_the_limit_still_holds(self) -> None:
        """Two attempts is what the worker was enrolled with. A dispatcher
        killed mid-turn must not make that three, or make it one."""
        self.begin_turn()
        self.assert_killed(run_child(self.db, "recover", "before_commit:finish_run"))
        self.recover()
        self.assert_one_outcome(attempts=1, delivery_state="retryable_failed")
        with self.reopen() as store:
            store.trust = "system"
            session = store.ensure_session("worker", provider="other")
            lease = store.acquire_lease("session", "worker", holder="dispatch:second", session_id=str(session["id"]),
                                        holder_pid=424242, holder_started_at=None)
            binding, credential = store.bind_terminal("worker", provider="other", by="dispatch:second", ownership="managed")
            self.lease, self.generation = str(lease["id"]), str(lease["generation"])
            self.session, self.binding, self.credential = str(session["id"]), str(binding["id"]), credential
        self.begin_turn()
        self.assert_killed(run_child(self.db, "recover", "after_commit:revoke_binding"))
        self.recover()
        # The second attempt was the last one: the delivery is out of tries.
        self.assert_one_outcome(attempts=2, delivery_state="dead_letter")

    def test_the_runs_own_bookkeeping_before_and_after_commit(self) -> None:
        """The provider process and the session it ran in: what recovery needs
        to know to stop the orphan and to resume the next turn."""
        run = self.begin_turn()
        self.assert_killed(run_child(self.db, "record_run_process", "before_commit:record_run_process", run, "4242"))
        with self.reopen() as store:
            self.assertIsNone(store.get_run(run)["provider_pid"])
        self.assert_killed(run_child(self.db, "record_run_process", "after_commit:record_run_process", run, "4242"))
        with self.reopen() as store:
            self.assertEqual(store.get_run(run)["provider_pid"], 4242)
        self.assert_killed(run_child(self.db, "record_provider_session", "before_commit:record_provider_session",
                                     self.session, "thread-9", self.generation))
        with self.reopen() as store:
            self.assertIsNone(store.get_session(self.session)["provider_session_id"])
        self.assert_killed(run_child(self.db, "record_provider_session", "after_commit:record_provider_session",
                                     self.session, "thread-9", self.generation))
        with self.reopen() as store:
            self.assertEqual(store.get_session(self.session)["provider_session_id"], "thread-9")

    def test_leases_and_dead_letters_before_and_after_commit(self) -> None:
        with self.reopen() as store:
            store.trust = "system"
            store.release_lease(self.lease, by="human:test", reason="making room for the crash")
        self.assert_killed(run_child(self.db, "acquire_lease", "before_commit:acquire_lease", "worker", self.session))
        with self.reopen() as store:
            self.assertIsNone(store.lease_on("session", "worker"))
        self.assert_killed(run_child(self.db, "acquire_lease", "after_commit:acquire_lease", "worker", self.session))
        with self.reopen() as store:
            held = store.lease_on("session", "worker")
            self.assertIsNotNone(held)
            self.assert_killed(run_child(self.db, "release_lease", "before_commit:release_lease", str(held["id"])))
        with self.reopen() as store:
            self.assertIsNotNone(store.lease_on("session", "worker"))
        self.assert_killed(run_child(self.db, "dead_letter_delivery", "before_commit:dead_letter_delivery",
                                     self.delivery, "the task is already done"))
        with self.reopen() as store:
            self.assertEqual(store.get_delivery(self.delivery)["state"], "queued")
        self.assert_killed(run_child(self.db, "dead_letter_delivery", "after_commit:dead_letter_delivery",
                                     self.delivery, "the task is already done"))
        with self.reopen() as store:
            self.assertEqual(store.get_delivery(self.delivery)["state"], "dead_letter")

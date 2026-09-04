"""M6 dispatch contract: leases, generation fencing, attempts, and what the
dispatcher is not allowed to do.

The rules being defended (ADR 0006):

* one lease per session, and taking it fences whatever held it, so two
  dispatchers cannot resume one provider session;
* a lease dies when it expires *or* when the process holding it is gone, which
  is what makes a killed dispatcher recoverable in seconds;
* the dispatcher never acknowledges or completes a worker's delivery: a turn
  that did nothing is a failed attempt however cleanly the provider exited;
* a human-owned terminal is never taken over;
* work that is moot -- a task finished, cancelled, or stopped on a budget --
  is dead-lettered, never started;
* a run log is bounded and redacted before it is written.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import time
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from luciazero_agentd import procinfo
from luciazero_agentd import ConflictError, NotFound, Store, ValidationError
from luciazero_agentd.adapters import ProcessAdapter, TurnRequest
from luciazero_agentd.dispatcher import DispatchError, Dispatcher
from luciazero_agentd.runlog import RunLog
from luciazero_agentd.statedir import pid_alive as _pid_alive
from luciazero_agentd.statedir import write_endpoint
from luciazero_agentd.__main__ import main
from luciazero_agentd.store import (
    LEASE_TTL_SECONDS,
    GenerationFenced,
    MootWork,
    UnsafeReference,
    _plus_seconds,
    utcnow,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _running(pid: int) -> bool:
    """Is this pid still around? Polled, because a signal is not instant."""
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        time.sleep(0.05)
    return True


def _reap_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _reap(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)

DEAD = lambda pid, started_at=None: False  # noqa: E731 - a process that is gone
LIVE = lambda pid, started_at=None: True  # noqa: E731


class DispatchCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-dispatch-")
        self.root = Path(self._tmp.name)
        self.store = Store.open(str(self.root / "bus.sqlite3"))
        self.store.migrate()
        self.store.trust = "system"
        self.store.register_agent("codex-architect", provider="codex", role="architect")
        self.store.register_agent("claude-reviewer", provider="claude", role="reviewer")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    # helpers
    def worker(self, agent_id: str = "claude-reviewer", **kwargs: object) -> dict:
        options = {"provider": "other", "command": ["true"], "by": "human:test"}
        options.update(kwargs)
        return self.store.enrol_worker(agent_id, **options)  # type: ignore[arg-type]

    def queued(self, *, task_id: str | None = None, recipient: str = "claude-reviewer") -> dict:
        payload = {"task_id": task_id} if task_id else {}
        message = self.store.send_message(sender="codex-architect", recipient=recipient, kind="task", payload=payload)
        return self.store.inbox(recipient, states=("queued",))["items"][-1]

    def session_and_lease(self, agent_id: str = "claude-reviewer", **kwargs: object) -> tuple[dict, dict]:
        session = self.store.ensure_session(agent_id, provider="other")
        lease = self.store.acquire_lease("session", agent_id, holder="dispatch:test", session_id=session["id"], **kwargs)  # type: ignore[arg-type]
        return session, lease


class LeaseTests(DispatchCase):
    def test_one_holder_at_a_time_and_taking_it_bumps_the_generation(self) -> None:
        session, first = self.session_and_lease()
        self.assertEqual(first["generation"], 1)
        with self.assertRaises(ConflictError) as caught:
            self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:other", session_id=session["id"])
        self.assertIn("held by", str(caught.exception))
        self.store.release_lease(first["id"], by="dispatch:test")
        second = self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:other", session_id=session["id"])
        self.assertEqual(second["generation"], 2)

    def test_a_lease_whose_holder_is_gone_is_reclaimed_without_waiting_out_its_ttl(self) -> None:
        session, first = self.session_and_lease(holder_pid=424242, holder_started_at="2026-09-04T00:00:00.000000+00:00")
        self.assertGreater(first["expires_at"], utcnow())  # still inside its TTL
        second = self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:new",
                                          session_id=session["id"], alive=DEAD)
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual([e["payload"]["reason"] for e in self.store.events(limit=200) if e["kind"] == "lease.reclaimed"], ["holder gone"])

    def test_an_expired_lease_is_reclaimed(self) -> None:
        session, first = self.session_and_lease()
        self.store._conn.execute("UPDATE leases SET expires_at = ? WHERE id = ?", (_plus_seconds(utcnow(), -60), first["id"]))
        second = self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:new", session_id=session["id"])
        self.assertEqual(second["generation"], 2)

    def test_renewal_stops_when_the_owned_process_is_gone(self) -> None:
        _, lease = self.session_and_lease()
        renewed = self.store.renew_lease(lease["id"], pid=4242, alive=LIVE)
        self.assertGreater(renewed["expires_at"], lease["expires_at"])
        with self.assertRaises(ConflictError):
            self.store.renew_lease(lease["id"], pid=4242, alive=DEAD)
        self.assertIsNone(self.store.lease_on("session", "claude-reviewer"))

    def test_a_stale_generation_is_fenced_out_of_every_write(self) -> None:
        session, first = self.session_and_lease()
        delivery = self.queued()
        self.worker()
        self.store.release_lease(first["id"], by="dispatch:test")
        self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:new", session_id=session["id"])
        with self.assertRaises(GenerationFenced):
            self.store.dispatch_delivery(delivery["delivery_id"], agent_id="claude-reviewer",
                                         lease_id=first["id"], generation=first["generation"], session_id=session["id"])
        with self.assertRaises(GenerationFenced):
            self.store.record_provider_session(session["id"], provider_session_id="thread-1", generation=first["generation"])


class WorkerTests(DispatchCase):
    def test_enrolment_is_an_upsert_and_validates_the_command(self) -> None:
        worker = self.worker(command=["python3", "-c", "pass"], max_attempts=2)
        self.assertEqual(worker["command"], ["python3", "-c", "pass"])
        self.assertEqual(worker["max_attempts"], 2)
        again = self.worker(command=["true"], max_attempts=5)
        self.assertEqual(again["command"], ["true"])
        self.assertEqual(again["max_attempts"], 5)
        with self.assertRaises(ValidationError):
            self.worker(command=[])
        with self.assertRaises(ValidationError):
            self.worker(max_attempts=0)
        with self.assertRaises(NotFound):
            self.worker("nobody")

    def test_a_command_may_not_carry_the_flags_the_dispatcher_sets(self) -> None:
        """A worker enrolled `--approve deny` whose command carried
        `--dangerously-skip-permissions` would have run with no permission check
        at all: both CLIs let the command's own flags win or accumulate, and our
        flags are appended, not merged. The enrolment is refused instead, so the
        policy the human chose is the policy the turn runs under."""
        for command in (["claude", "--dangerously-skip-permissions"],
                        ["claude", "--allowedTools", "Bash"],
                        ["claude", "--permission-mode=bypassPermissions"],
                        ["claude", "--mcp-config", "/tmp/other.json"]):
            with self.assertRaises(ValidationError, msg=command):
                self.worker(provider="claude", command=command)
        for command in (["codex", "exec", "-c", "sandbox_mode=danger-full-access"],
                        ["codex", "--dangerously-bypass-approvals-and-sandbox"],
                        ["codex", "exec", "--full-auto"]):
            with self.assertRaises(ValidationError, msg=command):
                self.worker(provider="codex", command=command)
        kept = self.worker(provider="claude", command=["claude", "--model", "sonnet"])
        self.assertEqual(kept["command"], ["claude", "--model", "sonnet"])

    def test_a_command_carrying_a_secret_shape_is_refused(self) -> None:
        with self.assertRaises(UnsafeReference):
            self.worker(command=["claude", "--token", "lzsc_" + "a" * 32])

    def test_only_enabled_workers_are_dispatchable(self) -> None:
        self.worker()
        self.queued()
        self.assertEqual(len(self.store.dispatchable_deliveries()), 1)
        self.store.set_worker_enabled("claude-reviewer", False, by="human:test")
        self.assertEqual(self.store.dispatchable_deliveries(), [])
        self.store.set_worker_enabled("claude-reviewer", True, by="human:test")
        self.assertEqual(len(self.store.dispatchable_deliveries()), 1)
        self.store.remove_worker("claude-reviewer", by="human:test")
        self.assertEqual(self.store.dispatchable_deliveries(), [])

    def test_work_for_an_agent_that_is_not_a_worker_is_never_dispatched(self) -> None:
        self.queued(recipient="codex-architect")
        self.assertEqual(self.store.dispatchable_deliveries(), [])


class SettlementTests(DispatchCase):
    def setUp(self) -> None:
        super().setUp()
        self.worker(max_attempts=2)
        self.delivery = self.queued()
        self.session, self.lease = self.session_and_lease()

    def dispatch(self) -> dict:
        self.store.dispatch_delivery(self.delivery["delivery_id"], agent_id="claude-reviewer",
                                     lease_id=self.lease["id"], generation=self.lease["generation"],
                                     session_id=self.session["id"], max_attempts=2)
        return self.store.start_run(agent_id="claude-reviewer", delivery_id=self.delivery["delivery_id"],
                                    session_id=self.session["id"], lease_id=self.lease["id"],
                                    generation=self.lease["generation"])

    def test_a_turn_that_did_nothing_is_a_failed_attempt(self) -> None:
        run = self.dispatch()
        self.assertEqual(self.store.get_delivery(self.delivery["delivery_id"])["state"], "processing")
        finished = self.store.finish_run(run["id"], exit_state="exit 0")
        # The provider exited cleanly, but the worker never touched its inbox.
        self.assertEqual(finished["state"], "failed")
        self.assertEqual(finished["delivery_state"], "retryable_failed")

    def test_the_worker_moving_the_delivery_is_what_makes_a_run_complete(self) -> None:
        run = self.dispatch()
        self.store.ack_delivery(self.delivery["delivery_id"], "claude-reviewer")  # the worker's own call
        finished = self.store.finish_run(run["id"], exit_state="exit 0")
        self.assertEqual(finished["state"], "completed")
        self.assertEqual(self.store.get_delivery(self.delivery["delivery_id"])["state"], "acknowledged")

    def test_attempts_run_out_into_a_dead_letter(self) -> None:
        first = self.dispatch()
        self.store.finish_run(first["id"], exit_state="exit 1", error="provider failed")
        self.assertEqual(self.store.get_delivery(self.delivery["delivery_id"])["state"], "retryable_failed")
        self.assertEqual(len(self.store.dispatchable_deliveries()), 1)
        second = self.dispatch()
        finished = self.store.finish_run(second["id"], exit_state="exit 1", error="provider failed again")
        self.assertEqual(finished["delivery_state"], "dead_letter")
        self.assertEqual(self.store.dispatchable_deliveries(), [])

    def test_a_permanent_failure_spends_no_further_attempts(self) -> None:
        run = self.dispatch()
        finished = self.store.finish_run(run["id"], exit_state="spawn_failed", error="no such binary", permanent=True)
        self.assertEqual(finished["delivery_state"], "dead_letter")
        self.assertEqual(self.store.get_delivery(self.delivery["delivery_id"])["attempts"], 1)

    def test_moot_work_is_never_started(self) -> None:
        # Cancelling already dead-letters queued task messages (M4), so the
        # case a dispatcher meets is work somebody else finished first.
        task = self.store.create_task(title="finish me", created_by="codex-architect")
        delivery = self.queued(task_id=task["id"])
        self.store.claim_task(task["id"], "claude-reviewer")
        self.store.complete_task(task["id"], "claude-reviewer")
        listed = [d for d in self.store.dispatchable_deliveries(limit=10) if d["id"] == delivery["delivery_id"]]
        self.assertEqual([d["moot"] for d in listed], [f"task {task['id']} is completed"])
        with self.assertRaises(MootWork):
            self.store.dispatch_delivery(delivery["delivery_id"], agent_id="claude-reviewer",
                                         lease_id=self.lease["id"], generation=self.lease["generation"],
                                         session_id=self.session["id"])

    def test_counting_the_attempt_and_recording_the_run_are_one_transaction(self) -> None:
        """Review finding: as two calls, a kill between them left the delivery
        `dispatched` with no run -- invisible to recovery, which scans runs, and
        to dispatch, which scans queued work -- with an attempt already spent."""
        run = self.store.begin_turn(self.delivery["delivery_id"], agent_id="claude-reviewer",
                                    lease_id=self.lease["id"], generation=self.lease["generation"],
                                    session_id=self.session["id"], max_attempts=2)
        delivery = self.store.get_delivery(self.delivery["delivery_id"])
        self.assertEqual((delivery["state"], delivery["attempts"]), ("processing", 1))
        self.assertEqual(self.store.get_run(run["id"])["state"], "running")

    def test_a_delivery_left_mid_turn_with_no_run_is_recovered(self) -> None:
        """The belt to that braces: however a turn is lost, the delivery still
        reaches an outcome instead of sitting where nothing can see it."""
        self.store.dispatch_delivery(self.delivery["delivery_id"], agent_id="claude-reviewer",
                                     lease_id=self.lease["id"], generation=self.lease["generation"],
                                     session_id=self.session["id"], max_attempts=2)
        self.assertEqual(self.store.dispatchable_deliveries(), [])  # nothing can see it
        settled = self.store.recover_deliveries()
        self.assertEqual([d["id"] for d in settled], [self.delivery["delivery_id"]])
        self.assertEqual(self.store.get_delivery(self.delivery["delivery_id"])["state"], "retryable_failed")
        self.assertEqual(len(self.store.dispatchable_deliveries()), 1)
        self.assertEqual(self.store.recover_deliveries(), [])  # nothing is settled twice

    def test_a_stranded_delivery_out_of_attempts_dead_letters(self) -> None:
        for _ in range(2):
            self.store.dispatch_delivery(self.delivery["delivery_id"], agent_id="claude-reviewer",
                                         lease_id=self.lease["id"], generation=self.lease["generation"],
                                         session_id=self.session["id"], max_attempts=2)
            self.store.recover_deliveries()
        self.assertEqual(self.store.get_delivery(self.delivery["delivery_id"])["state"], "dead_letter")

    def test_a_run_that_lost_its_session_cannot_settle_the_delivery(self) -> None:
        """A turn whose lease was reclaimed must not settle work somebody else
        is now doing."""
        run = self.store.begin_turn(self.delivery["delivery_id"], agent_id="claude-reviewer",
                                    lease_id=self.lease["id"], generation=self.lease["generation"],
                                    session_id=self.session["id"], max_attempts=2)
        self.store._conn.execute("UPDATE leases SET holder_pid = 424242 WHERE id = ?", (self.lease["id"],))
        self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:new",
                                 session_id=self.session["id"], alive=DEAD)
        with self.assertRaises(GenerationFenced):
            self.store.finish_run(run["id"], exit_state="exit 0", fenced=True)
        self.assertEqual(self.store.get_run(run["id"])["state"], "running")

    def test_a_run_whose_dispatcher_is_gone_is_recovered_once(self) -> None:
        run = self.dispatch()
        self.store._conn.execute("UPDATE leases SET holder_pid = 424242 WHERE id = ?", (self.lease["id"],))
        recovered = self.store.recover_runs(alive=DEAD)
        self.assertEqual([r["id"] for r in recovered], [run["id"]])
        self.assertEqual(self.store.get_run(run["id"])["state"], "abandoned")
        self.assertEqual(self.store.get_delivery(self.delivery["delivery_id"])["state"], "retryable_failed")
        self.assertEqual(self.store.recover_runs(alive=DEAD), [])  # nothing is settled twice


class OwnershipTests(DispatchCase):
    def test_the_dispatcher_never_takes_over_a_human_terminal(self) -> None:
        self.store.bind_terminal("claude-reviewer", provider="claude", by="human:test", tty="ttys001")
        with self.assertRaises(ConflictError) as caught:
            self.store.bind_terminal("claude-reviewer", provider="claude", by="dispatch:1", ownership="managed")
        self.assertIn("the user owns", str(caught.exception))

    def test_a_managed_binding_replaces_only_another_managed_one(self) -> None:
        first, _ = self.store.bind_terminal("claude-reviewer", provider="claude", by="dispatch:1", ownership="managed")
        second, _ = self.store.bind_terminal("claude-reviewer", provider="claude", by="dispatch:2", ownership="managed")
        self.assertEqual(self.store.get_binding(first["id"])["state"], "revoked")
        self.assertEqual(self.store.get_binding(second["id"])["state"], "active")


class StatusTests(DispatchCase):
    def test_status_names_the_workers_and_the_turns_in_flight(self) -> None:
        """A managed worker is the one thing on this view the user did not
        start by hand, so it has to be visible."""
        self.worker(command=["true"])
        status = self.store.status()
        self.assertEqual([w["agent_id"] for w in status["workers"]], ["claude-reviewer"])
        self.assertEqual(status["running_runs"], [])
        delivery = self.queued()
        session, lease = self.session_and_lease()
        self.store.dispatch_delivery(delivery["delivery_id"], agent_id="claude-reviewer", lease_id=lease["id"],
                                     generation=lease["generation"], session_id=session["id"])
        run = self.store.start_run(agent_id="claude-reviewer", delivery_id=delivery["delivery_id"],
                                   session_id=session["id"], lease_id=lease["id"], generation=lease["generation"])
        self.assertEqual([r["id"] for r in self.store.status()["running_runs"]], [run["id"]])


class RunLogTests(DispatchCase):
    def test_a_run_log_is_capped_private_and_scrubbed(self) -> None:
        credential = "lzsc_" + "b" * 32
        path = self.root / "runs" / "r.log"
        log = RunLog(path, literals=(credential, "shared-token-value"), max_bytes=2048)
        log.write("head\n")
        log.write("x" * 5000)
        log.write(f"the credential is {credential} and the token is shared-token-value\n")
        ref = log.close()
        body = Path(ref).read_text(encoding="utf-8")
        self.assertLessEqual(len(body.encode("utf-8")), 2048 + len("... 99999 bytes dropped by the run-log cap ...\n"))
        self.assertNotIn(credential, body)
        self.assertNotIn("shared-token-value", body)
        self.assertIn("bytes dropped", body)
        self.assertEqual(oct(os.stat(ref).st_mode)[-3:], "600")


class WrappedSecretTests(DispatchCase):
    """Review finding: scrubbing each chunk as it arrived missed a secret a
    provider printed across two lines, because neither half matched alone."""

    def log(self, *, max_bytes: int = 4096) -> tuple[RunLog, str, str]:
        credential, token = "lzsc_" + "d" * 32, "shared-token-value"
        return RunLog(self.root / "runs" / "w.log", literals=(credential, token), max_bytes=max_bytes), credential, token

    def test_a_secret_split_across_two_writes_is_still_scrubbed(self) -> None:
        log, credential, token = self.log()
        log.write("the credential is " + credential[:12])
        log.write(credential[12:] + " and the token is " + token[:6])
        log.write(token[6:] + " done\n")
        body = Path(log.close()).read_text(encoding="utf-8")
        self.assertNotIn(credential, "".join(body.split()))
        self.assertNotIn(token, body)
        self.assertIn("[redacted]", body)

    def test_a_secret_a_provider_wrapped_across_lines_is_still_scrubbed(self) -> None:
        log, credential, _ = self.log()
        log.write("token=" + credential[:20] + "\n" + credential[20:] + "\n")
        body = Path(log.close()).read_text(encoding="utf-8")
        self.assertNotIn(credential, "".join(body.split()))

    def test_the_cap_drops_a_margin_so_a_split_secret_loses_a_half(self) -> None:
        log, credential, _ = self.log(max_bytes=2048)
        log.write("head " + credential[:16])
        log.write("x" * 6000)
        log.write(credential[16:] + " tail\n")
        body = Path(log.close()).read_text(encoding="utf-8")
        self.assertNotIn(credential[:16], body)
        self.assertIn("bytes dropped", body)


class ProcessAdapterTests(DispatchCase):
    def request(self, command: tuple[str, ...], *, timeout: int = 30) -> TurnRequest:
        # The adapter writes into the log; closing it is the dispatcher's job,
        # so the test does what the dispatcher would.
        self.log = RunLog(self.root / "runs" / "a.log", literals=("lzsc_" + "c" * 32,))
        return TurnRequest(
            agent_id="claude-reviewer", provider="other", command=command, cwd=str(self.root),
            prompt="do the work", credential="lzsc_" + "c" * 32, url="http://127.0.0.1:1/mcp",
            timeout_seconds=timeout, log=self.log,
        )

    def logged(self) -> str:
        return Path(self.log.close()).read_text(encoding="utf-8")

    def test_a_clean_exit_is_a_successful_turn_and_output_is_logged(self) -> None:
        result = ProcessAdapter().start(self.request((sys.executable, "-c", "print('hello from the worker')")))
        self.assertTrue(result.ok)
        self.assertEqual(result.exit_state, "exit 0")
        self.assertIn("hello from the worker", self.logged())

    def test_a_non_zero_exit_is_retryable_and_a_missing_binary_is_not(self) -> None:
        failed = ProcessAdapter().start(self.request((sys.executable, "-c", "raise SystemExit(3)")))
        self.assertFalse(failed.ok)
        self.assertFalse(failed.permanent)
        missing = ProcessAdapter().start(self.request(("luciazero-no-such-provider",)))
        self.assertFalse(missing.ok)
        self.assertTrue(missing.permanent)
        self.assertEqual(missing.exit_state, "spawn_failed")

    def test_a_turn_that_runs_past_its_timeout_is_stopped(self) -> None:
        result = ProcessAdapter().start(self.request((sys.executable, "-c", "import time; time.sleep(30)"), timeout=1))
        self.assertFalse(result.ok)
        self.assertEqual(result.exit_state, "timeout")

    def test_the_credential_reaches_the_child_through_the_environment_only(self) -> None:
        script = "import os, sys; sys.stdout.write(os.environ['LUCIAZERO_AGENT_BUS_TOKEN'] + ' ' + ' '.join(sys.argv))"
        request = self.request((sys.executable, "-c", script))
        result = ProcessAdapter().start(request)
        self.assertTrue(result.ok)
        body = self.logged()
        # The log scrubs it, but the child received it: argv never carries it.
        self.assertNotIn("lzsc_", body.replace("[redacted]", ""))
        self.assertNotIn(request.credential, " ".join(request.command))


class TurnCapTests(DispatchCase):
    """`--max-turns` is the quota budget: turns are what cost money, and
    "keep going until somebody notices" is not a budget."""

    def setUp(self) -> None:
        super().setUp()
        write_endpoint(self.root, "http://127.0.0.1:9/mcp", os.getpid(), utcnow())
        (self.root / "token").write_text("shared-token-value", encoding="utf-8")

    def dispatch(self, *argv: str) -> tuple[int, str]:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = main(["dispatch", "--state-dir", str(self.root), "--interval", "0", *argv])
        return code, err.getvalue()

    def test_the_cap_stops_the_run_at_the_turn_it_names(self) -> None:
        self.worker(command=[sys.executable, "-c", "raise SystemExit(3)"], max_attempts=9)
        self.queued()
        code, err = self.dispatch("--max-turns", "2")
        self.assertEqual(code, 0)
        self.assertIn("2-turn cap", err)
        self.assertEqual(len(self.store.list_runs(agent_id="claude-reviewer")), 2)

    def test_watching_can_be_told_to_stop_when_the_work_runs_out(self) -> None:
        """Without this a `--watch` that has finished everything waits for
        more forever, which is the wrong end of a conversation that is over."""
        self.worker(command=[sys.executable, "-c", "raise SystemExit(3)"], max_attempts=1)
        self.queued()
        code, _ = self.dispatch("--watch", "--stop-when-idle")
        self.assertEqual(code, 0)
        # One attempt, dead-lettered, and then nothing left to do.
        self.assertEqual(len(self.store.list_runs(agent_id="claude-reviewer")), 1)

    def test_without_a_cap_one_pass_is_still_one_pass(self) -> None:
        self.worker(command=[sys.executable, "-c", "raise SystemExit(3)"], max_attempts=9)
        self.queued()
        self.assertEqual(self.dispatch("--once")[0], 0)
        self.assertEqual(len(self.store.list_runs(agent_id="claude-reviewer")), 1)


class DispatcherTests(DispatchCase):
    def setUp(self) -> None:
        super().setUp()
        write_endpoint(self.root, "http://127.0.0.1:9/mcp", os.getpid(), utcnow())
        (self.root / "token").write_text("shared-token-value", encoding="utf-8")

    def engine(self) -> Dispatcher:
        return Dispatcher(self.root, lease_ttl_seconds=60)

    def test_a_dispatcher_needs_a_running_daemon(self) -> None:
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        with self.assertRaises(DispatchError):
            Dispatcher(empty)

    def test_one_pass_runs_the_worker_and_records_the_attempt(self) -> None:
        self.worker(command=[sys.executable, "-c", "print('turn')"], max_attempts=2)
        delivery = self.queued()
        summaries = self.engine().tick()
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["outcome"], "failed")  # the worker never touched its inbox
        self.assertEqual(summaries[0]["delivery_state"], "retryable_failed")
        run = self.store.list_runs(agent_id="claude-reviewer")[0]
        self.assertEqual(run["attempt"], 1)
        self.assertTrue(Path(str(run["output_ref"])).exists())
        self.assertIn("turn", Path(str(run["output_ref"])).read_text(encoding="utf-8"))

    def test_the_turn_credential_does_not_outlive_the_turn(self) -> None:
        self.worker(command=[sys.executable, "-c", "print('turn')"])
        self.queued()
        self.engine().tick()
        self.assertEqual(self.store.list_bindings(states=("active",)), [])
        self.assertIsNone(self.store.lease_on("session", "claude-reviewer"))

    def test_moot_work_is_dead_lettered_without_starting_a_provider(self) -> None:
        task = self.store.create_task(title="already done", created_by="codex-architect")
        self.worker(command=["luciazero-no-such-provider"])
        delivery = self.queued(task_id=task["id"])
        self.store.claim_task(task["id"], "codex-architect")
        self.store.complete_task(task["id"], "codex-architect")
        summaries = self.engine().tick()
        self.assertEqual([s["outcome"] for s in summaries], ["dead_letter"])
        self.assertEqual(self.store.list_runs(), [])

    def test_a_provider_with_no_adapter_is_a_permanent_failure(self) -> None:
        """No test ever starts a real provider: this one asks for an adapter
        that does not exist, which is what a future provider looks like."""
        self.worker(provider="codex", command=["codex"])
        self.queued()

        def missing(provider: str):  # type: ignore[no-untyped-def]
            raise KeyError(provider)

        summaries = Dispatcher(self.root, adapters=missing).tick()
        self.assertEqual(summaries[0]["exit_state"], "no_adapter")
        self.assertEqual(summaries[0]["delivery_state"], "dead_letter")

    def test_failing_turns_spend_the_attempts_and_stop_at_the_dead_letter(self) -> None:
        """The adapter's failures have to walk the same limit a store-level
        failure does: retry, retry, dead letter, and then nothing."""
        self.worker(command=[sys.executable, "-c", "raise SystemExit(3)"], max_attempts=2)
        engine = self.engine()
        self.queued()
        self.assertEqual([s["delivery_state"] for s in engine.tick()], ["retryable_failed"])
        self.assertEqual([s["delivery_state"] for s in engine.tick()], ["dead_letter"])
        self.assertEqual(engine.tick(), [])
        self.assertEqual(len(self.store.list_runs()), 2)

    def test_a_task_that_runs_out_of_budget_mid_retry_is_never_started_again(self) -> None:
        """M5's stop outranks the attempts left: a task stopped between two
        attempts must not get the third."""
        task = self.store.create_task(title="expensive", created_by="codex-architect", budget={"tokens": 100})
        self.worker(command=[sys.executable, "-c", "raise SystemExit(3)"], max_attempts=3)
        self.queued(task_id=task["id"])
        engine = self.engine()
        self.assertEqual([s["delivery_state"] for s in engine.tick()], ["retryable_failed"])
        self.store.claim_task(task["id"], "claude-reviewer")
        self.store.record_usage(task["id"], "claude-reviewer", tokens=400)
        self.assertEqual(self.store.get_task(task["id"])["state"], "exhausted")
        summaries = engine.tick()
        self.assertEqual([s["outcome"] for s in summaries], ["dead_letter"])
        self.assertIn("exhausted", str(summaries[0]["reason"]))
        self.assertEqual(len(self.store.list_runs()), 1)  # no second provider was started

    def test_the_policy_a_turn_ran_under_is_recorded_on_the_run(self) -> None:
        """Re-enrolling the worker rewrites the worker row; an audit asking what
        governed a turn that already ended must not read the new answer."""
        self.worker(command=[sys.executable, "-c", "print('turn')"], approval_policy="workspace")
        self.queued()
        self.engine().tick()
        run = self.store.list_runs()[0]
        self.assertEqual(run["approval_policy"], "workspace")
        self.assertIn("under approval policy workspace", Path(str(run["output_ref"])).read_text(encoding="utf-8"))
        self.worker(command=[sys.executable, "-c", "print('turn')"], approval_policy="accept")
        self.assertEqual(self.store.get_run(str(run["id"]))["approval_policy"], "workspace")

    def test_the_sweep_removes_only_the_workspaces_its_own_turns_made(self) -> None:
        """The sweep deletes directories that carried a credential. It runs
        every pass, so what it may delete has to be exactly what this bus
        recorded a run for -- never a stranger's directory, and never through a
        symlink."""
        self.worker(command=[sys.executable, "-c", "print('turn')"])
        self.queued()
        engine = self.engine()
        engine.tick()
        run_id = str(self.store.list_runs()[0]["id"])
        stranger = engine.turn_dir / "not-a-run-id"
        stranger.mkdir(parents=True)
        (stranger / "keep").write_text("not ours", encoding="utf-8")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "precious").write_text("not ours either", encoding="utf-8")
        (engine.turn_dir / run_id).symlink_to(outside, target_is_directory=True)
        self.assertEqual(engine.sweep_workspaces(), [])
        self.assertTrue((outside / "precious").exists())
        self.assertTrue((stranger / "keep").exists())
        (engine.turn_dir / run_id).unlink()
        leftover = engine.turn_dir / run_id  # what a killed dispatcher leaves
        leftover.mkdir()
        (leftover / "mcp.json").write_text("{}", encoding="utf-8")
        self.assertEqual(engine.sweep_workspaces(), [run_id])
        self.assertFalse(leftover.exists())
        self.assertTrue((stranger / "keep").exists())

    def test_a_human_owned_agent_is_left_alone(self) -> None:
        self.worker(command=[sys.executable, "-c", "print('turn')"])
        delivery = self.queued()
        self.store.bind_terminal("claude-reviewer", provider="claude", by="human:test", tty="ttys002")
        summaries = self.engine().tick()
        self.assertEqual([s["outcome"] for s in summaries], ["human_owned"])
        self.assertEqual(self.store.list_runs(), [])
        self.assertEqual(self.store.get_delivery(delivery["delivery_id"])["state"], "queued")

    def test_a_second_dispatcher_finds_the_session_busy(self) -> None:
        self.worker(command=[sys.executable, "-c", "print('turn')"])
        self.queued()
        session = self.store.ensure_session("claude-reviewer", provider="other")
        self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:other",
                                 session_id=session["id"], holder_pid=os.getpid(), holder_started_at=None)
        summaries = self.engine().tick()
        self.assertEqual([s["outcome"] for s in summaries], ["busy"])
        self.assertEqual(self.store.list_runs(), [])

    def test_the_lease_outlasts_the_turn_it_covers(self) -> None:
        """Review finding: with a lease shorter than the turn, a second
        dispatcher could reclaim the session while the first provider ran."""
        self.worker(command=[sys.executable, "-c", "print('turn')"], turn_timeout_seconds=1800)
        self.queued()
        engine = Dispatcher(self.root, lease_ttl_seconds=60)
        acquired: list[dict] = []
        original = Store.acquire_lease

        def spy(self_store, *args, **kwargs):  # type: ignore[no-untyped-def]
            lease = original(self_store, *args, **kwargs)
            acquired.append({"ttl": kwargs.get("ttl_seconds")})
            return lease

        Store.acquire_lease = spy  # type: ignore[assignment]
        try:
            engine.tick()
        finally:
            Store.acquire_lease = original  # type: ignore[assignment]
        self.assertEqual([a["ttl"] for a in acquired], [1800 + 60])

    def test_a_turn_that_raises_still_settles_its_run(self) -> None:
        """An adapter bug must fail one delivery, not the dispatch loop."""
        self.worker(command=[sys.executable, "-c", "print('turn')"])
        delivery = self.queued()

        class Exploding:
            name = "boom"

            def start(self, request):  # type: ignore[no-untyped-def]
                raise RuntimeError("the adapter fell over")

            resume = start

            def cancel(self) -> None:
                return None

            def status(self) -> str:
                return "idle"

        engine = Dispatcher(self.root, adapters=lambda provider: Exploding())
        summaries = engine.tick()
        self.assertEqual([s["outcome"] for s in summaries], ["error"])
        self.assertEqual(self.store.list_runs()[0]["state"], "failed")
        self.assertEqual(self.store.get_delivery(delivery["delivery_id"])["state"], "retryable_failed")
        self.assertEqual(self.store.list_bindings(states=("active",)), [])

    def test_a_run_names_the_process_it_started(self) -> None:
        self.worker(command=[sys.executable, "-c", "print('turn')"])
        self.queued()
        self.engine().tick()
        run = self.store.list_runs(agent_id="claude-reviewer")[0]
        self.assertIsNotNone(run["provider_pid"])

    def test_recovery_revokes_the_credential_an_orphaned_provider_still_holds(self) -> None:
        """A killed dispatcher skips its own cleanup, so the child it started
        keeps a working credential until somebody takes it away."""
        self.worker(command=[sys.executable, "-c", "print('turn')"])
        delivery = self.queued()
        session = self.store.ensure_session("claude-reviewer", provider="other")
        lease = self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:dead",
                                         session_id=session["id"], holder_pid=424242, holder_started_at=None)
        binding, credential = self.store.bind_terminal("claude-reviewer", provider="other", by="dispatch:dead", ownership="managed")
        self.store.dispatch_delivery(delivery["delivery_id"], agent_id="claude-reviewer", lease_id=lease["id"],
                                     generation=lease["generation"], session_id=session["id"])
        run = self.store.start_run(agent_id="claude-reviewer", delivery_id=delivery["delivery_id"], session_id=session["id"],
                                   lease_id=lease["id"], generation=lease["generation"], binding_id=binding["id"])
        self.assertIsNotNone(self.store.resolve_credential(credential))
        Dispatcher(self.root, alive=DEAD).recover()
        self.assertEqual(self.store.get_binding(binding["id"])["state"], "revoked")
        self.assertIsNone(self.store.resolve_credential(credential))
        self.assertEqual(self.store.get_run(run["id"])["state"], "abandoned")

    def test_recovery_stops_the_children_an_orphaned_provider_started(self) -> None:
        """Review finding: recovery signalled the one pid it had recorded, which
        is exactly what `start_new_session=True` exists to make insufficient --
        the provider's own children kept running, and kept spending, after the
        dispatcher that started them was killed."""
        marker = self.root / "grandchild.pid"
        provider = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys, time\n"
             "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
             f"open({str(marker)!r}, 'w').write(str(kid.pid))\n"
             "time.sleep(120)\n"],
            start_new_session=True,
        )
        self.addCleanup(_reap, provider)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        grandchild = int(marker.read_text(encoding="utf-8"))
        self.addCleanup(_reap_pid, grandchild)

        self.worker(command=[sys.executable, "-c", "print('turn')"])
        delivery = self.queued()
        session = self.store.ensure_session("claude-reviewer", provider="other")
        lease = self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:dead",
                                         session_id=session["id"], holder_pid=424242, holder_started_at=None)
        binding, _credential = self.store.bind_terminal("claude-reviewer", provider="other", by="dispatch:dead", ownership="managed")
        self.store.dispatch_delivery(delivery["delivery_id"], agent_id="claude-reviewer", lease_id=lease["id"],
                                     generation=lease["generation"], session_id=session["id"])
        run = self.store.start_run(agent_id="claude-reviewer", delivery_id=delivery["delivery_id"], session_id=session["id"],
                                   lease_id=lease["id"], generation=lease["generation"], binding_id=binding["id"])
        self.store.record_run_process(str(run["id"]), pid=provider.pid, started_at=procinfo.started_at(provider.pid))

        # The dispatcher that held the lease is gone; the provider it started
        # is not, and neither is what the provider started.
        alive = lambda pid, started_at=None: pid != 424242 and procinfo.alive(pid, started_at)  # noqa: E731
        Dispatcher(self.root, alive=alive).recover()
        provider.wait(timeout=10)
        self.assertFalse(_running(grandchild), "the orphan's own child outlived recovery")

    def test_a_sigterm_leaves_no_live_credential_and_no_running_provider(self) -> None:
        """Review finding: `run` installs a SIGTERM handler for exactly this
        reason and `dispatch` did not, so `kill <pid>` left the turn's
        credential live and its provider orphaned."""
        self.worker(command=[sys.executable, "-c", "import time; time.sleep(120)"], turn_timeout_seconds=120)
        self.queued()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(PACKAGE_ROOT))
        child = subprocess.Popen(
            [sys.executable, "-m", "luciazero_agentd", "dispatch", "--watch", "--state-dir", str(self.root)],
            cwd=PACKAGE_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            def in_flight() -> dict | None:
                runs = self.store.list_runs(state="running", limit=1)
                return runs[0] if runs and runs[0]["provider_pid"] else None

            deadline = time.time() + 30
            run = None
            while time.time() < deadline and run is None:
                run = in_flight()
                time.sleep(0.05)
            self.assertIsNotNone(run, "the dispatcher never started a turn")
            assert run is not None
            provider_pid = int(run["provider_pid"])
            self.assertEqual(self.store.get_binding(str(run["binding_id"]))["state"], "active")
            child.terminate()  # SIGTERM, what `kill <pid>` sends
            self.assertEqual(child.wait(timeout=30), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            if child.stdout is not None:
                child.stdout.close()
        self.assertEqual(self.store.get_binding(str(run["binding_id"]))["state"], "revoked")
        self.assertIsNone(self.store.lease_on("session", "claude-reviewer"))
        self.assertEqual(self.store.get_run(str(run["id"]))["state"], "failed")
        self.assertEqual(self.store.get_delivery(str(run["delivery_id"]))["state"], "retryable_failed")
        for _ in range(50):  # the provider is signalled, not reaped, so give it a moment
            if not _pid_alive(provider_pid):
                break
            time.sleep(0.1)
        self.assertFalse(_pid_alive(provider_pid), "the provider outlived the dispatcher that started it")

    def test_recovery_settles_what_a_killed_dispatcher_left(self) -> None:
        self.worker(command=[sys.executable, "-c", "print('turn')"], max_attempts=3)
        delivery = self.queued()
        session = self.store.ensure_session("claude-reviewer", provider="other")
        lease = self.store.acquire_lease("session", "claude-reviewer", holder="dispatch:dead",
                                         session_id=session["id"], holder_pid=424242, holder_started_at=None)
        self.store.dispatch_delivery(delivery["delivery_id"], agent_id="claude-reviewer", lease_id=lease["id"],
                                     generation=lease["generation"], session_id=session["id"])
        run = self.store.start_run(agent_id="claude-reviewer", delivery_id=delivery["delivery_id"],
                                   session_id=session["id"], lease_id=lease["id"], generation=lease["generation"])
        engine = Dispatcher(self.root, lease_ttl_seconds=60, alive=DEAD)
        recovered = engine.recover()
        self.assertEqual([r["id"] for r in recovered], [run["id"]])
        self.assertEqual(self.store.get_delivery(delivery["delivery_id"])["state"], "retryable_failed")


if __name__ == "__main__":
    unittest.main()

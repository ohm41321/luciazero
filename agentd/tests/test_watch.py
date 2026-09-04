"""The live watcher (M7a), against a real store with a real writer attached.

The watcher exists because the pull beta pushes nothing: two agents can hold a
whole conversation while both terminals show nothing. What has to be defended
is that watching stays watching -- the pane must never become a participant.
`deliveries.acknowledged_at` is the number the M4 decision gate measures a
user-started turn with, so a watcher that acknowledged anything would destroy
the evidence it was built to expose.

So these tests hold the writer open while the follower reads (the normal case,
not the exception), take a fingerprint of every row before and after, and
check that a restart replays rather than skips.
"""
from __future__ import annotations

import io
import os
import sqlite3
from datetime import datetime, timedelta, timezone
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from pathlib import Path

from tests.fixtures import make_repo

from luciazero_agentd import watch
from luciazero_agentd.__main__ import main
from luciazero_agentd.store import Store

ARCHITECT, IMPLEMENTER, BYSTANDER = "codex-architect", "claude-implementer", "claude-reviewer"


class WatchCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-watch-")
        self.state_dir = Path(self._tmp.name)
        self.db = self.state_dir / "bus.sqlite3"
        # The writer stays open for the whole test: a watcher always reads a
        # database somebody else is writing.
        self.store = Store.open(str(self.db))
        self.store.migrate()
        self.store.trust = "bound"
        for agent, provider, role in ((ARCHITECT, "codex", "architect"),
                                      (IMPLEMENTER, "claude", "implementer"),
                                      (BYSTANDER, "claude", "reviewer")):
            self.store.register_agent(agent, provider=provider, role=role)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def follower(self, **kwargs: object) -> watch.Follower:
        follower = watch.Follower(self.db, **kwargs)  # type: ignore[arg-type]
        self.addCleanup(follower.close)
        return follower

    def say(self, sender: str, recipient: str, text: str, *, kind: str = "question") -> dict:
        return self.store.send_message(sender=sender, recipient=recipient, kind=kind, payload={"text": text})

    def opened_by(self, agent: str) -> dict:
        """One delivery acknowledged the way a real turn does it."""
        delivery = self.store.inbox(agent, states=("queued",))["items"][-1]
        return self.store.ack_delivery(delivery["delivery_id"], agent)

    def fingerprint(self) -> dict:
        """Every row the watcher can see, as it stands right now."""
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return {table: [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY seq")]
                    for table in ("messages", "deliveries", "events")}
        finally:
            conn.close()


class ReadOnlyTests(WatchCase):
    def test_the_watcher_cannot_write_what_it_watches(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "can you see this")
        conn = self.follower().connect()
        for statement, params in (
                ("UPDATE deliveries SET acknowledged_at = '2026-01-01T00:00:00+00:00'", ()),
                ("UPDATE deliveries SET state = 'acknowledged'", ()),
                ("DELETE FROM messages", ()),
                ("INSERT INTO events (created_at, actor, kind, entity_type, entity_id, payload) "
                 "VALUES ('x', 'watcher', 'watched', 'message', 'x', '{}')", ())):
            with self.assertRaises(sqlite3.OperationalError, msg=statement):
                conn.execute(statement, params)

    def test_watching_leaves_messages_deliveries_events_and_acknowledged_at_exactly_as_they_were(self) -> None:
        """The whole point, stated as a fingerprint: a full watch cycle --
        history, live poll, delivery transitions, restart -- changes no row."""
        self.say(ARCHITECT, IMPLEMENTER, "first")
        self.opened_by(IMPLEMENTER)
        self.say(IMPLEMENTER, ARCHITECT, "second")
        before = self.fingerprint()
        follower = self.follower()
        follower.tail(10)
        follower.poll()
        follower.close()
        self.follower(since=0).poll()
        self.assertEqual(self.fingerprint(), before)

    def test_a_state_directory_with_no_database_is_named_not_created(self) -> None:
        missing = self.state_dir / "elsewhere" / "bus.sqlite3"
        with self.assertRaises(watch.WatchError) as caught:
            watch.open_read_only(missing)
        # mode=ro reports a missing file as "unable to open database file",
        # which reads like a permission problem; the path has to be in the
        # sentence or a typo in --state-dir is unfindable.
        self.assertIn(str(missing), str(caught.exception))
        self.assertFalse(missing.exists(), "a watcher must never create the database it watches")


class FollowTests(WatchCase):
    def test_it_reads_a_wal_database_while_the_writer_holds_it(self) -> None:
        journal = self.store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(str(journal).lower(), "wal", "the watcher's whole problem is reading a live WAL database")
        follower = self.follower()
        follower.tail(0)
        self.say(ARCHITECT, IMPLEMENTER, "written while the follower is attached")
        events = follower.poll()
        self.assertEqual([e["what"] for e in events][:1], ["message"])
        self.assertIn("written while the follower is attached", watch.preview(events[0]["payload"]))

    def test_it_reconnects_instead_of_dying_when_a_poll_fails(self) -> None:
        follower = self.follower()
        follower.tail(0)
        self.say(ARCHITECT, IMPLEMENTER, "sent while the connection is broken")
        follower.conn.close()  # the daemon restarted underneath it
        seen = list(follower.follow(interval=0, passes=2))
        self.assertEqual(follower.reconnects, 1)
        self.assertEqual([e["id"] for e in seen if e["what"] == "message"],
                         [m["id"] for m in self.fingerprint()["messages"]])

    def test_it_keeps_following_across_a_writer_restart(self) -> None:
        follower = self.follower()
        follower.tail(0)
        self.say(ARCHITECT, IMPLEMENTER, "before the restart")
        self.store.close()
        self.store = Store.open(str(self.db))
        self.store.migrate()
        self.store.trust = "bound"
        self.say(IMPLEMENTER, ARCHITECT, "after the restart")
        texts = [watch.preview(e["payload"]) for e in follower.poll() if e["what"] == "message"]
        self.assertEqual(texts, ["before the restart", "after the restart"])

    def test_a_restarted_watcher_repeats_rather_than_skips(self) -> None:
        """A follower that loses a message to a crash is worse than one that
        shows it twice, so the cursor is allowed to go backwards and never
        forwards past something unseen."""
        self.say(ARCHITECT, IMPLEMENTER, "one")
        self.say(IMPLEMENTER, ARCHITECT, "two")
        first = self.follower()
        seen = [e["id"] for e in first.poll()]
        self.assertEqual(len(seen), 2)
        restarted = self.follower(since=first.since - 1)
        self.assertEqual([e["id"] for e in restarted.poll() if e["what"] == "message"], seen[-1:])
        from_scratch = self.follower()
        self.assertEqual([m["id"] for m in from_scratch.tail(10)], seen)

    def test_the_same_message_is_not_shown_twice_by_one_watcher(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "one")
        follower = self.follower()
        self.assertEqual(len(follower.poll()), 1)
        self.assertEqual(follower.poll(), [])

    def test_history_first_so_a_pane_opened_late_still_makes_sense(self) -> None:
        for i in range(5):
            self.say(ARCHITECT, IMPLEMENTER, f"line {i}")
        follower = self.follower()
        self.assertEqual([watch.preview(m["payload"]) for m in follower.tail(2)], ["line 3", "line 4"])
        self.assertEqual(follower.poll(), [], "history must move the cursor, or every line shows twice")


class AttentionTests(WatchCase):
    def test_a_delivery_being_opened_is_reported_once_with_the_wait_it_cost(self) -> None:
        """The wait the decision gate measures, shown as it happens rather
        than reconstructed from memory in a retro."""
        self.say(ARCHITECT, IMPLEMENTER, "please look at this")
        follower = self.follower()
        follower.poll()
        self.opened_by(IMPLEMENTER)
        opened = [e for e in follower.poll() if e["what"] == "delivery"]
        self.assertEqual([e["state"] for e in opened], ["acknowledged"])
        self.assertEqual(opened[0]["recipient_agent_id"], IMPLEMENTER)
        self.assertIsNotNone(opened[0]["waited"])
        self.assertGreaterEqual(float(opened[0]["waited"]), 0.0)
        self.assertEqual([e for e in follower.poll() if e["what"] == "delivery"], [])

    def test_what_was_already_true_when_the_watcher_started_is_not_news(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "opened long before anyone watched")
        self.opened_by(IMPLEMENTER)
        follower = self.follower()
        self.assertEqual([e for e in follower.poll() if e["what"] == "delivery"], [])

    def test_the_wait_is_measured_even_when_the_message_predates_the_watcher(self) -> None:
        """The follower does not hold the whole history in memory, so the
        message a delivery belongs to is looked up when it is needed."""
        self.say(ARCHITECT, IMPLEMENTER, "sent long before anyone watched")
        follower = self.follower(since=self.fingerprint()["messages"][-1]["seq"])
        follower.connect()
        self.assertEqual(follower.messages, {}, "history must not be loaded just in case")
        self.opened_by(IMPLEMENTER)
        opened = [e for e in follower.poll() if e["what"] == "delivery"]
        self.assertEqual(len(opened), 1)
        self.assertIsNotNone(opened[0]["waited"])

    def test_what_it_remembers_stays_bounded(self) -> None:
        """A pane left open for a week must not grow with the bus."""
        follower = self.follower()
        cache: dict = {}
        for i in range(watch.CACHE_LIMIT * 2):
            follower._remember(cache, f"msg_{i}", {"sender": ARCHITECT, "created_at": "now"})
        self.assertLessEqual(len(cache), watch.CACHE_LIMIT)
        self.assertIn(f"msg_{watch.CACHE_LIMIT * 2 - 1}", cache, "the newest must survive the trim")

    def test_one_agent_can_be_watched_without_seeing_everyone_else(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "for the implementer")
        self.say(ARCHITECT, BYSTANDER, "for somebody else")
        follower = self.follower(agents=[IMPLEMENTER])
        texts = [watch.preview(e["payload"]) for e in follower.poll() if e["what"] == "message"]
        self.assertEqual(texts, ["for the implementer"])

    def test_watching_one_agent_still_shows_when_its_own_message_was_opened(self) -> None:
        """Half the value of watching one agent is learning that the other
        side finally read what it sent."""
        self.say(IMPLEMENTER, BYSTANDER, "did you get this")
        follower = self.follower(agents=[IMPLEMENTER])
        follower.poll()
        self.opened_by(BYSTANDER)
        opened = [e for e in follower.poll() if e["what"] == "delivery"]
        self.assertEqual([e["recipient_agent_id"] for e in opened], [BYSTANDER])


class PairTests(WatchCase):
    def test_watching_a_pair_leaves_out_what_a_third_agent_was_told(self) -> None:
        """"Watch these two talk" means these two: a message the architect
        sent to somebody else is not part of this conversation."""
        self.say(ARCHITECT, IMPLEMENTER, "between us")
        self.say(ARCHITECT, BYSTANDER, "to a third party")
        self.say(BYSTANDER, IMPLEMENTER, "from a third party")
        follower = self.follower(agents=[ARCHITECT, IMPLEMENTER], pair=True)
        texts = [watch.preview(e["payload"]) for e in follower.poll() if e["what"] == "message"]
        self.assertEqual(texts, ["between us"])

    def test_naming_the_same_agents_without_pair_shows_everything_they_touch(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "between us")
        self.say(ARCHITECT, BYSTANDER, "to a third party")
        follower = self.follower(agents=[ARCHITECT, IMPLEMENTER])
        texts = [watch.preview(e["payload"]) for e in follower.poll() if e["what"] == "message"]
        self.assertEqual(texts, ["between us", "to a third party"])


class ChatTests(WatchCase):
    """`chat` picks the terminals; picking must never write to the bus."""

    def roster(self) -> list[dict]:
        follower = self.follower()
        return watch.roster(follower.connect())

    def test_the_plan_names_a_terminal_for_each_side_and_one_for_the_conversation(self) -> None:
        plan = watch.conversation_plan(self.roster(), ARCHITECT, IMPLEMENTER)
        self.assertEqual(len(plan), 3)
        self.assertIn(f"watch --between {ARCHITECT} {IMPLEMENTER}", plan[0][1])
        self.assertIn(f"run --agent {ARCHITECT} -- codex", plan[1][1])
        self.assertIn(f"run --agent {IMPLEMENTER} -- claude", plan[2][1])

    def test_an_agent_with_its_own_worktree_is_started_from_inside_it(self) -> None:
        """A session started from the main checkout binds the main checkout,
        and the isolation two agents depend on is quietly gone."""
        repo = make_repo(self.state_dir / "wt-implementer")
        self.store.bind_worktree(IMPLEMENTER, repo)
        plan = dict((label, command) for label, command in
                    watch.conversation_plan(self.roster(), ARCHITECT, IMPLEMENTER))
        line = plan[f"terminal for {IMPLEMENTER} (claude)"]
        self.assertTrue(line.startswith(f"cd {repo}/agentd &&"), line)

    def test_an_agent_whose_provider_has_no_known_command_is_not_guessed_at(self) -> None:
        self.store.register_agent("someone-else", provider="other", role="helper")
        plan = watch.conversation_plan(self.roster(), ARCHITECT, "someone-else")
        self.assertIn("<your other command>", plan[2][1])

    def test_a_binding_whose_terminal_is_gone_is_not_offered_as_live(self) -> None:
        """`active` outlives the window: a closed terminal leaves its row
        behind, and sending the user there is worse than saying nothing."""
        self.store.bind_terminal(ARCHITECT, provider="codex", by="human:test", tty="ttys999", pid=os.getpid())
        self.assertEqual([a["tty"] for a in self.roster() if a["id"] == ARCHITECT], ["ttys999"])
        self.store.bind_terminal(IMPLEMENTER, provider="claude", by="human:test", tty="ttys998", pid=2 ** 22 - 1)
        self.assertEqual([a["tty"] for a in self.roster() if a["id"] == IMPLEMENTER], [None])

    def test_choosing_who_talks_changes_nothing_on_the_bus(self) -> None:
        before = self.fingerprint()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["chat", "--state-dir", str(self.state_dir), "--between", ARCHITECT, IMPLEMENTER])
        self.assertEqual(code, 0)
        self.assertIn("watch --between", out.getvalue())
        self.assertEqual(self.fingerprint(), before)

    def test_a_pair_that_is_not_two_different_known_agents_is_refused(self) -> None:
        for pair in ((ARCHITECT, ARCHITECT), (ARCHITECT, "nobody-here")):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["chat", "--state-dir", str(self.state_dir), "--between", *pair])
            self.assertEqual(code, 2, msg=str(pair))
            self.assertIn("two different agents", err.getvalue())


class NextTests(WatchCase):
    """`next` answers the question everybody was answering by hand: `status`
    says what the state is, this says which terminal that means opening."""

    def owed(self) -> list[dict]:
        return watch.owed(self.follower().connect())

    def test_a_queued_message_names_the_agent_and_the_command_that_opens_it(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "please look at this")
        actions = self.owed()
        self.assertEqual([a["kind"] for a in actions], ["inbox"])
        self.assertEqual(actions[0]["agent"], IMPLEMENTER)
        self.assertIn(f"run --agent {IMPLEMENTER} -- claude", actions[0]["do"])

    def test_a_session_waiting_to_be_verified_comes_first_of_all(self) -> None:
        """Until somebody answers it, that session cannot do anything at all,
        and the person it is waiting for is the one reading this."""
        self.say(ARCHITECT, IMPLEMENTER, "queued for later")
        request, _code = self.store.open_claim(BYSTANDER, session_hash="a" * 64, provider="claude")
        actions = self.owed()
        self.assertEqual([a["kind"] for a in actions], ["claim", "inbox"])
        self.assertIn(f"claim approve {request['id']}", actions[0]["do"])
        self.assertIn("another terminal", actions[0]["why"])

    def test_an_expired_request_is_not_still_offered(self) -> None:
        request, _code = self.store.open_claim(BYSTANDER, session_hash="b" * 64, provider="claude")
        gone = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="microseconds")
        self.store._conn.execute("UPDATE claim_requests SET expires_at = ? WHERE id = ?", (gone, request["id"]))
        self.store._conn.commit()
        self.assertEqual(self.owed(), [])

    def test_what_needs_a_person_outranks_what_only_needs_a_turn(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "still queued")
        self.say(ARCHITECT, BYSTANDER, "undeliverable")
        delivery = self.store.inbox(BYSTANDER, states=("queued",))["items"][-1]
        self.store._conn.execute("UPDATE deliveries SET state = 'dead_letter' WHERE id = ?",
                                 (delivery["delivery_id"],))
        self.store._conn.commit()
        actions = self.owed()
        self.assertEqual([a["kind"] for a in actions], ["dead_letter", "inbox"])
        self.assertIsNone(actions[0]["do"], "a dead letter is a decision, not a command")

    def test_a_task_somebody_is_holding_is_not_repeated_when_its_inbox_already_says_so(self) -> None:
        task = self.store.create_task(title="the work", created_by=ARCHITECT, assigned_to=IMPLEMENTER)
        self.store.send_message(sender=ARCHITECT, recipient=IMPLEMENTER, kind="task",
                                payload={"task_id": task["id"]})
        item = self.store.inbox(IMPLEMENTER, states=("queued",))["items"][-1]
        self.store.ack_delivery(item["delivery_id"], IMPLEMENTER)
        self.store.claim_task(task["id"], IMPLEMENTER)
        self.assertEqual([a["kind"] for a in self.owed()], ["claimed"])
        self.say(ARCHITECT, IMPLEMENTER, "and one more thing")
        self.assertEqual([a["kind"] for a in self.owed()], ["inbox"],
                         "one line per agent: the queued message already means open that session")

    def test_a_stopped_task_is_offered_as_a_decision_with_the_command_written_out(self) -> None:
        task = self.store.create_task(title="ran out", created_by=ARCHITECT, assigned_to=IMPLEMENTER)
        self.store._conn.execute("UPDATE tasks SET state = 'exhausted' WHERE id = ?", (task["id"],))
        self.store._conn.commit()
        actions = self.owed()
        self.assertEqual([a["kind"] for a in actions], ["exhausted"])
        self.assertIn(f"cancel {task['id']}", actions[0]["do"])

    def test_a_quiet_bus_owes_nothing(self) -> None:
        self.assertEqual(self.owed(), [])

    def test_the_command_says_what_to_start_when_the_daemon_is_down(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["next", "--state-dir", str(self.state_dir)])
        self.assertEqual(code, 0)
        # No endpoint.json in this fixture: nothing else can happen first.
        self.assertIn("serve", out.getvalue())

    def test_asking_what_to_do_next_changes_nothing(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "queued")
        before = self.fingerprint()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["next", "--state-dir", str(self.state_dir), "--json"]), 0)
        self.assertEqual(self.fingerprint(), before)


class RenderTests(WatchCase):
    def test_a_task_message_shows_the_title_not_the_id(self) -> None:
        task = self.store.create_task(title="M7a: read-only inbox watcher",
                                      created_by=ARCHITECT, assigned_to=IMPLEMENTER)
        self.store.send_message(sender=ARCHITECT, recipient=IMPLEMENTER, kind="task",
                                payload={"task_id": task["id"]})
        follower = self.follower()
        line = watch.Renderer().line([e for e in follower.poll() if e["what"] == "message"][0])
        self.assertIn("M7a: read-only inbox watcher", line)

    def test_peer_text_cannot_repaint_the_pane(self) -> None:
        """Everything on this pane was written by another agent."""
        self.say(ARCHITECT, IMPLEMENTER, "clear\x1b[2Jthis\x00now")
        follower = self.follower()
        line = watch.Renderer(colour=False).line([e for e in follower.poll()][0])
        self.assertNotIn("\x1b", line)
        self.assertNotIn("\x00", line)

    def test_a_secret_shaped_payload_is_scrubbed_on_the_way_to_the_screen(self) -> None:
        """The daemon redacts on the way in; a pane left open on a desk is a
        second audience, so it redacts again on the way out."""
        secret = "lzsc_" + "0" * 32
        self.assertNotIn(secret, watch.preview({"text": f"credential {secret} here"}))

    def test_a_long_line_is_cut_so_one_message_stays_one_line(self) -> None:
        self.assertEqual(len(watch.preview({"text": "x" * 500}, width=40)), 40)


class CommandTests(WatchCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["watch", "--state-dir", str(self.state_dir), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_one_pass_prints_the_conversation_and_exits(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "printed by the command")
        code, out, _ = self.run_cli("--once", "--color", "never")
        self.assertEqual(code, 0)
        self.assertIn("printed by the command", out)
        self.assertIn(f"{ARCHITECT}", out)
        self.assertIn("read-only", out.splitlines()[0])

    def test_an_agent_nobody_has_ever_heard_of_is_refused_not_silently_empty(self) -> None:
        code, _, err = self.run_cli("--once", "--agent", "nobody-here")
        self.assertEqual(code, 2)
        self.assertIn("no agent", err)

    def test_payload_none_shows_who_talked_to_whom_and_nothing_they_said(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "a secret plan")
        code, out, _ = self.run_cli("--once", "--payload", "none", "--color", "never")
        self.assertEqual(code, 0)
        self.assertNotIn("a secret plan", out)
        self.assertIn(IMPLEMENTER, out)

    def test_two_different_filters_at_once_are_refused_rather_than_ranked(self) -> None:
        code, _, err = self.run_cli("--once", "--between", ARCHITECT, IMPLEMENTER, "--agent", BYSTANDER)
        self.assertEqual(code, 2)
        self.assertIn("pick one", err)

    def test_a_missing_state_directory_exits_2_with_the_path(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["watch", "--once", "--state-dir", str(self.state_dir / "nowhere")])
        self.assertEqual(code, 2)
        self.assertIn("nowhere", err.getvalue())


if __name__ == "__main__":
    sys.exit(unittest.main())


class LauncherTests(WatchCase):
    """Which form of the command a human is shown (M7e).

    Everything `chat` and `next` print is meant to be pasted into another
    terminal, so the only property that matters is that what is printed runs.
    `luciazero-agentd` runs only once install.sh has put it on PATH; before
    that the package is reached with `python3 -m` from the `agentd` directory,
    and printing the short form early would print a command not found.
    """

    def test_the_short_form_is_used_once_the_launcher_is_installed(self) -> None:
        self.assertEqual("luciazero-agentd", watch.launcher(which=lambda name: "/opt/bin/" + name))

    def test_without_it_the_module_form_carries_its_own_cd(self) -> None:
        printed = watch.launcher(which=lambda name: None)
        self.assertTrue(printed.endswith("agentd && python3 -m luciazero_agentd"), printed)
        self.assertTrue(Path(printed.split(" && ")[0][len("cd "):]).is_dir(),
                        "the fallback names a directory that exists")

    def test_an_agent_is_still_started_from_inside_its_own_worktree(self) -> None:
        """The `cd` exists so the binding records the worktree. With the
        launcher it lands in the worktree itself; without it, in the `agentd`
        directory under it, which is where the module has to be imported."""
        self.assertEqual("cd /tmp/wt && luciazero-agentd",
                         watch.launcher_in("/tmp/wt", which=lambda name: "/opt/bin/" + name))
        self.assertEqual("cd /tmp/wt/agentd && python3 -m luciazero_agentd",
                         watch.launcher_in("/tmp/wt", which=lambda name: None))

    def test_a_worktree_with_a_space_stays_one_argument(self) -> None:
        """`cd /tmp/my tree && ...` is a command that cds somewhere else."""
        for which in (lambda name: "/opt/bin/" + name, lambda name: None):
            printed = watch.launcher_in("/tmp/my tree", which=which)
            self.assertIn("'/tmp/my tree", printed, printed)

    def test_next_prints_the_short_form_when_it_is_available(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "please look at this")
        with mock.patch("shutil.which", lambda name: "/opt/bin/" + name):
            actions = watch.owed(self.follower().connect())
        self.assertTrue(actions[0]["do"].startswith("luciazero-agentd run --agent"),
                        actions[0]["do"])

    def test_next_falls_back_to_the_python_form_when_it_is_not(self) -> None:
        self.say(ARCHITECT, IMPLEMENTER, "please look at this")
        with mock.patch("shutil.which", lambda name: None):
            actions = watch.owed(self.follower().connect())
        self.assertIn("python3 -m luciazero_agentd run --agent", actions[0]["do"])

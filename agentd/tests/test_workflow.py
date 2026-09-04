"""M5 workflow contract: the task graph, the loop stoppers, per-task budgets,
and artifact provenance.

What each group is defending:

* a task never becomes claimable while a prerequisite is unfinished, and the
  transition that makes it claimable happens in the same transaction as the
  prerequisite's completion, so no turn can see a half-settled graph;
* a prerequisite that ends any way but ``completed`` blocks what waits on it,
  all the way down, because a dependent that waits on a task nobody will ever
  finish waits forever;
* a cycle is refused before anything is written;
* a conversation cannot run away: the daemon counts hops itself, and a sender
  cannot reset that count;
* a budget is a stop, not a warning -- the task goes terminal, its queued work
  is dead-lettered, and nothing more runs on it;
* an artifact record keeps who produced it and how much that identity was
  worth, and a result can only cite artifacts that exist.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from luciazero_agentd import ConflictError, NotFound, Store, ValidationError
from luciazero_agentd.store import (
    CONVERSATION_TTL_SECONDS,
    MAX_HOPS,
    BudgetExceeded,
    ConversationLimit,
    DependencyRefused,
    _plus_seconds,
    utcnow,
)
from tests.fixtures import commit_file, git, make_repo


class WorkflowCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-workflow-")
        self.store = Store.open(str(Path(self._tmp.name) / "bus.sqlite3"))
        self.store.migrate()
        self.store.register_agent("codex-architect", provider="codex", role="architect")
        self.store.register_agent("claude-reviewer", provider="claude", role="reviewer")
        self.store.register_agent("codex-implementer", provider="codex", role="implementer")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    # helpers
    def task(self, title: str, **kwargs: object) -> dict:
        return self.store.create_task(title=title, created_by="codex-architect", **kwargs)  # type: ignore[arg-type]

    def state(self, task_id: str) -> str:
        return str(self.store.get_task(task_id)["state"])

    def events(self, kind: str) -> list[dict]:
        return [e for e in self.store.events(limit=500) if e["kind"] == kind]

    def worktree(self, agent_id: str, name: str = "repo") -> str:
        repo = make_repo(Path(self._tmp.name) / name)
        self.store.bind_worktree(agent_id, repo)
        return repo


class DependencyTests(WorkflowCase):
    def test_a_task_with_an_unfinished_prerequisite_starts_waiting_and_cannot_be_claimed(self) -> None:
        first = self.task("fix")
        second = self.task("verify", depends_on=[first["id"]])
        self.assertEqual(second["state"], "waiting")
        self.assertEqual(second["depends_on"], [first["id"]])
        with self.assertRaises(ConflictError) as caught:
            self.store.claim_task(second["id"], "claude-reviewer")
        self.assertIn("waiting", str(caught.exception))
        self.assertIn(first["id"], str(caught.exception))

    def test_a_prerequisite_that_is_already_complete_creates_an_open_task(self) -> None:
        first = self.task("fix")
        self.store.claim_task(first["id"], "codex-implementer")
        self.store.complete_task(first["id"], "codex-implementer")
        second = self.task("verify", depends_on=[first["id"]])
        self.assertEqual(second["state"], "open")

    def test_completing_the_last_prerequisite_opens_the_dependent_in_the_same_transaction(self) -> None:
        one = self.task("fix a")
        two = self.task("fix b")
        both = self.task("verify", depends_on=[one["id"], two["id"]])
        self.store.claim_task(one["id"], "codex-implementer")
        self.store.complete_task(one["id"], "codex-implementer")
        self.assertEqual(self.state(both["id"]), "waiting")  # one prerequisite left
        self.store.claim_task(two["id"], "codex-implementer")
        self.store.complete_task(two["id"], "codex-implementer")
        self.assertEqual(self.state(both["id"]), "open")
        unblocked = self.events("task.unblocked")
        self.assertEqual([e["entity_id"] for e in unblocked], [both["id"]])
        # That the unblocking shares the completing transaction, rather than
        # following it, is proved by killing the process between the two:
        # tests.test_crash.CrashCase.test_completion_and_unblocking_commit_together
        self.store.claim_task(both["id"], "claude-reviewer")
        self.assertEqual(self.state(both["id"]), "claimed")

    def test_a_prerequisite_that_ends_blocked_blocks_the_whole_chain_below_it(self) -> None:
        one = self.task("fix")
        two = self.task("verify", depends_on=[one["id"]])
        three = self.task("report", depends_on=[two["id"]])
        self.store.claim_task(one["id"], "codex-implementer")
        self.store.complete_task(one["id"], "codex-implementer", outcome="blocked", result={"why": "needs a decision"})
        self.assertEqual(self.state(two["id"]), "blocked")
        self.assertEqual(self.state(three["id"]), "blocked")
        self.assertEqual(self.store.get_task(two["id"])["result"], {"blocked_by": one["id"], "prerequisite_state": "blocked"})
        self.assertEqual(self.store.get_task(three["id"])["result"], {"blocked_by": two["id"], "prerequisite_state": "blocked"})

    def test_cancelling_a_prerequisite_blocks_its_dependents(self) -> None:
        one = self.task("fix")
        two = self.task("verify", depends_on=[one["id"]])
        self.store.cancel_task(one["id"], "human", reason="changed my mind")
        self.assertEqual(self.state(two["id"]), "blocked")

    def test_a_dependency_on_a_task_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaises(NotFound):
            self.task("verify", depends_on=["tsk_missing"])

    def test_a_new_task_whose_prerequisite_already_failed_is_created_blocked(self) -> None:
        one = self.task("fix")
        self.store.cancel_task(one["id"], "human")
        late = self.task("verify", depends_on=[one["id"]])
        self.assertEqual(late["state"], "blocked")
        self.assertEqual(late["result"], {"blocked_by": one["id"], "prerequisite_state": "cancelled"})


class GraphTests(WorkflowCase):
    def test_a_graph_is_created_in_one_transaction_with_its_edges(self) -> None:
        tasks = self.store.create_task_graph(created_by="codex-architect", nodes=[
            {"key": "fix", "title": "fix the bug", "assigned_to": "codex-implementer"},
            {"key": "verify", "title": "verify the fix", "depends_on": ["fix"], "assigned_to": "claude-reviewer"},
            {"key": "report", "title": "report the outcome", "depends_on": ["verify", "fix"]},
        ])
        self.assertEqual([t["title"] for t in tasks], ["fix the bug", "verify the fix", "report the outcome"])
        self.assertEqual([t["state"] for t in tasks], ["open", "waiting", "waiting"])
        view = self.store.task_view(tasks[2]["id"])
        self.assertEqual(sorted(view["unmet_dependencies"]), sorted([tasks[0]["id"], tasks[1]["id"]]))
        self.assertEqual(self.store.task_view(tasks[0]["id"])["blocks"], sorted([tasks[1]["id"], tasks[2]["id"]]))

    def test_a_cycle_is_refused_and_nothing_is_written(self) -> None:
        before = self.store.counts()
        with self.assertRaises(DependencyRefused) as caught:
            self.store.create_task_graph(created_by="codex-architect", nodes=[
                {"key": "a", "title": "a", "depends_on": ["c"]},
                {"key": "b", "title": "b", "depends_on": ["a"]},
                {"key": "c", "title": "c", "depends_on": ["b"]},
            ])
        self.assertIn("cycle", str(caught.exception))
        self.assertEqual(self.store.counts()["tasks"], before["tasks"])
        self.assertEqual(self.store.counts()["task_deps"], before["task_deps"])

    def test_a_task_cannot_depend_on_itself(self) -> None:
        with self.assertRaises(DependencyRefused):
            self.store.create_task_graph(created_by="codex-architect", nodes=[{"key": "a", "title": "a", "depends_on": ["a"]}])

    def test_a_graph_node_may_depend_on_a_task_that_already_exists(self) -> None:
        first = self.task("fix")
        tasks = self.store.create_task_graph(created_by="codex-architect", nodes=[
            {"key": "verify", "title": "verify", "depends_on": [first["id"]]},
        ])
        self.assertEqual(tasks[0]["state"], "waiting")
        self.store.claim_task(first["id"], "codex-implementer")
        self.store.complete_task(first["id"], "codex-implementer")
        self.assertEqual(self.state(tasks[0]["id"]), "open")

    def test_a_replayed_graph_returns_the_same_tasks(self) -> None:
        nodes = [{"key": "fix", "title": "fix"}, {"key": "verify", "title": "verify", "depends_on": ["fix"]}]
        first = self.store.create_task_graph(created_by="codex-architect", nodes=nodes, idempotency_key="g1")
        again = self.store.create_task_graph(created_by="codex-architect", nodes=nodes, idempotency_key="g1")
        self.assertEqual([t["id"] for t in first], [t["id"] for t in again])
        self.assertEqual(self.store.counts()["tasks"], 2)

    def test_bad_graphs_are_refused(self) -> None:
        with self.assertRaises(ValidationError):
            self.store.create_task_graph(created_by="codex-architect", nodes=[])
        with self.assertRaises(ValidationError):
            self.store.create_task_graph(created_by="codex-architect", nodes=[{"title": "no key"}])
        with self.assertRaises(ValidationError):
            self.store.create_task_graph(created_by="codex-architect", nodes=[
                {"key": "a", "title": "a"}, {"key": "a", "title": "again"},
            ])
        with self.assertRaises(ValidationError):
            self.store.create_task_graph(created_by="codex-architect", nodes=[{"key": "a", "title": "a", "nonsense": 1}])


class ConversationLimitTests(WorkflowCase):
    def send(self, correlation: str | None = None, **kwargs: object) -> dict:
        return self.store.send_message(
            sender="codex-architect", recipient="claude-reviewer", kind="question",
            payload={}, correlation_id=correlation, **kwargs,  # type: ignore[arg-type]
        )

    def test_the_daemon_counts_hops_and_the_sender_cannot(self) -> None:
        first = self.send()
        correlation = first["correlation_id"]
        self.assertEqual(first["hop_count"], 0)
        second = self.send(correlation)
        self.assertEqual(second["hop_count"], 1)
        third = self.send(correlation)
        self.assertEqual(third["hop_count"], 2)

    def test_a_reply_loop_stops_at_the_hop_limit(self) -> None:
        first = self.send()
        correlation = first["correlation_id"]
        for _ in range(MAX_HOPS):
            self.send(correlation)
        before = self.store.counts()["messages"]
        with self.assertRaises(ConversationLimit) as caught:
            self.send(correlation)
        self.assertIn(str(MAX_HOPS), str(caught.exception))
        self.assertEqual(self.store.counts()["messages"], before)
        refusals = self.events("conversation.hop_limit")
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["payload"]["limit"], MAX_HOPS)

    def test_a_threaded_reply_joins_its_parents_conversation(self) -> None:
        """Review finding: the cap counted per correlation_id, so a ping-pong
        threaded with reply_to alone started a fresh conversation on every turn
        and never reached the limit. The parent's conversation is now inherited."""
        first = self.send()
        reply = self.store.send_message(sender="claude-reviewer", recipient="codex-architect",
                                        kind="question", payload={}, reply_to=first["id"])
        self.assertEqual(reply["correlation_id"], first["correlation_id"])
        self.assertEqual(reply["hop_count"], 1)
        parent = reply["id"]
        names = ("codex-architect", "claude-reviewer")
        for hop in range(MAX_HOPS - 1):
            parent = self.store.send_message(sender=names[hop % 2], recipient=names[(hop + 1) % 2],
                                             kind="question", payload={}, reply_to=parent)["id"]
        with self.assertRaises(ConversationLimit):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer",
                                    kind="question", payload={}, reply_to=parent)

    def test_a_reply_cannot_be_filed_under_another_conversation(self) -> None:
        first = self.send()
        other = self.send()
        with self.assertRaises(ConflictError) as caught:
            self.store.send_message(sender="claude-reviewer", recipient="codex-architect", kind="question",
                                    payload={}, reply_to=first["id"], correlation_id=other["correlation_id"])
        self.assertIn("omit reply_to to start a new conversation", str(caught.exception))

    def test_a_conversation_stops_when_it_outlives_its_ttl(self) -> None:
        # Messages are immutable, so the aged conversation is seeded rather
        # than back-dated: this is the shape a bus left running overnight has.
        correlation = "msg_stale"
        stale = _plus_seconds(utcnow(), -(CONVERSATION_TTL_SECONDS + 60))
        self.store._conn.execute(
            """INSERT INTO messages (id, sender_agent_id, recipient_agent_id, kind, payload, correlation_id, hop_count, created_at)
               VALUES (?, 'codex-architect', 'claude-reviewer', 'question', '{}', ?, 0, ?)""",
            (correlation, correlation, stale),
        )
        before = self.store.counts()["messages"]
        with self.assertRaises(ConversationLimit) as caught:
            self.send(correlation)
        self.assertIn("time to live", str(caught.exception))
        self.assertEqual(self.store.counts()["messages"], before)
        self.assertEqual(len(self.events("conversation.expired")), 1)


class BudgetTests(WorkflowCase):
    def test_an_unknown_budget_dimension_is_refused_rather_than_ignored(self) -> None:
        with self.assertRaises(ValidationError):
            self.task("bounded", budget={"minutes": 5})
        with self.assertRaises(ValidationError):
            self.task("bounded", budget={"turns": 0})
        with self.assertRaises(ValidationError):
            self.task("bounded", budget={"cost_usd": -1})

    def test_the_send_that_would_overspend_the_turn_budget_stops_the_task(self) -> None:
        task = self.task("bounded", budget={"turns": 2})
        for _ in range(2):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        self.assertEqual(self.store.get_task(task["id"])["spent"]["turns"], 2)
        messages = self.store.counts()["messages"]
        with self.assertRaises(BudgetExceeded) as caught:
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        self.assertIn("turns", str(caught.exception))
        self.assertEqual(self.store.counts()["messages"], messages)
        self.assertEqual(self.state(task["id"]), "exhausted")
        self.assertEqual(self.store.get_task(task["id"])["result"]["dimension"], "turns")

    def test_stopping_dead_letters_the_queued_work_and_refuses_a_later_claim(self) -> None:
        task = self.task("bounded", budget={"turns": 1})
        self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        with self.assertRaises(BudgetExceeded):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        inbox = self.store.inbox("claude-reviewer", states=("queued",))
        self.assertEqual(inbox["items"], [])
        self.assertEqual(len(self.events("delivery.dead_letter")), 1)
        with self.assertRaises(ConflictError):
            self.store.claim_task(task["id"], "claude-reviewer")

    def test_a_task_past_its_deadline_is_stopped_on_the_next_claim(self) -> None:
        task = self.task("bounded", budget={"seconds": 3600})
        self.store._conn.execute("UPDATE tasks SET deadline_at = ? WHERE id = ?", (_plus_seconds(utcnow(), -60), task["id"]))
        with self.assertRaises(BudgetExceeded) as caught:
            self.store.claim_task(task["id"], "claude-reviewer")
        self.assertIn("seconds", str(caught.exception))
        self.assertEqual(self.state(task["id"]), "exhausted")

    def test_reported_usage_is_additive_and_spends_the_budget(self) -> None:
        task = self.task("bounded", budget={"tokens": 100})
        self.store.claim_task(task["id"], "claude-reviewer")
        self.store.record_usage(task["id"], "claude-reviewer", tokens=40)
        record = self.store.record_usage(task["id"], "claude-reviewer", tokens=40)
        self.assertEqual(record["spent"]["tokens"], 80)
        self.assertEqual(record["state"], "claimed")
        record = self.store.record_usage(task["id"], "claude-reviewer", tokens=40)
        self.assertEqual(record["state"], "exhausted")
        self.assertEqual(record["result"]["dimension"], "tokens")

    def test_usage_carries_the_reporters_trust_and_cannot_be_lowered(self) -> None:
        task = self.task("bounded", budget={"cost_usd": 1.0})
        self.store.claim_task(task["id"], "claude-reviewer")
        self.store.trust = "bound"
        self.store.record_usage(task["id"], "claude-reviewer", cost_usd=0.25)
        usage = self.events("task.usage")[-1]
        self.assertEqual(usage["payload"]["trust"], "bound")
        with self.assertRaises(ValidationError):
            self.store.record_usage(task["id"], "claude-reviewer", cost_usd=-0.25)
        with self.assertRaises(ValidationError):
            self.store.record_usage(task["id"], "claude-reviewer")
        self.assertEqual(self.store.get_task(task["id"])["spent"]["cost_usd"], 0.25)

    def test_only_the_claim_holder_records_usage(self) -> None:
        """A peer that could credit usage to a task it never claimed could spend
        another agent's budget and stop its work, with no way to reopen it."""
        task = self.task("bounded", assigned_to="codex-implementer", budget={"tokens": 100})
        with self.assertRaises(ConflictError):
            self.store.record_usage(task["id"], "codex-implementer", tokens=1)  # not claimed yet
        self.store.claim_task(task["id"], "codex-implementer")
        with self.assertRaises(ConflictError) as caught:
            self.store.record_usage(task["id"], "claude-reviewer", tokens=90)
        self.assertIn("claim", str(caught.exception))
        self.assertEqual(self.store.get_task(task["id"])["spent"]["tokens"], 0)
        self.assertEqual(self.state(task["id"]), "claimed")
        self.store.record_usage(task["id"], "codex-implementer", tokens=90)
        self.store.complete_task(task["id"], "codex-implementer")
        with self.assertRaises(ConflictError):
            self.store.record_usage(task["id"], "codex-implementer", tokens=1)

    def test_stopping_a_task_blocks_what_was_waiting_on_it(self) -> None:
        first = self.task("bounded", budget={"turns": 1})
        second = self.task("verify", depends_on=[first["id"]])
        self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": first["id"]})
        with self.assertRaises(BudgetExceeded):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": first["id"]})
        self.assertEqual(self.state(second["id"]), "blocked")

    def test_budget_remaining_reports_what_is_left(self) -> None:
        task = self.task("bounded", budget={"turns": 3, "tokens": 10})
        self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        view = self.store.task_view(task["id"])
        self.assertEqual(view["budget_remaining"], {"turns": 2.0, "tokens": 10.0})


class ProvenanceTests(WorkflowCase):
    def test_an_artifact_keeps_its_producer_and_the_trust_of_that_identity(self) -> None:
        repo = self.worktree("codex-implementer")
        head = commit_file(repo, "fix.py", "print('fixed')\n")
        self.store.trust = "bound"
        task = self.task("fix")
        artifact = self.store.publish_artifact(kind="commit", ref=head, produced_by="codex-implementer", task_id=task["id"])
        self.assertEqual(artifact["produced_by_agent_id"], "codex-implementer")
        self.assertEqual(artifact["trust"], "bound")
        listed = self.store.list_artifacts(task_id=task["id"])["items"]
        self.assertEqual([a["id"] for a in listed], [artifact["id"]])
        self.assertEqual(self.store.list_artifacts(produced_by="claude-reviewer")["items"], [])

    def test_a_result_can_only_cite_artifacts_that_exist(self) -> None:
        repo = self.worktree("codex-implementer")
        head = commit_file(repo, "fix.py", "print('fixed')\n")
        task = self.task("fix")
        artifact = self.store.publish_artifact(kind="commit", ref=head, produced_by="codex-implementer", task_id=task["id"])
        self.store.claim_task(task["id"], "codex-implementer")
        with self.assertRaises(NotFound):
            self.store.complete_task(task["id"], "codex-implementer", artifacts=["art_missing"])
        self.assertEqual(self.state(task["id"]), "claimed")  # the refusal changed nothing
        record = self.store.complete_task(task["id"], "codex-implementer", result={"verdict": "fixed"}, artifacts=[artifact["id"]])
        self.assertEqual(record["result"], {"verdict": "fixed", "artifacts": [artifact["id"]]})
        self.assertEqual(self.events("task.completed")[-1]["payload"]["artifacts"], [artifact["id"]])

    def test_a_verifier_cites_the_artifact_someone_else_produced(self) -> None:
        repo = self.worktree("codex-implementer")
        head = commit_file(repo, "fix.py", "print('fixed')\n")
        fix = self.task("fix")
        artifact = self.store.publish_artifact(kind="commit", ref=head, produced_by="codex-implementer", task_id=fix["id"])
        self.store.claim_task(fix["id"], "codex-implementer")
        self.store.complete_task(fix["id"], "codex-implementer", artifacts=[artifact["id"]])
        verify = self.task("verify", depends_on=[fix["id"]])
        self.assertEqual(self.state(verify["id"]), "open")
        self.store.claim_task(verify["id"], "claude-reviewer")
        record = self.store.complete_task(verify["id"], "claude-reviewer", result={"verified": True}, artifacts=[artifact["id"]])
        self.assertEqual(record["result"]["artifacts"], [artifact["id"]])
        # The cited artifact still names the agent that produced it, not the
        # one that cited it: verification does not rewrite provenance.
        self.assertEqual(self.store.get_artifact(artifact["id"])["produced_by_agent_id"], "codex-implementer")

    def test_a_stopped_task_takes_no_more_artifacts(self) -> None:
        repo = self.worktree("codex-implementer")
        head = commit_file(repo, "fix.py", "print('fixed')\n")
        task = self.task("bounded")
        self.store.cancel_task(task["id"], "human")
        with self.assertRaises(ConflictError):
            self.store.publish_artifact(kind="commit", ref=head, produced_by="codex-implementer", task_id=task["id"])

    def test_status_names_the_tasks_it_stopped(self) -> None:
        task = self.task("bounded", budget={"turns": 1})
        self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        with self.assertRaises(BudgetExceeded):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"task_id": task["id"]})
        status = self.store.status()
        # A stopped task is in no list a human reads otherwise: not open, not
        # claimed, and nobody is coming back to it.
        self.assertEqual([t["id"] for t in status["stopped_tasks"]], [task["id"]])
        self.assertEqual(status["stopped_tasks"][0]["dimension"], "turns")

    def test_status_counts_the_new_states(self) -> None:
        first = self.task("fix")
        self.task("verify", depends_on=[first["id"]])
        status = self.store.status()
        self.assertEqual(status["tasks"]["waiting"], 1)
        self.assertEqual(status["tasks"]["exhausted"], 0)


if __name__ == "__main__":
    unittest.main()

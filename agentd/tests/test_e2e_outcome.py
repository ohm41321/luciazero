"""The M4 gate's own assertion, checked against crafted record sets.

`assert_outcome` in scripts/agent_bus_e2e.py is the only thing that decides
whether a live run reached the roadmap state, and no fake-provider run can
exercise its live branch: these cases do, including the message set the
approved 2026-09-03 live run actually produced.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_bus_e2e as e2e  # noqa: E402

ARCHITECT, REVIEWER, IMPLEMENTER = e2e.ARCHITECT, e2e.REVIEWER, e2e.IMPLEMENTER
FLOW = [
    ("task", ARCHITECT, REVIEWER),
    ("finding", REVIEWER, ARCHITECT),
    ("task", ARCHITECT, IMPLEMENTER),
    ("artifact", IMPLEMENTER, REVIEWER),
    ("result", REVIEWER, ARCHITECT),
]
# what the live architect added after the flow: a courtesy result nobody reads
COURTESY = ("result", ARCHITECT, REVIEWER)


def snapshot(messages, *, states=None, correlation="msg_0", bindings=3, asserted_writes=()):
    """A record set that passes every other check, so a case fails only for
    the message or delivery reason it is about."""
    states = states or ["completed"] * len(messages)
    return {
        "counts": {"leases": 0, "approvals": 0},
        "tasks": [
            {"id": "tsk_1", "title": "review", "state": "completed", "assigned_to": REVIEWER, "requires_worktree": 1},
            {"id": "tsk_2", "title": "fix", "state": "completed", "assigned_to": IMPLEMENTER, "requires_worktree": 1},
            {"id": "tsk_3", "title": "verify", "state": "completed", "assigned_to": REVIEWER, "requires_worktree": 1},
        ],
        "messages": [
            {"id": f"msg_{i}", "kind": kind, "from": sender, "to": recipient, "correlation_id": correlation}
            for i, (kind, sender, recipient) in enumerate(messages)
        ],
        "deliveries": [{"id": f"dlv_{i}", "state": state} for i, state in enumerate(states)],
        "artifacts": [
            {"id": "art_1", "kind": "report", "ref": "reports/finding.md", "by": REVIEWER},
            {"id": "art_2", "kind": "commit", "ref": "0" * 40, "by": IMPLEMENTER},
            {"id": "art_3", "kind": "report", "ref": "reports/verification.md", "by": REVIEWER},
        ],
        "event_kinds": ["worktree.bound"] * 3 + ["binding.created"] * bindings + ["message.sent"] * len(messages),
        "asserted_writes": list(asserted_writes),
        "worktrees": [{"path": "/tmp/wt-reviewer"}, {"path": "/tmp/wt-implementer"}],
    }


class OutcomeAssertionTests(unittest.TestCase):
    def setUp(self):
        self.daemon = SimpleNamespace(pids=[11, 22])
        self.ws = SimpleNamespace(reviewer_wt="/tmp/wt-reviewer", implementer_wt="/tmp/wt-implementer")
        self.real = os.path.realpath  # the assertion realpaths the worktree paths
        e2e.os.path.realpath = lambda p: str(p)
        self.addCleanup(setattr, e2e.os.path, "realpath", self.real)

    def check(self, snap, *, live):
        return e2e.assert_outcome(snap, self.daemon, self.ws, "msg_0", live=live)

    def refuse(self, snap, *, live):
        with self.assertRaises(e2e.E2EError) as caught:
            self.check(snap, live=live)
        return str(caught.exception)

    def test_the_flow_alone_passes_in_both_modes(self):
        for live in (False, True):
            with self.subTest(live=live):
                out = self.check(snapshot(FLOW), live=live)
                self.assertEqual(out["chatter"], [])
                self.assertEqual(out["commit"], "0" * 40)

    def test_live_courtesy_message_passes_and_is_reported(self):
        snap = snapshot(FLOW + [COURTESY], states=["completed"] * 5 + ["queued"])
        out = self.check(snap, live=True)
        self.assertEqual(out["chatter"], [("result", ARCHITECT, REVIEWER, "queued")])

    def test_fake_mode_still_refuses_any_extra_message(self):
        snap = snapshot(FLOW + [COURTESY], states=["completed"] * 5 + ["queued"])
        self.assertIn("unexpected messages beside the outcome flow", self.refuse(snap, live=False))

    def test_chatter_before_the_flow_ends_is_allowed_by_position(self):
        snap = snapshot(FLOW[:2] + [COURTESY] + FLOW[2:], states=["completed"] * 2 + ["queued"] + ["completed"] * 3)
        self.assertEqual(self.check(snap, live=True)["chatter"], [("result", ARCHITECT, REVIEWER, "queued")])

    def test_a_replayed_step_is_not_chatter(self):
        replay = ("result", REVIEWER, ARCHITECT)
        snap = snapshot(FLOW + [replay], states=["completed"] * 5 + ["queued"])
        self.assertIn("sent twice", self.refuse(snap, live=True))

    def test_a_missing_step_fails_even_with_chatter_to_fill_the_count(self):
        snap = snapshot(FLOW[:4] + [COURTESY], states=["completed"] * 5)
        self.assertIn("does not contain", self.refuse(snap, live=True))

    def test_an_unverified_write_fails_the_slice(self):
        """ADR 0004: the slice runs on the shipped default, so every write in
        it comes from a bound session."""
        snap = snapshot(FLOW, asserted_writes=["message.sent"])
        self.assertIn("unverified writes reached the bus", self.refuse(snap, live=True))

    def test_every_agent_must_be_bound(self):
        self.assertIn("bound terminal", self.refuse(snapshot(FLOW, bindings=2), live=True))

    def test_an_identity_refusal_anywhere_fails_the_slice(self):
        snap = snapshot(FLOW)
        snap["event_kinds"].append("session.identity_refused")
        self.assertIn("named an agent it was not bound to", self.refuse(snap, live=True))

    def test_the_flow_must_be_read_to_the_end(self):
        snap = snapshot(FLOW, states=["completed"] * 4 + ["acknowledged"])
        self.assertIn("not all completed", self.refuse(snap, live=True))

    def test_a_failed_chatter_delivery_is_a_bus_defect(self):
        for state in ("dead_letter", "retryable_failed"):
            with self.subTest(state=state):
                snap = snapshot(FLOW + [COURTESY], states=["completed"] * 5 + [state])
                self.assertIn("beside the outcome flow failed", self.refuse(snap, live=True))

    def test_recorded_live_run_of_2026_09_03(self):
        """The exact message and delivery set of the approved live run."""
        snap = snapshot(FLOW + [COURTESY], states=["completed"] * 5 + ["queued"], correlation="msg_92e94a57dd0647ac85458439840ce11b")
        for message in snap["messages"]:
            message["correlation_id"] = "msg_92e94a57dd0647ac85458439840ce11b"
        out = e2e.assert_outcome(snap, self.daemon, self.ws, "msg_92e94a57dd0647ac85458439840ce11b", live=True)
        self.assertEqual(out["daemon_pids"], [11, 22])
        self.assertEqual(len(out["chatter"]), 1)


if __name__ == "__main__":
    unittest.main()

"""M3 security fixtures: cross-worktree isolation, stale-identity refusal,
approval provenance, path containment, secret redaction, and bounded input.
Runs inside the daemon suite and on its own under ``./test.sh
--agent-bus-security``."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import inspect
import io
import json
import os
import pty
import re
import select
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from luciazero_agentd import (
    ApprovalRefused,
    ConflictError,
    NotFound,
    Store,
    UnsafeReference,
    ValidationError,
    WorktreeMismatch,
)
from luciazero_agentd import __main__ as cli
from luciazero_agentd import store as store_module
from luciazero_agentd.redact import Redactor, find_credential_url
from luciazero_agentd.server import TOOLS, BusServer
from tests.fixtures import commit_file, git, make_repo
from tests.test_mcp import Http

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
NONCE_RE = re.compile(r"lzap_[0-9a-f]{32}")


class SecurityCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-sec-")
        self.tmp = Path(os.path.realpath(self._tmp.name))  # worktree records hold real paths
        self.db = str(self.tmp / "bus.sqlite3")
        self.store = Store.open(self.db)
        self.store.migrate()
        self.store.register_agent("codex-architect", provider="codex", role="architect")
        self.store.register_agent("claude-reviewer", provider="claude", role="reviewer")
        self.repo_a = make_repo(self.tmp / "a")
        self.repo_b = make_repo(self.tmp / "b")

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def events_text(self) -> str:
        return json.dumps(self.store.events(limit=500), default=str)

    def raw_dump(self) -> str:
        """Everything in the database file, for 'never stored' assertions."""
        conn = sqlite3.connect(self.db)
        try:
            return "\n".join(conn.iterdump())
        finally:
            conn.close()


class WorktreeIsolation(SecurityCase):
    def test_bind_records_identity_and_refresh_tracks_head_and_dirty(self) -> None:
        record = self.store.bind_worktree("claude-reviewer", self.repo_a)
        self.assertEqual(record["path"], self.repo_a)
        self.assertEqual(record["branch"], "main")
        self.assertEqual(record["head_oid"], git(self.repo_a, "rev-parse", "HEAD"))
        self.assertEqual(record["base_oid"], record["head_oid"])
        self.assertEqual(record["repo_id"], git(self.repo_a, "rev-list", "--max-parents=0", "HEAD"))
        self.assertFalse(record["dirty"])
        (Path(self.repo_a) / "README.md").write_text("changed\n", encoding="utf-8")
        new_head = commit_file(self.repo_a, "notes.md", "n\n")
        (Path(self.repo_a) / "scratch.txt").write_text("wip\n", encoding="utf-8")
        task = self.store.create_task(title="t", created_by="codex-architect")
        self.store.claim_task(task["id"], "claude-reviewer")  # verifies and refreshes
        refreshed = self.store.get_worktree("claude-reviewer")
        self.assertEqual(refreshed["head_oid"], new_head)
        self.assertTrue(refreshed["dirty"])
        self.assertGreater(refreshed["verified_at"], record["verified_at"])

    def test_concurrent_writers_never_share_a_worktree(self) -> None:
        self.store.bind_worktree("codex-architect", self.repo_a)
        with self.assertRaises(ConflictError) as ctx:
            self.store.bind_worktree("claude-reviewer", self.repo_a)
        self.assertIn("owned by 'codex-architect'", str(ctx.exception))
        link = self.tmp / "link-to-a"
        os.symlink(self.repo_a, link)
        with self.assertRaises(ConflictError):
            self.store.bind_worktree("claude-reviewer", str(link))  # resolves to the same toplevel
        with self.assertRaises(ConflictError):
            self.store.bind_worktree("claude-reviewer", os.path.join(self.repo_a, "reports"))  # subdirectory, same toplevel
        self.assertEqual(self.store.bind_worktree("claude-reviewer", self.repo_b)["path"], self.repo_b)
        # Rebinding your own worktree is an upsert, not a conflict.
        self.assertEqual(self.store.bind_worktree("codex-architect", self.repo_a)["path"], self.repo_a)
        # Moving to a worktree someone else holds is refused too.
        with self.assertRaises(ConflictError):
            self.store.bind_worktree("codex-architect", self.repo_b)

    def test_stale_branch_refuses_claim_until_restored(self) -> None:
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        task = self.store.create_task(title="write", created_by="codex-architect", requires_worktree=True)
        git(self.repo_a, "checkout", "-q", "-b", "elsewhere")
        with self.assertRaises(WorktreeMismatch) as ctx:
            self.store.claim_task(task["id"], "claude-reviewer")
        self.assertIn("branch is now 'elsewhere'", str(ctx.exception))
        self.assertEqual(self.store.get_task(task["id"])["state"], "open")
        self.assertIn('"worktree.mismatch"', self.events_text())
        git(self.repo_a, "checkout", "-q", "main")
        self.assertEqual(self.store.claim_task(task["id"], "claude-reviewer")["state"], "claimed")

    def test_vanished_worktree_refuses_publish_but_allows_blocked(self) -> None:
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        task = self.store.create_task(title="write", created_by="codex-architect", requires_worktree=True)
        self.store.claim_task(task["id"], "claude-reviewer")
        shutil.rmtree(self.repo_a)
        with self.assertRaises(WorktreeMismatch) as ctx:
            self.store.publish_artifact(kind="report", ref="reports/x.md", produced_by="claude-reviewer", task_id=task["id"])
        self.assertIn("unusable", str(ctx.exception))
        blocked = self.store.complete_task(task["id"], "claude-reviewer", outcome="blocked", result={"reason": "worktree gone"})
        self.assertEqual(blocked["state"], "blocked")

    def test_repository_identity_change_at_the_same_path_is_refused(self) -> None:
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        task = self.store.create_task(title="write", created_by="codex-architect", requires_worktree=True)
        shutil.rmtree(self.repo_a)
        make_repo(self.repo_a)  # same path, same branch name, different root commit
        with self.assertRaises(WorktreeMismatch) as ctx:
            self.store.claim_task(task["id"], "claude-reviewer")
        self.assertIn("repository identity changed", str(ctx.exception))

    def test_tasks_that_need_a_worktree_refuse_agents_without_one(self) -> None:
        needs = self.store.create_task(title="write", created_by="codex-architect", requires_worktree=True)
        plain = self.store.create_task(title="read", created_by="codex-architect")
        with self.assertRaises(ConflictError) as ctx:
            self.store.claim_task(needs["id"], "claude-reviewer")
        self.assertIn("needs a bound worktree", str(ctx.exception))
        self.assertEqual(self.store.claim_task(plain["id"], "claude-reviewer")["state"], "claimed")
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        self.assertEqual(self.store.claim_task(needs["id"], "claude-reviewer")["state"], "claimed")
        self.assertTrue(self.store.get_task(needs["id"])["requires_worktree"])

    def test_rebinding_elsewhere_while_holding_worktree_work_is_refused(self) -> None:
        # Review finding: an unconditional upsert let a stale worker finish a
        # worktree-bound task against an unrelated checkout.
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        task = self.store.create_task(title="write", created_by="codex-architect", requires_worktree=True)
        self.store.claim_task(task["id"], "claude-reviewer")
        with self.assertRaises(ConflictError) as ctx:
            self.store.bind_worktree("claude-reviewer", self.repo_b)
        self.assertIn("complete or block them before binding another worktree", str(ctx.exception))
        self.assertEqual(self.store.get_worktree("claude-reviewer")["path"], self.repo_a)
        self.assertEqual(self.store.bind_worktree("claude-reviewer", self.repo_a)["path"], self.repo_a)  # same place: fine
        self.store.complete_task(task["id"], "claude-reviewer", outcome="blocked", result={"reason": "moving"})
        self.assertEqual(self.store.bind_worktree("claude-reviewer", self.repo_b)["path"], self.repo_b)
        bound = [e for e in self.store.events(limit=500) if e["kind"] == "worktree.bound"]
        self.assertEqual(bound[-1]["payload"]["previous_path"], self.repo_a)

    def test_bind_rejects_what_is_not_a_usable_worktree(self) -> None:
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(ValidationError):
            self.store.bind_worktree("claude-reviewer", str(plain))
        with self.assertRaises(ValidationError):
            self.store.bind_worktree("claude-reviewer", "relative/path")
        with self.assertRaises(ValidationError):
            self.store.bind_worktree("claude-reviewer", str(self.tmp / "missing"))
        with self.assertRaises(ValidationError):
            self.store.bind_worktree("claude-reviewer", self.repo_a, base="-oops")
        with self.assertRaises(ValidationError):
            self.store.bind_worktree("claude-reviewer", self.repo_a, base="no-such-ref")
        git(self.repo_a, "checkout", "-q", "--detach")
        with self.assertRaises(ValidationError) as ctx:
            self.store.bind_worktree("claude-reviewer", self.repo_a)
        self.assertIn("detached HEAD", str(ctx.exception))
        with self.assertRaises(NotFound):
            self.store.get_worktree("claude-reviewer")


class ArtifactContainment(SecurityCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        self.task = self.store.create_task(title="review", created_by="codex-architect")
        self.store.claim_task(self.task["id"], "claude-reviewer")

    def publish(self, ref: str, kind: str = "report", **extra: object) -> dict:
        return self.store.publish_artifact(kind=kind, ref=ref, produced_by="claude-reviewer", task_id=self.task["id"], **extra)

    def test_unsafe_paths_are_refused(self) -> None:
        outside = self.tmp / "outside.md"
        outside.write_text("secret\n", encoding="utf-8")
        for ref in ("../outside.md", "/etc/hosts", "reports/../../outside.md", ".git/config", ".git/HEAD", "reports/", "./reports/x.md",
                    "~/x.md", "https://user:pw@example.invalid/repo.git", "ssh://git@example.invalid/x", "reports/missing.md", "reports"):
            with self.assertRaises(UnsafeReference, msg=ref):
                self.publish(ref)
        self.assertEqual(self.store.counts()["artifacts"], 0)

    def test_symlinks_are_refused_even_when_they_stay_inside(self) -> None:
        repo = Path(self.repo_a)
        os.symlink(repo / "README.md", repo / "reports" / "inside-link.md")
        with self.assertRaises(UnsafeReference) as ctx:
            self.publish("reports/inside-link.md")
        self.assertIn("symlink", str(ctx.exception))
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "secret.txt").write_text("s\n", encoding="utf-8")
        os.symlink(elsewhere, repo / "ext")
        with self.assertRaises(UnsafeReference):
            self.publish("ext/secret.txt")

    def test_regular_file_gets_a_daemon_computed_digest(self) -> None:
        expected = hashlib.sha256((Path(self.repo_a) / "reports" / "x.md").read_bytes()).hexdigest()
        with self.assertRaises(ValidationError):
            self.publish("reports/x.md", sha256="0" * 64)
        record = self.publish("reports/x.md")
        self.assertEqual(record["sha256"], expected)
        self.assertEqual(self.publish("reports/x.md", sha256=expected)["sha256"], expected)
        self.assertIn('"bytes": 9', self.events_text())

    def test_oversized_files_are_refused(self) -> None:
        original = store_module.MAX_ARTIFACT_BYTES
        store_module.MAX_ARTIFACT_BYTES = 4
        try:
            with self.assertRaises(UnsafeReference) as ctx:
                self.publish("reports/x.md")
            self.assertIn("cap is 4", str(ctx.exception))
        finally:
            store_module.MAX_ARTIFACT_BYTES = original

    def test_commit_refs_must_exist_in_the_bound_worktree(self) -> None:
        head = git(self.repo_a, "rev-parse", "HEAD")
        self.assertEqual(self.publish(head, kind="commit")["ref"], head)
        foreign = git(self.repo_b, "rev-parse", "HEAD")  # a different clone: its objects are not here
        with self.assertRaises(ConflictError):
            self.publish(foreign, kind="commit")
        with self.assertRaises(ConflictError):
            self.publish("f" * 40, kind="commit")
        for ref in ("HEAD", "main", head[:12], "https://user:pw@example.invalid/x.git"):
            with self.assertRaises(UnsafeReference, msg=ref):
                self.publish(ref, kind="commit")

    def test_publishing_needs_a_bound_worktree(self) -> None:
        with self.assertRaises(ConflictError) as ctx:
            self.store.publish_artifact(kind="report", ref="reports/x.md", produced_by="codex-architect")
        self.assertIn("needs a bound worktree", str(ctx.exception))

    def test_git_metadata_is_refused_in_any_spelling_or_depth(self) -> None:
        # Review finding: only an exact-case leading ".git" was refused, so
        # ".GIT/config" published on a case-insensitive filesystem.
        nested = Path(self.repo_a) / "vendor" / "nested"
        make_repo(nested)
        for ref in (".GIT/config", ".Git/HEAD", ".git/config", "vendor/nested/.git/config", "vendor/nested/.GIT/HEAD"):
            with self.assertRaises(UnsafeReference, msg=ref) as ctx:
                self.publish(ref)
            self.assertIn(".git", str(ctx.exception))
        self.assertEqual(self.store.counts()["artifacts"], 0)

    def test_linked_worktree_binds_and_publishes_but_never_its_gitdir(self) -> None:
        linked = str(self.tmp / "linked")
        git(self.repo_a, "worktree", "add", "-q", "-b", "feature", linked)
        linked = os.path.realpath(linked)
        self.assertTrue(os.path.isfile(os.path.join(linked, ".git")))  # gitdir pointer file, not a directory
        record = self.store.bind_worktree("codex-architect", linked)
        self.assertEqual((record["branch"], record["repo_id"]), ("feature", self.store.get_worktree("claude-reviewer")["repo_id"]))
        published = self.store.publish_artifact(kind="report", ref="reports/x.md", produced_by="codex-architect")
        self.assertRegex(published["sha256"], r"^[0-9a-f]{64}$")
        with self.assertRaises(UnsafeReference):
            self.store.publish_artifact(kind="report", ref=".git", produced_by="codex-architect")

    def test_secret_bearing_refs_and_contents_are_refused(self) -> None:
        # Review finding: a nonce travelled through an artifact's file name
        # and its content because only the digest was computed.
        nonce = "lzap_" + "a" * 32
        repo = Path(self.repo_a)
        (repo / "reports" / f"{nonce}.md").write_text("x\n", encoding="utf-8")
        with self.assertRaises(ValidationError) as ctx:
            self.publish(f"reports/{nonce}.md")
        self.assertNotIn(nonce, str(ctx.exception))
        for name, content in (
            ("reports/handoff.md", f"approved, use {nonce}\n"),
            ("reports/run.log", "Authorization: Bearer abcDEF123456789xyz\n"),
            ("reports/creds.txt", "ghp_" + "A" * 36 + "\n"),
            ("reports/clone.sh", "git clone https://me:tok3n@github.com/x/y.git\n"),
        ):
            (repo / name).write_text(content, encoding="utf-8")
            with self.assertRaises(UnsafeReference, msg=name) as ctx:
                self.publish(name)
            self.assertIn("secret-shaped", str(ctx.exception))
            self.assertNotIn(nonce, str(ctx.exception))
            self.assertNotIn("tok3n", str(ctx.exception))
        # Ordinary code and prose in a patch must still publish (heuristic tier never refuses).
        (repo / "reports" / "fix.patch").write_text("+    token = request.headers.get('x')\n+    # password: required for login\n", encoding="utf-8")
        self.assertEqual(self.publish("reports/fix.patch", kind="patch")["ref"], "reports/fix.patch")
        self.assertEqual(self.store.counts()["artifacts"], 1)
        self.assertNotIn(nonce, self.raw_dump())

    def test_commit_refs_carry_no_caller_digest(self) -> None:
        head = git(self.repo_a, "rev-parse", "HEAD")
        with self.assertRaises(ValidationError):
            self.publish(head, kind="commit", sha256="f" * 64)
        self.assertIsNone(self.publish(head, kind="commit")["sha256"])


class ApprovalProvenance(SecurityCase):
    def setUp(self) -> None:
        super().setUp()
        self.task = self.store.create_task(title="ship it", created_by="codex-architect")
        self.store.claim_task(self.task["id"], "claude-reviewer")

    def grant(self, operation: str = "delete", **kw: object) -> str:
        _, nonce = self.store.grant_approval(self.task["id"], operation, granted_by="human:test", **kw)
        return nonce

    def test_nonce_shape_and_only_its_hash_is_stored(self) -> None:
        nonce = self.grant()
        self.assertRegex(nonce, r"^lzap_[0-9a-f]{32}$")
        dump = self.raw_dump()
        self.assertNotIn(nonce, dump)
        self.assertIn(hashlib.sha256(nonce.encode()).hexdigest(), dump)
        self.assertNotIn("nonce_hash", json.dumps(self.store.pending_approvals()))
        record = self.store.consume_approval(self.task["id"], "delete", nonce, "claude-reviewer")
        self.assertNotIn("nonce_hash", record)
        self.assertEqual(record["consumed_by"], "claude-reviewer")
        self.assertNotIn(nonce, self.events_text())

    def test_only_the_claim_holder_can_consume(self) -> None:
        nonce = self.grant()
        with self.assertRaises(ApprovalRefused) as ctx:
            self.store.consume_approval(self.task["id"], "delete", nonce, "codex-architect")
        self.assertIn("does not hold the task claim", str(ctx.exception))
        self.assertEqual(len(self.store.pending_approvals()), 1)
        self.store.consume_approval(self.task["id"], "delete", nonce, "claude-reviewer")
        with self.assertRaises(ApprovalRefused) as ctx:
            self.store.consume_approval(self.task["id"], "delete", nonce, "claude-reviewer")
        self.assertIn("already used", str(ctx.exception))
        self.assertEqual(self.store.pending_approvals(), [])
        self.assertIn('"approval.refused"', self.events_text())

    def test_bound_to_one_task_and_one_operation(self) -> None:
        nonce = self.grant("delete")
        with self.assertRaises(ApprovalRefused) as ctx:
            self.store.consume_approval(self.task["id"], "force_push", nonce, "claude-reviewer")
        self.assertIn("different task or operation", str(ctx.exception))
        other = self.store.create_task(title="other", created_by="codex-architect")
        self.store.claim_task(other["id"], "claude-reviewer")
        with self.assertRaises(ApprovalRefused):
            self.store.consume_approval(other["id"], "delete", nonce, "claude-reviewer")
        with self.assertRaises(ApprovalRefused) as ctx:
            self.store.consume_approval(self.task["id"], "delete", "lzap_" + "0" * 32, "claude-reviewer")
        self.assertIn("no such approval", str(ctx.exception))
        with self.assertRaises(ValidationError) as bad:
            self.store.consume_approval(self.task["id"], "delete", "please-approve", "claude-reviewer")
        self.assertNotIn("please-approve", str(bad.exception))
        self.assertEqual(self.store.consume_approval(self.task["id"], "delete", nonce, "claude-reviewer")["operation"], "delete")

    def test_expired_nonce_is_refused(self) -> None:
        nonce = self.grant(ttl_seconds=1)
        time.sleep(1.2)
        with self.assertRaises(ApprovalRefused) as ctx:
            self.store.consume_approval(self.task["id"], "delete", nonce, "claude-reviewer")
        self.assertIn("expired", str(ctx.exception))
        self.assertEqual(self.store.pending_approvals(), [])

    def test_approvals_attach_only_to_open_or_claimed_tasks(self) -> None:
        self.store.complete_task(self.task["id"], "claude-reviewer")
        with self.assertRaises(ConflictError):
            self.grant()
        with self.assertRaises(NotFound):
            self.store.grant_approval("tsk_missing", "delete", granted_by="human:test")

    def test_a_forwarded_nonce_is_scrubbed_from_messages_tasks_and_results(self) -> None:
        nonce = self.grant()
        sent = self.store.send_message(sender="claude-reviewer", recipient="codex-architect", kind="decision",
                                       payload={"nonce": nonce, "note": f"go ahead, use {nonce} now", "nested": [nonce]})
        self.assertEqual(sent["payload"]["nonce"], "[redacted:approval-nonce]")
        self.assertEqual(sent["payload"]["note"], "go ahead, use [redacted:approval-nonce] now")
        self.assertEqual(sent["payload"]["nested"], ["[redacted:approval-nonce]"])
        task = self.store.create_task(title=f"approved with {nonce}", created_by="codex-architect", payload={"n": nonce})
        self.assertNotIn(nonce, task["title"])
        self.assertNotIn(nonce, json.dumps(task["payload"]))
        done = self.store.complete_task(self.task["id"], "claude-reviewer", result={"nonce": nonce})
        self.assertNotIn(nonce, json.dumps(done["result"]))
        # Review finding: keys and id-shaped fields were side channels.
        keyed = self.store.send_message(sender="claude-reviewer", recipient="codex-architect", kind="decision", payload={nonce: "use this"})
        self.assertEqual(list(keyed["payload"]), ["[redacted:approval-nonce]"])
        for attempt in (
            lambda: self.store.send_message(sender="claude-reviewer", recipient="codex-architect", kind="decision", payload={}, correlation_id=nonce),
            lambda: self.store.send_message(sender="claude-reviewer", recipient="codex-architect", kind="decision", payload={}, idempotency_key=nonce),
            lambda: self.store.create_task(title="t", created_by="codex-architect", idempotency_key=nonce),
            lambda: self.store.register_agent(nonce, provider="other", role="mule"),
            lambda: self.store.publish_artifact(kind="report", ref=f"reports/{nonce}.md", produced_by="claude-reviewer"),
        ):
            with self.assertRaises(ValidationError) as refused:
                attempt()
            self.assertNotIn(nonce, str(refused.exception))
        mule = self.store.register_agent("mule", provider="other", role=f"carrier of {nonce}", capabilities=[nonce, "review"])
        self.assertEqual(mule["role"], "carrier of [redacted:approval-nonce]")
        self.assertEqual(mule["capabilities"], ["[redacted:approval-nonce]", "review"])
        self.assertNotIn(nonce, self.raw_dump())
        # The real nonce, handed over outside the bus, still works exactly once.
        self.store.claim_task(task["id"], "claude-reviewer")
        _, fresh = self.store.grant_approval(task["id"], "deploy", granted_by="human:test")
        self.assertEqual(self.store.consume_approval(task["id"], "deploy", fresh, "claude-reviewer")["operation"], "deploy")

    def test_no_mcp_tool_can_create_an_approval(self) -> None:
        names = {t["name"] for t in TOOLS}
        self.assertEqual({n for n in names if "approv" in n}, {"approval_consume"})
        for tool in TOOLS:
            source = inspect.getsource(tool["handler"])
            self.assertNotIn("grant_approval", source, tool["name"])
        _, credential = self.store.bind_terminal("claude-reviewer", provider="claude", by="human:test")
        # Legacy mode is on, and spending an approval is still refused without
        # a bound terminal: an unverified session must never spend one (M4.5).
        with BusServer(self.db, "test-token-0123456789abcdef", port=0, allow_unattributed=True) as server:
            unverified = Http(server.url, "test-token-0123456789abcdef")
            unverified.initialize()
            blocked = unverified.call("approval_consume", {"task_id": self.task["id"], "operation": "delete", "nonce": "lzap_" + "a" * 32, "agent_id": "claude-reviewer"})
            self.assertTrue(blocked["isError"])
            self.assertIn("IdentityRequired", blocked["content"][0]["text"])

            client = Http(server.url, credential)
            client.initialize()
            refused = client.call("approval_consume", {"task_id": self.task["id"], "operation": "delete", "nonce": "lzap_" + "a" * 32, "agent_id": "claude-reviewer"})
            self.assertTrue(refused["isError"])
            self.assertIn("ApprovalRefused", refused["content"][0]["text"])
            shaped = client.call("approval_consume", {"task_id": self.task["id"], "operation": "delete", "nonce": "not-a-nonce", "agent_id": "claude-reviewer"})
            self.assertTrue(shaped["isError"])
            self.assertIn("invalid_arguments", shaped["content"][0]["text"])
        self.assertEqual(self.store.pending_approvals(), [])


def run_in_pty(args: list[str], answer: str, env: dict[str, str], timeout: float = 60) -> tuple[int, str]:
    """Run ``args`` on a pseudo-terminal, type ``answer``, return (exit, output)."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=PACKAGE_ROOT, close_fds=True)
    os.close(slave)
    os.write(master, answer.encode("utf-8"))
    output = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO once the child closed its end (Linux)
                break
            if not chunk:
                break
            output += chunk
        elif proc.poll() is not None:
            break
    code = proc.wait(timeout=10)
    os.close(master)
    return code, output.decode("utf-8", errors="replace")


class ApprovalCli(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-approve-")
        self.state = self._tmp.name
        with Store.open(Path(self.state) / "bus.sqlite3") as store:
            store.migrate()
            store.register_agent("codex-architect", provider="codex", role="architect")
            store.register_agent("claude-reviewer", provider="claude", role="reviewer")
            self.task = store.create_task(title="drop the old table", created_by="codex-architect")
            store.claim_task(self.task["id"], "claude-reviewer")
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(PACKAGE_ROOT), TERM="dumb")
        self.args = [sys.executable, "-m", "luciazero_agentd", "approve", self.task["id"], "delete", "--state-dir", self.state]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def pending(self) -> list:
        with Store.open(Path(self.state) / "bus.sqlite3") as store:
            return store.pending_approvals()

    def test_non_interactive_input_is_refused(self) -> None:
        result = subprocess.run(self.args, input="y\n", capture_output=True, text=True, env=self.env, cwd=PACKAGE_ROOT, timeout=60)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("non-interactive", result.stderr)
        self.assertNotRegex(result.stdout + result.stderr, NONCE_RE)
        self.assertEqual(self.pending(), [])

    def test_interactive_grant_prints_the_nonce_once(self) -> None:
        code, output = run_in_pty(self.args, "y\n", self.env)
        self.assertEqual(code, 0, output)
        self.assertIn("drop the old table", output)
        nonces = NONCE_RE.findall(output)
        self.assertEqual(len(set(nonces)), 1, output)
        nonce = nonces[0]
        approvals = self.pending()
        self.assertEqual(len(approvals), 1)
        self.assertEqual((approvals[0]["task_id"], approvals[0]["operation"]), (self.task["id"], "delete"))
        self.assertTrue(approvals[0]["granted_by"].startswith("human:"))
        with Store.open(Path(self.state) / "bus.sqlite3") as store:
            self.assertEqual(store.consume_approval(self.task["id"], "delete", nonce, "claude-reviewer")["id"], approvals[0]["id"])

    def test_declining_creates_nothing(self) -> None:
        code, output = run_in_pty(self.args, "n\n", self.env)
        self.assertEqual(code, 1, output)
        self.assertIn("not approved", output)
        self.assertEqual(self.pending(), [])

    def test_eof_at_the_prompt_declines_cleanly(self) -> None:
        code, output = run_in_pty(self.args, "\x04", self.env)  # Ctrl-D
        self.assertEqual(code, 1, output)
        self.assertIn("not approved", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(self.pending(), [])

    def test_unknown_task_and_operation(self) -> None:
        code, output = run_in_pty([*self.args[:4], "tsk_nope", "delete", "--state-dir", self.state], "y\n", self.env)
        self.assertEqual(code, 2, output)
        bad_op = subprocess.run([*self.args[:5], "rm-rf", "--state-dir", self.state], capture_output=True, text=True, env=self.env, cwd=PACKAGE_ROOT, timeout=60)
        self.assertEqual(bad_op.returncode, 2)
        self.assertIn("invalid choice", bad_op.stderr)


class SecretRedaction(unittest.TestCase):
    SAMPLES = (
        ("Authorization: Bearer abcDEF123456789xyz", "Authorization: Bearer [redacted]"),
        ("authorization: bearer abcdefghijklmnopqrstuvwxyz", "Authorization: Bearer [redacted]"),  # header context: no digit needed
        ("Bearer abcdefghijklmnopqrstuvwxyz", "Bearer abcdefghijklmnopqrstuvwxyz"),  # accepted false negative (ADR 0003)
        ("token lzap_0123456789abcdef0123456789abcdef", "token [redacted:approval-nonce]"),
        ("key AKIAIOSFODNN7EXAMPLE here", "key [redacted:aws-key] here"),
        ("ghp_" + "A" * 36, "[redacted:github-token]"),
        ("github_pat_" + "B" * 30, "[redacted:github-token]"),
        ("sk-ant-" + "c" * 26 + "1234", "[redacted:api-key]"),
        ("sk-" + "c" * 30, "sk-" + "c" * 30),  # no digit: an identifier, not a key
        ("xoxb-123456789012-abcdef", "[redacted:slack-token]"),
        ("git clone https://user:s3cret@github.com/x/y.git", "git clone https://[redacted]@github.com/x/y.git"),
        ("password=hunter2hunter2", "password=[redacted]"),
        ('api_key: "abcdefghij1"', 'api_key: "[redacted]"'),
        ("access_token=eyJabc123def456", "access_token=[redacted]"),
        ("GITHUB_TOKEN=ghx1234567890", "GITHUB_TOKEN=[redacted]"),
        ("export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI7K", "export AWS_SECRET_ACCESS_KEY=[redacted]"),
        ("client_secret: 'ab12cd34ef'", "client_secret: '[redacted]'"),
        ("redis://:pw123@host/0", "redis://[redacted]@host/0"),
        ("HTTPS://user:pw1@host/x", "HTTPS://[redacted]@host/x"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----", "[redacted:private-key]"),
        # Review findings: prose, identifiers and ordinary code must survive.
        ("idempotency_key=t1 is fine", "idempotency_key=t1 is fine"),
        ("the bearer credentials keep other users out", "the bearer credentials keep other users out"),
        ("password: required for login", "password: required for login"),
        ("feature/sk-implement-login-page-redesign", "feature/sk-implement-login-page-redesign"),
        ("token = request.headers.get(name)", "token = request.headers.get(name)"),
        ("no secrets here", "no secrets here"),
    )

    def test_patterns(self) -> None:
        redactor = Redactor()
        for raw, expected in self.SAMPLES:
            scrubbed, count = redactor.text(raw)
            self.assertEqual(scrubbed, expected)
            self.assertEqual(count > 0, raw != expected, raw)

    def test_literals_and_json_walk(self) -> None:
        redactor = Redactor(["my-daemon-token-value", "short"])
        scrubbed, count = redactor.json({"a": "x my-daemon-token-value y", "b": ["short is too short to count", {"c": "ghp_" + "Z" * 36}], "n": 3})
        self.assertEqual(scrubbed, {"a": "x [redacted] y", "b": ["short is too short to count", {"c": "[redacted:github-token]"}], "n": 3})
        self.assertEqual(count, 2)

    def test_json_keys_and_secret_named_keys(self) -> None:
        nonce = "lzap_" + "0" * 32
        scrubbed, count = Redactor().json({nonce: "use this", "password": "hunter2hunter2", "GITHUB_TOKEN": "plainlooking", "note": "ok", "short_secret": "abc", "nested": {"client_secret": "x" * 12}})
        self.assertEqual(scrubbed, {"[redacted:approval-nonce]": "use this", "password": "[redacted]", "GITHUB_TOKEN": "[redacted]", "note": "ok", "short_secret": "abc", "nested": {"client_secret": "[redacted]"}})
        self.assertEqual(count, 4)

    def test_scan_reports_strict_shapes_only(self) -> None:
        redactor = Redactor(["my-daemon-token-value"])
        self.assertEqual(redactor.scan("nothing"), [])
        self.assertEqual(redactor.scan("token = request.headers.get(name)"), [])  # heuristic tier never refuses
        self.assertEqual(sorted(redactor.scan("lzap_" + "a" * 32 + " and my-daemon-token-value")), ["approval-nonce", "daemon-token"])
        self.assertEqual(redactor.scan("https://u:p1@h/x"), ["url-credential"])

    def test_large_hyphenated_payload_stays_linear(self) -> None:
        blob = "a-" * (32 * 1024)
        started = time.monotonic()
        Redactor().text(blob)
        find_credential_url(blob)
        self.assertLess(time.monotonic() - started, 1.0)


class StoreAndServerRedaction(SecurityCase):
    def test_payloads_titles_results_and_events_are_scrubbed(self) -> None:
        payload = {"log": "Authorization: Bearer abcDEF123456789xyz", "aws": "AKIAIOSFODNN7EXAMPLE", "pem": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----", "list": ["password=hunter2hunter2"]}
        sent = self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="finding", payload=payload)
        self.assertEqual(sent["payload"]["log"], "Authorization: Bearer [redacted]")
        self.assertEqual(sent["payload"]["aws"], "[redacted:aws-key]")
        self.assertEqual(sent["payload"]["pem"], "[redacted:private-key]")
        self.assertEqual(sent["payload"]["list"], ["password=[redacted]"])
        task = self.store.create_task(title="rotate ghp_" + "Q" * 36, created_by="codex-architect", payload={"k": "xoxb-123456789012-abcdef"})
        self.assertEqual(task["title"], "rotate [redacted:github-token]")
        self.store.claim_task(task["id"], "claude-reviewer")
        done = self.store.complete_task(task["id"], "claude-reviewer", result={"out": "sk-" + "d" * 26 + "9876"})
        self.assertEqual(done["result"]["out"], "[redacted:api-key]")
        dump = self.raw_dump()
        for secret in ("abcDEF123456789xyz", "AKIAIOSFODNN7EXAMPLE", "hunter2hunter2", "Q" * 36, "xoxb-", "d" * 26 + "9876"):
            self.assertNotIn(secret, dump)
        events = self.store.events(limit=100)
        self.assertEqual([e["payload"]["redactions"] for e in events if e["kind"] == "message.sent"], [4])

    def test_credential_bearing_urls_are_refused_not_stored(self) -> None:
        for call in (
            lambda: self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="task", payload={"repo": "https://me:tok3n@github.com/x/y.git"}),
            lambda: self.store.create_task(title="clone", created_by="codex-architect", payload={"nested": {"url": "ssh://user:pw@host/x"}}),
        ):
            with self.assertRaises(UnsafeReference) as ctx:
                call()
            self.assertNotIn("tok3n", str(ctx.exception))
            self.assertNotIn("pw@", str(ctx.exception))
        self.assertEqual(self.store.counts()["messages"], 0)
        self.assertEqual(self.store.counts()["tasks"], 0)

    def test_server_scrubs_error_messages_and_its_own_token(self) -> None:
        token = "daemon-token-0123456789abcdefXYZ"
        with BusServer(self.db, token, port=0, allow_unattributed=True) as server:
            client = Http(server.url, token)
            client.initialize()
            looks_like_a_token = "ghp_" + "R" * 36
            error = client.call("agent_heartbeat", {"agent_id": looks_like_a_token})
            self.assertTrue(error["isError"])  # strict shape in an id: refused, never echoed
            self.assertNotIn(looks_like_a_token, error["content"][0]["text"])
            self.assertIn("secret-shaped", error["content"][0]["text"])
            echoed = client.call("agent_heartbeat", {"agent_id": "password=hunter2hunter2"})
            self.assertTrue(echoed["isError"])  # shape error echoes the value: scrubbed on the way out
            self.assertNotIn("hunter2hunter2", echoed["content"][0]["text"])
            self.assertIn("password=[redacted]", echoed["content"][0]["text"])
            task = client.call("task_create", {"title": f"leak {token} here", "created_by": "codex-architect"})["structuredContent"]
            self.assertEqual(task["title"], "leak [redacted] here")
            self.assertNotIn(token, json.dumps(client.call("task_list", {})))
            status, _, body = client.raw(b"", method="GET", path="/status")
            self.assertEqual(status, 200)
            self.assertNotIn(token, body.decode("utf-8"))

    def test_daemon_token_is_refused_in_every_id_channel(self) -> None:
        # Review finding: ids were checked against the pattern-only redactor,
        # so the daemon token (no fixed shape) went into correlation_id and
        # idempotency_key raw.
        token = "daemon-token-" + "q" * 30
        store = Store.open(self.db, redact_literals=(token,))
        try:
            self.store.bind_worktree("claude-reviewer", self.repo_a)
            task = self.store.create_task(title="t", created_by="codex-architect")
            self.store.claim_task(task["id"], "claude-reviewer")
            for attempt in (
                lambda: store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="finding", payload={}, correlation_id=token),
                lambda: store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="finding", payload={}, idempotency_key=token),
                lambda: store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="finding", payload={}, reply_to=token),
                lambda: store.create_task(title="t", created_by="codex-architect", idempotency_key=token),
                lambda: store.create_task(title="t", created_by="codex-architect", assigned_to=token),
                lambda: store.register_agent(token, provider="other", role="mule"),
                lambda: store.publish_artifact(kind="report", ref="reports/x.md", produced_by="claude-reviewer", idempotency_key=token),
                lambda: store.publish_artifact(kind="report", ref="reports/x.md", produced_by="claude-reviewer", task_id=token),
                lambda: store.claim_task(token, "claude-reviewer"),
                lambda: store.consume_approval(token, "delete", "lzap_" + "0" * 32, "claude-reviewer"),
            ):
                with self.assertRaises(ValidationError) as refused:
                    attempt()
                self.assertNotIn(token, str(refused.exception))
            # And a peer that pastes it as free text gets it scrubbed.
            self.assertEqual(store.register_agent("mule", provider="other", role=f"holder of {token}")["role"], "holder of [redacted]")
        finally:
            store.close()
        self.assertNotIn(token, self.raw_dump())
        with BusServer(self.db, token, port=0, allow_unattributed=True) as server:
            client = Http(server.url, token)
            client.initialize()
            result = client.call("message_send", {"sender": "codex-architect", "recipient": "claude-reviewer", "kind": "finding", "payload": {}, "correlation_id": token})
            self.assertTrue(result["isError"])
            self.assertNotIn(token, json.dumps(result))
        self.assertNotIn(token, self.raw_dump())

    def test_bounded_input(self) -> None:
        with self.assertRaises(ValidationError):
            self.store.bind_worktree("claude-reviewer", "/" + "a" * 1025)
        with self.assertRaises(ValidationError):
            self.store.send_message(sender="codex-architect", recipient="claude-reviewer", kind="finding", payload={"blob": "x" * (64 * 1024 + 1)})
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        with self.assertRaises(ValidationError):
            self.store.publish_artifact(kind="report", ref="r/" + "x" * 2048, produced_by="claude-reviewer")
        with self.assertRaises(ValidationError):
            self.store.grant_approval("t", "delete", granted_by="human:test", ttl_seconds=0)


class StatusSurface(SecurityCase):
    def test_status_shows_worktrees_and_pending_approvals(self) -> None:
        self.store.bind_worktree("claude-reviewer", self.repo_a)
        task = self.store.create_task(title="ship", created_by="codex-architect", requires_worktree=True)
        self.store.claim_task(task["id"], "claude-reviewer")
        self.store.grant_approval(task["id"], "deploy", granted_by="human:test")
        status = self.store.status()
        reviewer = next(a for a in status["agents"] if a["id"] == "claude-reviewer")
        self.assertEqual(reviewer["worktree"]["branch"], "main")
        self.assertFalse(reviewer["worktree"]["dirty"])
        self.assertIsNone(next(a for a in status["agents"] if a["id"] == "codex-architect")["worktree"])
        self.assertEqual(status["approvals_pending"], 1)
        self.assertNotIn("nonce", json.dumps(status["pending_approvals"]))
        status["server"] = {"name": "luciazero-agentd", "version": "t", "started_at": "now"}
        original = cli._fetch_status
        cli._fetch_status = lambda _state_dir: status
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.cmd_status(argparse.Namespace(state_dir=None, json=False))
        finally:
            cli._fetch_status = original
        self.assertIn("on main", out.getvalue())
        self.assertIn("approvals pending: 1", out.getvalue())


if __name__ == "__main__":
    unittest.main()

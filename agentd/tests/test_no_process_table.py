"""What the commands do where the process table cannot be read.

Every binding this daemon issues is anchored to a pid and its start time, and
both come from `ps`. A sandbox that denies `/bin/ps` therefore takes the floor
out from under `run`, `claim` and `terminal` at once -- and it happens: the
whole `agentd` suite was seen failing with 90 errors and 6 failures inside one
provider's exec sandbox, every one of them a `PermissionError` escaping from a
single denied command.

`procinfo` already turns a missing `ps` and a hung `ps` into `ProcessError`,
which the commands know how to report. A denied one was not on that list, so
it escaped as itself, past every handler, as a traceback. These tests pin the
conversion and, for `run`, that refusing leaves nothing behind: no binding
anyone could still present, no credential on disk, and no provider process.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from luciazero_agentd import procinfo
from luciazero_agentd.statedir import write_endpoint

from tests.test_nudge import make_store

PACKAGE_ROOT = str(Path(__file__).resolve().parents[1])


def deny(*commands: str) -> tuple[str, tempfile.TemporaryDirectory]:
    """A PATH holding nothing but unrunnable copies of `commands`.

    Exactly how a sandbox refuses: the file is found and cannot be executed,
    so `subprocess.run` raises `PermissionError` rather than
    `FileNotFoundError`. The directory is the whole PATH on purpose -- the
    exec search walks past a file it may not run and keeps looking, so a
    shadow in front of the real `/bin/ps` denies nothing.
    """
    tmp = tempfile.TemporaryDirectory(prefix="agentd-denied-bin-")
    for name in commands:
        blocked = Path(tmp.name) / name
        blocked.write_text("#!/bin/sh\nexit 0\n")
        blocked.chmod(0o600)  # readable, never executable
    return tmp.name, tmp


class ConversionTests(unittest.TestCase):
    def test_a_denied_command_is_a_process_error_like_a_missing_one(self) -> None:
        path, tmp = deny("ps")
        self.addCleanup(tmp.cleanup)
        previous = os.environ.get("PATH", "")
        os.environ["PATH"] = path
        self.addCleanup(os.environ.__setitem__, "PATH", previous)
        with self.assertRaises(procinfo.ProcessError) as caught:
            procinfo._run(["ps", "-o", "lstart=", "-p", "1"])
        self.assertIn("ps", str(caught.exception))


class CommandTests(unittest.TestCase):
    """The commands, run as commands: a denied `ps` must reach the user as a
    sentence and an exit code, never as a traceback."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-noptable-")
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.state.mkdir()
        self.db = self.state / "bus.sqlite3"
        with make_store(self.db) as store:
            store.register_agent("codex-architect", provider="codex", role="architect")
        write_endpoint(self.state, "http://127.0.0.1:1/mcp", os.getpid(), "now")
        # A provider that leaves a mark, so "it never started" is provable
        # rather than assumed.
        self.ran = Path(self._tmp.name) / "provider-ran"
        self.provider = Path(self._tmp.name) / "provider.sh"
        # Absolute paths: the denied PATH these run under holds nothing else.
        self.provider.write_text(f"#!/bin/sh\n/usr/bin/touch {self.ran}\nexec /bin/cat\n")
        self.provider.chmod(0o755)
        self.workspaces = Path(self._tmp.name) / "workspaces"
        self.workspaces.mkdir()

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        path, tmp = deny("ps", "lsof")
        self.addCleanup(tmp.cleanup)
        env = {**os.environ, "PATH": path, "PYTHONPATH": PACKAGE_ROOT,
               "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(self.workspaces)}
        return subprocess.run([sys.executable, "-m", "luciazero_agentd", *args],
                              capture_output=True, text=True, timeout=60, env=env)

    def test_run_refuses_and_leaves_no_binding_credential_or_child(self) -> None:
        done = self.cli("run", "--agent", "codex-architect", "--provider", "claude",
                        "--state-dir", str(self.state), "--", str(self.provider))
        self.assertEqual(2, done.returncode, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("process table", done.stderr.lower())
        self.assertFalse(self.ran.exists(), "the provider must not be started")
        with make_store(self.db) as store:
            live = [b for b in store.list_bindings() if b["agent_id"] == "codex-architect"]
        self.assertEqual([], live, "a refusal must not leave a binding anyone could present")
        self.assertEqual([], [p.name for p in self.workspaces.iterdir() if p.name.startswith("luciazero-bind-")],
                         "the credential workspace must not outlive the refusal")

    def test_claim_refuses_rather_than_approving_a_check_it_could_not_run(self) -> None:
        """`claim approve` must prove this shell is not the session that is
        asking. Under a pty, because the command refuses a pipe first."""
        import select
        import signal
        import time

        from luciazero_agentd import nudge

        path, tmp = deny("ps", "lsof")
        self.addCleanup(tmp.cleanup)
        pid, master = nudge.spawn(
            [sys.executable, "-m", "luciazero_agentd", "claim", "approve", "clm_nothing",
             "--state-dir", str(self.state)],
            {**os.environ, "PATH": path, "PYTHONPATH": PACKAGE_ROOT, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        seen = bytearray()
        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    seen.extend(chunk)
            done, waited = os.waitpid(pid, os.WNOHANG)
            if done == pid:
                status = waited
                break
        if status is None:  # pragma: no cover - only on a hang
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            self.fail(f"claim did not exit: {bytes(seen)!r}")
        os.close(master)
        text = bytes(seen).decode("utf-8", "replace")
        self.assertEqual(2, os.WEXITSTATUS(status), text)
        self.assertNotIn("Traceback", text)
        self.assertIn("process table", text.lower())

    def test_terminal_says_why_instead_of_raising(self) -> None:
        done = self.cli("terminal", "list", "--state-dir", str(self.state))
        self.assertEqual(1, done.returncode, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertIn("process table", done.stderr.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

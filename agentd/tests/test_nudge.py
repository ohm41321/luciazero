"""M7f: typing into the session that is already open.

Every test here drives a real pty and a real store. What it never does is
start a provider: the child is `cat`, which echoes what it is typed, so the
assertion "the nudge reached the terminal" is the bytes coming back out.
"""

from __future__ import annotations

import os
import pty
import signal
import sys
import termios
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from luciazero_agentd import nudge  # noqa: E402
from luciazero_agentd.store import Store, utcnow  # noqa: E402


def make_store(path: Path) -> Store:
    store = Store.open(str(path))
    store.migrate()
    return store


class WatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-nudge-")
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "bus.sqlite3"
        self.now = 1000.0
        with make_store(self.db) as store:
            store.register_agent("codex-architect", provider="codex", role="architect")
            store.register_agent("claude-implementer", provider="claude", role="implementer")
        self.started = utcnow()

    def clock(self) -> float:
        return self.now

    def watcher(self, agent: str = "codex-architect", **kwargs: object) -> nudge.Watcher:
        kwargs.setdefault("started_at", self.started)
        kwargs.setdefault("clock", self.clock)
        return nudge.Watcher(self.db, agent, **kwargs)  # type: ignore[arg-type]

    def send(self, text: str = "hello", to: str = "codex-architect") -> None:
        with make_store(self.db) as store:
            store.send_message(sender="claude-implementer", recipient=to,
                               kind="finding", payload={"message": text})

    def seen(self, agent: str = "codex-architect") -> None:
        """The agent calls the daemon, as the skill does at session start."""
        time.sleep(0.001)  # utcnow() has to move past started_at
        with make_store(self.db) as store:
            store.heartbeat(agent)

    def test_a_delivery_that_arrives_while_the_session_waits_is_a_nudge(self) -> None:
        watcher = self.watcher()
        self.seen()
        self.send()
        self.assertTrue(watcher.due())

    def test_nothing_new_is_never_a_nudge(self) -> None:
        watcher = self.watcher()
        self.seen()
        self.assertFalse(watcher.due())

    def test_the_backlog_is_not_a_nudge(self) -> None:
        """What was already queued when the terminal opened belongs to the
        skill's own first inbox read, not to an interruption."""
        self.send("waiting since before you started")
        watcher = self.watcher()
        self.seen()
        self.assertFalse(watcher.due())

    def test_one_delivery_is_one_nudge(self) -> None:
        watcher = self.watcher()
        self.seen()
        self.send()
        self.assertTrue(watcher.due())
        self.now += 3600
        self.assertFalse(watcher.due(), "the same delivery must not nudge twice")

    def test_a_burst_of_messages_cannot_start_a_burst_of_turns(self) -> None:
        watcher = self.watcher(cooldown=20.0)
        self.seen()
        self.send("one")
        self.assertTrue(watcher.due())
        self.send("two")
        self.now += 5
        self.assertFalse(watcher.due(), "inside the cooldown")
        self.now += 20
        self.assertTrue(watcher.due(), "after the cooldown")

    def test_a_session_that_has_not_reached_the_bus_is_left_alone(self) -> None:
        """It may be holding a trust dialog; a line typed there answers a
        question the user never read."""
        watcher = self.watcher()
        self.send()
        self.assertFalse(watcher.due())
        self.seen()
        self.assertTrue(watcher.due())

    def test_a_delivery_for_somebody_else_is_not_a_nudge(self) -> None:
        watcher = self.watcher("codex-architect")
        self.seen("codex-architect")
        self.send("for the other one", to="claude-implementer")
        self.assertFalse(watcher.due())

    def test_an_unreadable_bus_nudges_nobody(self) -> None:
        watcher = self.watcher()
        self.seen()
        self.send()
        self.db.unlink()
        self.db.write_text("not a database", encoding="utf-8")
        self.assertFalse(watcher.due())


class TypistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.written: list[bytes] = []
        self.now = 0.0

    def typist(self, **kwargs: object) -> nudge.Typist:
        return nudge.Typist(self.written.append, clock=lambda: self.now, **kwargs)  # type: ignore[arg-type]

    def test_the_return_is_a_second_write_a_beat_later(self) -> None:
        """A TUI reads a burst as a paste and keeps the return in the box."""
        typist = self.typist(delay=0.4)
        typist.start()
        self.assertEqual([nudge.TEXT.encode()], self.written)
        typist.tick()
        self.assertEqual([nudge.TEXT.encode()], self.written, "too early")
        self.now = 0.5
        typist.tick()
        self.assertEqual([nudge.TEXT.encode(), b"\r"], self.written)

    def test_a_second_line_never_interleaves_with_the_first(self) -> None:
        typist = self.typist(delay=0.4)
        typist.start()
        typist.start()
        self.assertEqual([nudge.TEXT.encode()], self.written)
        self.assertTrue(typist.busy)
        self.now = 0.5
        typist.tick()
        self.assertFalse(typist.busy)

    def test_the_text_is_a_literal_of_this_module(self) -> None:
        """Nothing from a payload may reach a peer's prompt: a message that
        could type into another session would be writing its instructions."""
        source = Path(nudge.__file__).read_text(encoding="utf-8")
        self.assertIn('TEXT = "check your bus inbox"', source)
        self.assertNotIn("payload", nudge.TEXT)
        typist = self.typist()
        typist.start()
        self.now = 99
        typist.tick()
        self.assertEqual(b"".join(self.written), nudge.TEXT.encode() + b"\r")


class ProxyTests(unittest.TestCase):
    """The pty half, with `cat` standing in for a provider.

    A terminal always drains what is written to it, so the fixture does too:
    a test that stops reading fills the pty buffer and blocks the proxy in a
    write, which looks like a hang in the code under test and is not one.
    """

    def setUp(self) -> None:
        self.terminal, self.slave = pty.openpty()
        self.seen = bytearray()
        self.stop = threading.Event()
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()
        self.addCleanup(self._close)

    def _drain(self) -> None:
        import select

        while not self.stop.is_set():
            try:
                ready, _, _ = select.select([self.terminal], [], [], 0.1)
            except OSError:
                return
            if not ready:
                continue
            try:
                chunk = os.read(self.terminal, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.seen.extend(chunk)

    def _close(self) -> None:
        self.stop.set()
        self.reader.join(5)
        for fd in (self.terminal, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def start(self, argv: list[str], **kwargs: object) -> threading.Thread:
        pid, master = nudge.spawn(argv, dict(os.environ))
        self.pid = pid
        self.code: list[int] = []

        def run() -> None:
            self.code.append(nudge.proxy(pid, master, stdin=self.slave,
                                         stdout=self.slave, **kwargs))  # type: ignore[arg-type]

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(self._end, thread, pid)
        return thread

    def _end(self, thread: threading.Thread, pid: int) -> None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not thread.is_alive():
                return
            try:
                os.kill(pid, sig)
            except OSError:
                pass
            thread.join(5)

    def wait_for(self, needle: bytes, seconds: float = 10.0) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if needle in self.seen:
                return True
            time.sleep(0.02)
        return False

    def test_what_the_user_types_reaches_the_provider_and_back(self) -> None:
        self.start(["cat"])
        os.write(self.terminal, b"round trip\n")
        self.assertTrue(self.wait_for(b"round trip"), bytes(self.seen))

    def test_the_provider_exit_code_is_this_command_s_exit_code(self) -> None:
        thread = self.start(["sh", "-c", "exit 7"])
        thread.join(15)
        self.assertEqual([7], self.code)

    def test_a_provider_that_exits_ends_the_command_even_with_its_pty_held(self) -> None:
        """A grandchild inherits the pty and can hold it open after the
        provider is gone. The child is the exit condition, not the pty:
        macOS reports EOF when the session leader exits, Linux does not, and
        a `run` that waited for the pty would hang there forever."""
        thread = self.start(["sh", "-c", "sleep 30 & exit 3"])
        thread.join(10)
        self.assertFalse(thread.is_alive(), "the proxy waited on a pty nobody would close")
        self.assertEqual([3], self.code)

    def test_a_nudge_is_typed_into_the_session(self) -> None:
        """`cat` echoes what it is typed, so the nudge coming back out of the
        pty is proof it arrived as keystrokes."""

        class Once:
            def __init__(self) -> None:
                self.left = 1

            def due(self) -> bool:
                self.left -= 1
                return self.left == 0

        self.start(["cat"], watcher=Once(), poll=0.05)
        self.assertTrue(self.wait_for(nudge.TEXT.encode()), bytes(self.seen))

    def test_a_quiet_bus_types_nothing(self) -> None:
        class Never:
            def due(self) -> bool:
                return False

        self.start(["cat"], watcher=Never(), poll=0.05)
        os.write(self.terminal, b"marker\n")
        self.assertTrue(self.wait_for(b"marker"))
        self.assertNotIn(nudge.TEXT.encode(), bytes(self.seen))

    @staticmethod
    def settings(fd: int) -> list:
        """The terminal's settings, without PENDIN -- a kernel status bit
        saying input is waiting to be retyped, which the act of reprogramming
        a busy terminal sets and nobody chose."""
        attrs = termios.tcgetattr(fd)
        attrs[3] &= ~getattr(termios, "PENDIN", 0)
        return attrs

    def test_the_terminal_is_left_as_it_was_found(self) -> None:
        """raw mode belongs to the provider; a `run` that returned without
        restoring it would leave the user's shell with no echo."""
        before = self.settings(self.slave)
        thread = self.start(["sh", "-c", "exit 0"])
        thread.join(15)
        self.assertEqual(before, self.settings(self.slave))


class RunTests(unittest.TestCase):
    """`run` end to end, under a pty, with a delivery arriving mid-session.

    The provider stand-in is a script that ignores the flags `run` adds and
    execs `cat`, so whatever is typed into the session comes back out of the
    pty: that echo is the proof the nudge was delivered as keystrokes to a
    process that was doing nothing at the time.
    """

    def setUp(self) -> None:
        import tempfile

        from luciazero_agentd.statedir import write_endpoint

        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-run-")
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "state"
        self.state.mkdir()
        self.db = self.state / "bus.sqlite3"
        with make_store(self.db) as store:
            store.register_agent("codex-architect", provider="codex", role="architect")
            store.register_agent("claude-implementer", provider="claude", role="implementer")
        write_endpoint(self.state, "http://127.0.0.1:1/mcp", os.getpid(), "now")
        self.provider = self.state / "provider.sh"
        self.provider.write_text("#!/bin/sh\nexec cat\n")
        self.provider.chmod(0o755)

    def test_a_delivery_knocks_on_a_session_that_is_doing_nothing(self) -> None:
        package_root = str(Path(__file__).resolve().parents[1])
        pid, master = nudge.spawn(
            [sys.executable, "-m", "luciazero_agentd", "run", "--agent", "codex-architect",
             "--provider", "claude", "--state-dir", str(self.state), "--", str(self.provider)],
            {**os.environ, "PYTHONPATH": package_root, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.addCleanup(self._end, pid, master)
        seen = bytearray()

        def wait_for(needle: bytes, seconds: float = 20.0) -> bool:
            import select

            deadline = time.time() + seconds
            while time.time() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        return needle in seen
                    if not chunk:
                        return needle in seen
                    seen.extend(chunk)
                if needle in seen:
                    return True
            return False

        self.assertTrue(wait_for(b"bound as"), bytes(seen))
        # The session reaches the bus, as the skill does at its first turn;
        # until it has, a nudge could land in a dialog nobody read.
        time.sleep(0.05)
        with make_store(self.db) as store:
            store.heartbeat("codex-architect")
            store.send_message(sender="claude-implementer", recipient="codex-architect",
                               kind="finding", payload={"message": "while you were idle"})
        self.assertTrue(wait_for(nudge.TEXT.encode()), bytes(seen))
        # The payload stays on the bus: only the fixed literal is ever typed.
        self.assertNotIn(b"while you were idle", bytes(seen))

    def _end(self, pid: int, master: int) -> None:
        import signal as _signal

        for sig in (_signal.SIGTERM, _signal.SIGKILL):
            try:
                os.kill(pid, sig)
                os.waitpid(pid, 0)
                break
            except ChildProcessError:
                break
            except OSError:
                continue
        try:
            os.close(master)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()

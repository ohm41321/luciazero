"""M8: waking the session that is already open.

MCP is request and response. The daemon cannot push, so a session learns about
a delivery only when it calls `message_inbox`, and it can call nothing at all
while it is idle -- a session runs code during a turn and not one moment
otherwise. Two sessions therefore trade messages perfectly and neither notices,
until a person types "check your inbox" into the one that is waiting. That is
the gap this module closes.

The only thing that can start a turn in a session somebody is watching is
whatever owns its terminal. `run` already starts the provider, so it takes the
terminal too: the provider gets a pty, `run` copies bytes both ways, and when a
delivery arrives for the bound agent it types one line into that pty. To the
provider it is indistinguishable from the user typing, because that is exactly
what it is.

What may be typed is the narrow part. The text is a fixed literal defined here
and nothing from the payload ever reaches it: a peer that could put its own
words into another session's prompt would have found a way to write that
session's instructions, which is the whole shape of a prompt injection. The
payload still arrives the way it always did, through `message_inbox`, where the
skill treats it as untrusted input.

Three more limits, each for a failure seen while building this:

* **Nothing is typed until the agent has used the bus since `run` started.**
  A session that has just opened may be holding a modal -- Claude Code asks
  whether the folder is trusted -- and a line typed into that dialog answers a
  question nobody read. Once the agent has called the daemon, the session is
  past its dialogs and listening at a prompt.
* **The backlog is not a nudge.** What is already queued when the session
  starts is the skill's job to read; only a delivery that arrives afterwards
  means "something happened while you were sitting there".
* **A cooldown.** Every nudge spends a turn of somebody's quota, so a peer
  that sends ten messages in a second must not start ten turns.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import signal
import sqlite3
import struct
import termios
import time
import tty
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .store import Store, StoreError

#: Typed into the provider's terminal, verbatim, and never anything else.
TEXT = "check your bus inbox"
#: The provider TUIs treat a burst of bytes as a paste; the return goes in its
#: own write, a beat later, so it submits the line instead of joining it.
RETURN_DELAY = 0.4
#: A nudge costs a turn. Peers cannot make that cheaper by sending faster.
COOLDOWN_SECONDS = 20.0
POLL_SECONDS = 2.0


class Watcher:
    """Decides when the terminal should be typed into. Reads, never writes."""

    def __init__(self, db_path: Path | str, agent_id: str, *, started_at: str,
                 clock: Callable[[], float] = time.monotonic,
                 cooldown: float = COOLDOWN_SECONDS) -> None:
        self.db_path = str(db_path)
        self.agent_id = agent_id
        self.started_at = started_at
        self.clock = clock
        self.cooldown = cooldown
        #: Deliveries at or below this sequence were already there when the
        #: session opened; the skill reads those itself.
        self.seen_seq = self._max_queued_seq()
        self.last_nudge: Optional[float] = None

    def _read(self, call: Callable[[Store], Any], default: Any) -> Any:
        try:
            with Store.open(self.db_path) as store:
                return call(store)
        except (StoreError, OSError, sqlite3.Error):
            # A bus that cannot be read nudges nobody. It must not take the
            # provider with it either: this loop is the user's terminal, and
            # an unreadable store is a reason to stop typing, not to close it.
            return default

    def _max_queued_seq(self) -> int:
        def newest(store: Store) -> int:
            page = store.inbox(self.agent_id, states=("queued",), limit=500)
            return max((item["delivery_seq"] for item in page["items"]), default=0)
        return int(self._read(newest, 0))

    def _seen_since_start(self) -> bool:
        """Has the agent talked to the daemon since this terminal opened?"""
        def last_seen(store: Store) -> Optional[str]:
            return store.get_agent(self.agent_id).get("last_seen_at")
        stamp = self._read(last_seen, None)
        return bool(stamp and stamp > self.started_at)

    def due(self) -> bool:
        """True at most once per new delivery, and never faster than the
        cooldown. Calling this is what marks the delivery as noticed."""
        newest = self._max_queued_seq()
        if newest <= self.seen_seq:
            return False
        now = self.clock()
        if self.last_nudge is not None and now - self.last_nudge < self.cooldown:
            return False
        if not self._seen_since_start():
            return False
        self.seen_seq = newest
        self.last_nudge = now
        return True


class Typist:
    """Types one line, in two writes. Nothing else ever reaches the pty."""

    def __init__(self, write: Callable[[bytes], None], *,
                 clock: Callable[[], float] = time.monotonic,
                 delay: float = RETURN_DELAY, text: str = TEXT) -> None:
        self.write = write
        self.clock = clock
        self.delay = delay
        self.text = text
        self.return_due: Optional[float] = None

    def start(self) -> None:
        if self.return_due is not None:
            return  # a line is already going in; never interleave two
        self.write(self.text.encode("utf-8"))
        self.return_due = self.clock() + self.delay

    def tick(self) -> None:
        if self.return_due is not None and self.clock() >= self.return_due:
            self.write(b"\r")
            self.return_due = None

    @property
    def busy(self) -> bool:
        return self.return_due is not None


def _window_size(fd: int) -> Optional[bytes]:
    try:
        return fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
    except OSError:
        return None


def _copy_window(source: int, target: int) -> None:
    size = _window_size(source)
    if size is not None:
        try:
            fcntl.ioctl(target, termios.TIOCSWINSZ, size)
        except OSError:
            pass


def _drain(master: int, stdout: int, *, seconds: float = 0.2) -> None:
    """Whatever the provider printed on its way out still belongs on screen."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            ready, _, _ = select.select([master], [], [], 0.02)
        except OSError:
            return
        if not ready:
            return
        try:
            data = os.read(master, 65536)
        except OSError:
            return
        if not data:
            return
        try:
            os.write(stdout, data)
        except OSError:
            return


def usable(stdin: int = 0, stdout: int = 1) -> bool:
    """A pty is only worth taking when there is a real terminal to proxy."""
    return os.isatty(stdin) and os.isatty(stdout)


def spawn(argv: Sequence[str], env: dict[str, str]) -> tuple[int, int]:
    """Start the provider on a pty of its own. Returns (pid, master fd)."""
    pid, master = pty.fork()
    if pid == 0:  # pragma: no cover - the child never returns
        try:
            os.execvpe(argv[0], list(argv), env)
        finally:
            os._exit(127)
    return pid, master


def proxy(pid: int, master: int, *, watcher: Optional[Watcher] = None,
          stdin: int = 0, stdout: int = 1, poll: float = POLL_SECONDS,
          clock: Callable[[], float] = time.monotonic,
          typist: Optional[Typist] = None) -> int:
    """Copy bytes between this terminal and the provider's pty until it exits,
    typing a nudge into it when the watcher says a delivery arrived.

    The terminal is put in raw mode so the provider sees every keystroke as it
    would have with the terminal to itself, and it is restored however this
    returns -- an exception here would otherwise leave the user's shell without
    an echo.
    """
    typist = typist or Typist(lambda data: os.write(master, data), clock=clock)
    _copy_window(stdout, master)
    restore: Optional[list[Any]] = None
    if os.isatty(stdin):
        try:
            restore = termios.tcgetattr(stdin)
            tty.setraw(stdin)
        except termios.error:
            restore = None

    def _resize(*_: object) -> None:
        _copy_window(stdout, master)

    previous_winch = None
    try:
        previous_winch = signal.signal(signal.SIGWINCH, _resize)
    except (ValueError, OSError):  # not the main thread, or no SIGWINCH
        previous_winch = None

    next_poll = clock() + poll
    status: Optional[int] = None
    try:
        while True:
            # The pty is not a reliable death certificate: a grandchild can
            # hold the slave open after the provider exits, and a killed
            # provider was seen to leave the master quiet rather than closed.
            # The child itself is the exit condition; the pty only carries
            # bytes.
            try:
                done, waited = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                done, waited = pid, 0
            if done == pid:
                status = waited
                _drain(master, stdout)
                break
            try:
                ready, _, _ = select.select([stdin, master], [], [], 0.2)
            except (OSError, select.error) as exc:  # EINTR on window change
                if getattr(exc, "errno", None) == errno.EINTR:
                    continue
                raise
            if master in ready:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break  # the pty closed: the provider is gone
                if not data:
                    break
                os.write(stdout, data)
            if stdin in ready:
                try:
                    data = os.read(stdin, 65536)
                except OSError:
                    data = b""
                if data:
                    os.write(master, data)
            typist.tick()
            now = clock()
            if watcher is not None and now >= next_poll:
                next_poll = now + poll
                if not typist.busy and watcher.due():
                    typist.start()
    finally:
        if previous_winch is not None:
            try:
                signal.signal(signal.SIGWINCH, previous_winch)
            except (ValueError, OSError):
                pass
        if restore is not None:
            termios.tcsetattr(stdin, termios.TCSADRAIN, restore)
        try:
            os.close(master)
        except OSError:
            pass
    if status is None:
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            return 0
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.WEXITSTATUS(status)

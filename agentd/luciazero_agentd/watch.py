"""M7a: follow the bus as it happens, without touching it.

The pull beta pushes nothing. A message sits in its delivery until a human
opens that agent's session and the agent reads its own inbox, so two agents
can hold a whole conversation while both terminals show nothing at all. That
is the cost the M4 decision gate asks about, and it is also why the traffic is
invisible: there is no third place where the exchange can be watched.

This is that third place. It is a reader and only a reader:

- the database is opened ``mode=ro``, so a bug here cannot rewrite the record
  that the decision log treats as evidence;
- nothing is acknowledged. ``deliveries.acknowledged_at`` is what the gate
  measures a user-started turn with, and it must keep meaning "an agent opened
  this in its own session" -- a watcher that marked messages read would erase
  the very number it was built to expose;
- the cursor lives in this process. A restart replays from the tail rather
  than skipping ahead, because a follower that loses a message to a crash is
  worse than one that shows it twice.

Reading a database another process is writing is the normal case here, not the
exception, so a poll that fails reconnects and carries on: the daemon may be
restarted, and WAL may be checkpointed, under a running watcher.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

from . import procinfo
from .redact import DEFAULT as DEFAULT_REDACTOR

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Peer-supplied text on a terminal: an escape sequence in a message payload
# must never move the cursor or repaint the pane it is printed in.
PREVIEW_KEYS = ("title", "text", "summary", "question", "finding", "decision",
                "note", "body", "message", "result", "task_id", "artifact_id")
PREVIEW_WIDTH = 96
# A follower left open for days must not grow with the bus. What it remembers
# is trimmed to the recent past; anything older is one indexed lookup away.
CACHE_LIMIT = 4096
# Delivery states worth a line: the moment somebody actually opened it, and
# the moment they were done with it. The rest is dispatcher bookkeeping.
NOTABLE_STATES = ("acknowledged", "completed", "dead_letter")
PALETTE = ("\033[36m", "\033[35m", "\033[32m", "\033[33m", "\033[34m", "\033[31m")
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


class WatchError(RuntimeError):
    pass


def clean(value: Any) -> str:
    return CONTROL_CHARS.sub("?", str(value))


def open_read_only(path: Path) -> sqlite3.Connection:
    """The database, read-only and never migrated.

    ``mode=ro`` refuses to create what is missing, which is the point -- but it
    reports a path that does not exist as ``unable to open database file``,
    indistinguishable from a permission problem. The existence check is what
    turns a typo in ``--state-dir`` into a sentence that names the directory.
    """
    if not path.exists():
        raise WatchError(f"no bus database at {path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        raise WatchError(f"cannot read {path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def preview(payload: Any, *, width: int = PREVIEW_WIDTH) -> str:
    """One line of what was actually said.

    The daemon redacts on the way in; this redacts again on the way out,
    because a pane left open on a desk is a second audience.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            pass
    if isinstance(payload, dict):
        for key in PREVIEW_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value if key not in ("task_id", "artifact_id") else f"{key}={value}"
                break
        else:
            text = json.dumps(payload, sort_keys=True, default=str)
    else:
        text = str(payload)
    text, _ = DEFAULT_REDACTOR.text(clean(" ".join(text.split())))
    return text if len(text) <= width else text[: width - 1] + "…"


def local_time(stamp: Any) -> str:
    try:
        return datetime.fromisoformat(str(stamp)).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "--:--:--"


def gap(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


class Follower:
    """A read-only cursor over messages and delivery states.

    ``since`` is the last message seq already shown. Deliveries are tracked by
    the state they were last seen in, so a transition is reported once without
    the watcher ever writing a cursor back into the store.
    """

    def __init__(self, path: Path, *, agents: Optional[Iterable[str]] = None, pair: bool = False,
                 since: Optional[int] = None) -> None:
        self.path = Path(path)
        # Two ways to narrow: `agents` shows anything one of them touched,
        # `pair` shows only what the named two said to each other -- which is
        # what somebody watching a conversation actually means.
        self.agents = frozenset(agents) if agents else None
        self.pair = pair
        self.since = since
        self.conn: Optional[sqlite3.Connection] = None
        self.states: dict[str, str] = {}
        self.messages: dict[str, dict[str, str]] = {}
        self.titles: dict[str, Optional[str]] = {}
        self.watermark: Optional[str] = None
        self.reconnects = 0
        self._primed = False

    def connect(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = open_read_only(self.path)
            if not self._primed:
                # Whatever the deliveries already were is not news. The
                # watermark is how that is said without reading the whole
                # table: a delivery that changes later gets a newer
                # `updated_at` and comes back into view by itself.
                #
                # Only on the first connect. A reconnect keeps the watermark,
                # so a transition that happened while the daemon was down is
                # still reported rather than swallowed.
                row = self.conn.execute("SELECT MAX(updated_at) AS mark FROM deliveries").fetchone()
                self.watermark = str(row["mark"]) if row and row["mark"] else None
                if self.watermark is not None:
                    # The rows sitting exactly on the watermark come back on
                    # every poll (`>=`, because timestamps can tie); knowing
                    # the state they were already in is what keeps them quiet.
                    for delivery in self.conn.execute(
                            "SELECT id, state FROM deliveries WHERE updated_at >= ?", (self.watermark,)).fetchall():
                        self.states.setdefault(str(delivery["id"]), str(delivery["state"]))
                self._primed = True
        return self.conn

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "Follower":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _mine(self, row: Any) -> bool:
        if self.agents is None:
            return True
        ends = {str(row["sender_agent_id"]), str(row["recipient_agent_id"])}
        return ends <= self.agents if self.pair else bool(ends & self.agents)

    def _mine_delivery(self, conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
        """A delivery is the watched agents' business either way: one of them
        is opening the message, or one of them sent it and is waiting."""
        if self.agents is None:
            return True
        sender = (self.message_of(conn, str(row["message_id"])) or {}).get("sender")
        ends = {str(row["recipient_agent_id"])} | ({sender} if sender else set())
        return ends <= self.agents if self.pair and sender else bool(ends & self.agents)

    def _remember(self, cache: dict, key: str, value: Any) -> Any:
        if len(cache) >= CACHE_LIMIT:
            for old in list(cache)[: CACHE_LIMIT // 2]:
                cache.pop(old, None)
        cache[key] = value
        return value

    def message_of(self, conn: sqlite3.Connection, message_id: str) -> Optional[dict[str, str]]:
        """Who sent a message and when, for a delivery whose message may be
        older than this watcher. One indexed lookup, then cached."""
        if message_id in self.messages:
            return self.messages[message_id]
        row = conn.execute("SELECT sender_agent_id, created_at FROM messages WHERE id = ?",
                           (message_id,)).fetchone()
        if row is None:
            return None
        return self._remember(self.messages, message_id,
                              {"sender": str(row["sender_agent_id"]), "created_at": str(row["created_at"])})

    def _record(self, conn: sqlite3.Connection, row: Any) -> dict[str, Any]:
        """One message, with the task's title fetched when the payload carries
        only its id -- ``task_id=tsk_e6e6…`` is not a readable transcript."""
        record = dict(row)
        payload = record.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if isinstance(payload, dict) and payload.get("task_id") and not any(
                isinstance(payload.get(key), str) and payload[key].strip() for key in PREVIEW_KEYS[:-2]):
            record["task_title"] = self.title_of(conn, str(payload["task_id"]))
        return record

    def title_of(self, conn: sqlite3.Connection, task_id: str) -> Optional[str]:
        if task_id not in self.titles:
            row = conn.execute("SELECT title FROM tasks WHERE id = ?", (task_id,)).fetchone()
            self.titles[task_id] = str(row["title"]) if row is not None else None
        return self.titles[task_id]

    def tail(self, count: int) -> list[dict[str, Any]]:
        """The last few messages, so a watcher opened mid-conversation still
        shows what is being talked about. Sets the cursor past them."""
        conn = self.connect()
        rows = [self._record(conn, r) for r in conn.execute(
            "SELECT * FROM messages ORDER BY seq DESC LIMIT ?", (max(count, 0) * 8 + 8,)).fetchall()]
        kept = [r for r in rows if self._mine(r)][:count][::-1]
        highest = max((int(r["seq"]) for r in rows), default=0)
        self.since = max(self.since or 0, highest)
        for row in rows:
            self._remember(self.messages, str(row["id"]),
                           {"sender": str(row["sender_agent_id"]), "created_at": str(row["created_at"])})
        return kept

    def poll(self) -> list[dict[str, Any]]:
        """Everything that happened since the last poll, in order.

        Messages first, then the delivery transitions, each as a dict with a
        ``what`` of ``message`` or ``delivery``.
        """
        conn = self.connect()
        events: list[dict[str, Any]] = []
        cursor = self.since or 0
        for row in conn.execute("SELECT * FROM messages WHERE seq > ? ORDER BY seq", (cursor,)).fetchall():
            record = self._record(conn, row)
            self.since = int(record["seq"])
            self._remember(self.messages, str(record["id"]),
                           {"sender": str(record["sender_agent_id"]), "created_at": str(record["created_at"])})
            if self._mine(record):
                events.append({"what": "message", **record})
        # Only deliveries that have changed since the last poll: `>=` rather
        # than `>` because two rows can share a timestamp, and the states map
        # is what stops the boundary row being reported twice.
        mark = self.watermark or ""
        for row in conn.execute("SELECT * FROM deliveries WHERE updated_at >= ? ORDER BY seq", (mark,)).fetchall():
            record = dict(row)
            delivery_id, state = str(record["id"]), str(record["state"])
            self.watermark = max(self.watermark or "", str(record["updated_at"]))
            known = self.states.get(delivery_id)
            self._remember(self.states, delivery_id, state)
            if known == state or state not in NOTABLE_STATES or not self._mine_delivery(conn, record):
                continue
            record["waited"] = self._waited(conn, record)
            events.append({"what": "delivery", **record})
        return events

    def _waited(self, conn: sqlite3.Connection, delivery: dict[str, Any]) -> Optional[float]:
        """How long that delivery sat before somebody opened the turn.

        The same number `scripts/agent_bus_evidence.py` exports for the
        decision log, shown live -- the wait is easier to believe when it is
        watched than when it is reconstructed afterwards.
        """
        sent = (self.message_of(conn, str(delivery.get("message_id"))) or {}).get("created_at")
        stamp = delivery.get("acknowledged_at") or delivery.get("updated_at")
        try:
            return (datetime.fromisoformat(str(stamp)) - datetime.fromisoformat(str(sent))).total_seconds()
        except (TypeError, ValueError):
            return None

    def follow(self, *, interval: float = 1.0, passes: Optional[int] = None,
               on_error: Optional[Callable[[Exception], None]] = None) -> Iterator[dict[str, Any]]:
        """Poll until stopped. A failed poll reconnects rather than exiting:
        the daemon it is reading may be restarted under it."""
        done = 0
        while passes is None or done < passes:
            try:
                yield from self.poll()
            except sqlite3.Error as exc:
                self.close()
                self.reconnects += 1
                if on_error is not None:
                    on_error(exc)
            done += 1
            if passes is not None and done >= passes:
                return
            time.sleep(interval)


class Renderer:
    """The pane itself: one line per thing that happened."""

    def __init__(self, *, colour: bool = False, payload: str = "preview") -> None:
        self.colour = colour
        self.payload = payload
        self._colours: dict[str, str] = {}

    def paint(self, agent: str, text: Optional[str] = None) -> str:
        if not self.colour:
            return text if text is not None else agent
        if agent not in self._colours:
            self._colours[agent] = PALETTE[len(self._colours) % len(PALETTE)]
        return f"{self._colours[agent]}{text if text is not None else agent}{RESET}"

    def dim(self, text: str) -> str:
        return f"{DIM}{text}{RESET}" if self.colour else text

    def line(self, event: dict[str, Any]) -> str:
        if event["what"] == "message":
            return self._message(event)
        return self._delivery(event)

    def _message(self, event: dict[str, Any]) -> str:
        sender, recipient = clean(event["sender_agent_id"]), clean(event["recipient_agent_id"])
        head = (f"{self.dim(local_time(event['created_at']))}  "
                f"{self.paint(sender):<24} -> {self.paint(recipient):<24} "
                f"{self.dim('[' + clean(event['kind']) + ']'):<12}")
        if self.payload == "none":
            return f"{head} {self.dim(clean(event['id']))}"
        if event.get("task_title"):
            body = preview({"title": event["task_title"]})
            return f"{head} {body}\n{' ' * 10}{self.dim(clean(event['id']))}"
        if self.payload == "full":
            body, _ = DEFAULT_REDACTOR.text(clean(event["payload"]))
        else:
            body = preview(event["payload"])
        return f"{head} {body}\n{' ' * 10}{self.dim(clean(event['id']))}"

    def _delivery(self, event: dict[str, Any]) -> str:
        who = clean(event["recipient_agent_id"])
        waited = event.get("waited")
        verb = {"acknowledged": "opened it", "completed": "finished with it",
                "dead_letter": "never got it (dead letter)"}[str(event["state"])]
        after = f" after {gap(float(waited))}" if isinstance(waited, (int, float)) else ""
        return self.dim(f"{local_time(event.get('updated_at'))}  {who} {verb}{after}")


# --- setting one up ---------------------------------------------------------
#
# The watcher answers "show me the conversation". The other half of the same
# question is "which terminals are having it", and that is a chore nobody
# should do from memory: three windows, three commands, each with the right
# agent id, and one of them has to be the pane that shows the traffic.

PROVIDER_COMMAND = {"codex": "codex", "claude": "claude"}


def launcher() -> str:
    """How to invoke the daemon from another terminal.

    There is no installed `luciazero-agentd` executable -- the package is run
    with `python3 -m` from the `agentd` directory -- so a plan that leaves the
    `cd` out prints commands that do not run.
    """
    return launcher_in(Path(__file__).resolve().parents[2])


def launcher_in(checkout: Any) -> str:
    """The same, from one agent's own checkout.

    An agent's session must start inside its own worktree or the binding
    records the main checkout as its working directory and the isolation is
    gone -- the mistake is invisible until two agents are found editing one
    tree, so the `cd` is part of the command rather than a note under it.
    """
    return f"cd {Path(checkout) / 'agentd'} && python3 -m luciazero_agentd"


def roster(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Who could be talking, and which terminal each one already holds."""
    agents = [dict(r) for r in conn.execute(
        "SELECT id, provider, role, last_seen_at FROM agents ORDER BY id").fetchall()]
    worktrees = {str(r["agent_id"]): str(r["path"]) for r in conn.execute(
        "SELECT agent_id, path FROM worktrees").fetchall()}
    live: dict[str, dict[str, Any]] = {}
    try:
        for row in conn.execute(
                "SELECT agent_id, tty, state, expires_at, pid, process_started_at FROM bindings "
                "WHERE state = 'active' ORDER BY created_at").fetchall():
            live[str(row["agent_id"])] = dict(row)
    except sqlite3.OperationalError:
        pass  # an older state directory predates ADR 0004 bindings
    now = datetime.now(timezone.utc)
    for agent in agents:
        binding = live.get(str(agent["id"]))
        if binding is not None:
            try:
                # `active` is a state, not a promise: a credential that has run
                # out still leaves its row behind, and calling that terminal
                # live would send the user to a window that no longer answers.
                if datetime.fromisoformat(str(binding["expires_at"])) <= now:
                    binding = None
                elif not procinfo.alive(binding["pid"], binding["process_started_at"]):
                    # `active` outlives the window: the daemon only sweeps a
                    # binding when something asks. Sending the user to a
                    # terminal that has already been closed is worse than
                    # telling them to open a new one.
                    binding = None
            except (TypeError, ValueError):
                binding = None
        agent["tty"] = str(binding["tty"]) if binding and binding["tty"] else None
        agent["bound"] = binding is not None
        agent["worktree"] = worktrees.get(str(agent["id"]))
    return agents


def conversation_plan(agents: list[dict[str, Any]], first: str, second: str, *,
                      state_dir: Optional[Path] = None) -> list[tuple[str, str]]:
    """One (what this terminal is, what to type in it) pair per terminal.

    The watcher comes first on purpose: open it before the two sessions and
    the conversation is visible from its first message rather than from
    whenever somebody thought to look.
    """
    where = f" --state-dir {state_dir}" if state_dir is not None else ""
    known = {str(a["id"]): a for a in agents}
    run = launcher()
    plan = [("terminal 1 - the conversation",
             f"{run} watch --between {first} {second}{where}")]
    for agent_id in (first, second):
        agent = known.get(agent_id, {})
        provider = str(agent.get("provider") or "other")
        command = PROVIDER_COMMAND.get(provider)
        if command is None:
            plan.append((f"terminal for {agent_id} ({provider})",
                         f"{run} run --agent {agent_id}{where} -- <your {provider} command>"))
            continue
        held = f"  # already bound to {agent['tty']}" if agent.get("tty") else ""
        start = launcher_in(agent["worktree"]) if agent.get("worktree") else run
        plan.append((f"terminal for {agent_id} ({provider})",
                     f"{start} run --agent {agent_id}{where} -- {command}{held}"))
    return plan


def auto_turn_plan(agents: list[dict[str, Any]], first: str, second: str, *,
                   state_dir: Optional[Path] = None, turns: int = 4) -> list[tuple[str, str]]:
    """The managed-dispatch version: turns started by the dispatcher, not by a
    person opening a terminal.

    Printed, never run. Every turn here starts a real provider process against
    the user's own credentials, so the decision to spend that is the user's and
    has to be made in front of the commands, not behind them.
    """
    where = f" --state-dir {state_dir}" if state_dir is not None else ""
    run = launcher()
    known = {str(a["id"]): a for a in agents}
    plan: list[tuple[str, str]] = []
    for agent_id in (first, second):
        agent = known.get(agent_id, {})
        provider = str(agent.get("provider") or "other")
        command = PROVIDER_COMMAND.get(provider, f"<your {provider} command>")
        cwd = agent.get("worktree") or f"<{agent_id}'s own worktree>"
        plan.append((f"enrol {agent_id} as a managed worker (its own worktree, workspace approvals)",
                     f"{run} worker add {agent_id} {provider} --cwd {cwd} "
                     f"--approve workspace --max-attempts 1{where} -- {command}"))
    plan.append((f"start the turns, capped at {turns} (each one spends quota)",
                 f"{run} dispatch --max-turns {turns} --interval 2{where}"))
    plan.append(("watch what they say to each other",
                 f"{run} watch --between {first} {second}{where}"))
    return plan


# --- what to do next --------------------------------------------------------
#
# Every session so far has ended with somebody reading `status` and working out
# by hand which terminal to open. `status` reports state; this reports the next
# action, in the order that unblocks the most, with the command already
# written. It reads the database and nothing else.

#: Most blocking first. A dead letter and a stopped task need a person to
#: decide something; a queued delivery only needs a turn.
NEEDS_A_DECISION = ("dead_letter",)
STUCK_TASK_STATES = ("exhausted", "blocked")


def owed(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """What is waiting on whom, as actions rather than as state."""
    agents = {str(a["id"]): a for a in roster(conn)}
    actions: list[dict[str, Any]] = []

    # M7c: a session sitting there unverified, waiting for a person. First,
    # because until it is answered that session cannot do anything at all.
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for row in conn.execute(
            "SELECT id, agent_id, provider FROM claim_requests WHERE state = 'open' AND expires_at > ? "
            "ORDER BY seq", (now,)):
        actions.append({"priority": 0, "agent": str(row["agent_id"]), "kind": "claim",
                        "why": f"a {row['provider']} session is asking to be this agent — needs you, from another terminal",
                        "do": f"{launcher()} claim approve {row['id']}"})

    for row in conn.execute(
            "SELECT recipient_agent_id AS agent, COUNT(*) AS n FROM deliveries "
            "WHERE state = 'dead_letter' GROUP BY recipient_agent_id ORDER BY recipient_agent_id"):
        actions.append({"priority": 0, "agent": str(row["agent"]), "kind": "dead_letter",
                        "why": f"{row['n']} delivery(ies) nobody could deliver — needs you, not a turn",
                        "do": None})


    marks = ", ".join("?" * len(STUCK_TASK_STATES))
    for row in conn.execute(
            f"SELECT id, title, state, assigned_agent_id AS agent FROM tasks "
            f"WHERE state IN ({marks}) ORDER BY seq", STUCK_TASK_STATES):
        actions.append({"priority": 1, "agent": str(row["agent"] or ""), "kind": str(row["state"]),
                        "why": f"task {row['id']} is {row['state']}: {row['title']}",
                        "do": f"{launcher()} cancel {row['id']}  # or raise its budget and re-open it"})

    for row in conn.execute(
            "SELECT recipient_agent_id AS agent, COUNT(*) AS n FROM deliveries "
            "WHERE state = 'queued' GROUP BY recipient_agent_id ORDER BY recipient_agent_id"):
        agent_id = str(row["agent"])
        actions.append({"priority": 2, "agent": agent_id, "kind": "inbox",
                        "why": f"{row['n']} message(s) waiting, unread until its turn starts",
                        "do": start_command(agents.get(agent_id, {"id": agent_id}))})

    queued = {a["agent"] for a in actions if a["kind"] == "inbox"}
    for row in conn.execute(
            "SELECT id, title, assigned_agent_id AS agent FROM tasks WHERE state = 'claimed' ORDER BY seq"):
        agent_id = str(row["agent"] or "")
        if agent_id and agent_id not in queued:
            actions.append({"priority": 3, "agent": agent_id, "kind": "claimed",
                            "why": f"holding task {row['id']} with nothing queued: {row['title']}",
                            "do": start_command(agents.get(agent_id, {"id": agent_id}))})

    for row in conn.execute("SELECT id, title FROM tasks WHERE state = 'waiting' ORDER BY seq"):
        actions.append({"priority": 4, "agent": "", "kind": "waiting",
                        "why": f"task {row['id']} waits on its prerequisites: {row['title']}",
                        "do": None})

    actions.sort(key=lambda a: (a["priority"], a["agent"]))
    return actions


def start_command(agent: dict[str, Any]) -> str:
    """How to give that agent a turn: its own worktree, its own provider."""
    provider = str(agent.get("provider") or "other")
    command = PROVIDER_COMMAND.get(provider, f"<your {provider} command>")
    run = launcher_in(agent["worktree"]) if agent.get("worktree") else launcher()
    return f"{run} run --agent {agent['id']} -- {command}"

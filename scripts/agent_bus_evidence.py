#!/usr/bin/env python3
"""Export one workflow's record set from a bus state directory.

The M4 decision gate asks for real workflows "each with its correlation ID and
record set kept". Kept where, by whom, in what shape -- left to goodwill, that
is a promise nobody can audit later, so this is the command that makes it a
file: pick a conversation, get every record that belongs to it and a ledger row
to paste into `docs/agent-bus-decision-log.md`.

It opens the database read-only and never migrates it. Evidence that the tool
reading it can rewrite is not evidence, and an old state directory left from a
real workflow may be several schema versions behind.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agentd"))

from luciazero_agentd.redact import DEFAULT as DEFAULT_REDACTOR  # noqa: E402


class EvidenceError(RuntimeError):
    pass


def connect(state_dir: Path) -> sqlite3.Connection:
    """Read-only, so exporting evidence cannot change it."""
    path = state_dir / "bus.sqlite3"
    if not path.exists():
        raise EvidenceError(f"no bus database in {state_dir}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as exc:
        # An older state directory may not have every table this asks for.
        raise EvidenceError(f"{exc} (the state directory may predate this schema)") from exc


def decode(record: dict[str, Any], *fields: str) -> dict[str, Any]:
    for field in fields:
        value = record.get(field)
        if isinstance(value, str):
            try:
                record[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return record


def conversations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every conversation in the store, newest first: what there is to export."""
    return rows(conn, """
        SELECT correlation_id AS correlation_id,
               COUNT(*) AS messages,
               MIN(created_at) AS started_at,
               MAX(created_at) AS ended_at,
               GROUP_CONCAT(DISTINCT sender_agent_id) AS senders,
               GROUP_CONCAT(DISTINCT recipient_agent_id) AS recipients
          FROM messages
         WHERE correlation_id IS NOT NULL
      GROUP BY correlation_id
      ORDER BY MIN(created_at) DESC
    """)


def record_set(conn: sqlite3.Connection, correlation_id: str) -> dict[str, Any]:
    """Everything that belongs to one conversation: the messages, the
    deliveries they created, the tasks they name, the artifacts published
    against those tasks, the worktrees the participants wrote from, the runs
    that carried any of it, and the events that mention any of them."""
    messages = [decode(m, "payload") for m in rows(
        conn, "SELECT * FROM messages WHERE correlation_id = ? ORDER BY seq", (correlation_id,))]
    if not messages:
        raise EvidenceError(f"no messages carry correlation id {correlation_id!r}")
    message_ids = [str(m["id"]) for m in messages]
    marks = ", ".join("?" * len(message_ids))
    deliveries = rows(conn, f"SELECT * FROM deliveries WHERE message_id IN ({marks}) ORDER BY seq", tuple(message_ids))

    task_ids = sorted({str(m["payload"].get("task_id")) for m in messages
                       if isinstance(m.get("payload"), dict) and m["payload"].get("task_id")}
                      | {str(d["task_id"]) for d in deliveries if d.get("task_id")})
    tasks = artifacts = []
    if task_ids:
        marks = ", ".join("?" * len(task_ids))
        tasks = [decode(t, "payload", "budget") for t in rows(
            conn, f"SELECT * FROM tasks WHERE id IN ({marks}) ORDER BY seq", tuple(task_ids))]
        artifacts = rows(conn, f"SELECT * FROM artifacts WHERE task_id IN ({marks}) ORDER BY seq", tuple(task_ids))

    agents = sorted({str(m["sender_agent_id"]) for m in messages} | {str(m["recipient_agent_id"]) for m in messages})
    marks = ", ".join("?" * len(agents))
    worktrees = rows(conn, f"SELECT * FROM worktrees WHERE agent_id IN ({marks})", tuple(agents))

    # The first thing the recipient's session did after the message landed.
    # A pull-beta turn has no `turn_started_at` -- nothing records the moment a
    # person gave the session its turn -- so the wait to the acknowledgement is
    # two unlabelled things at once. This splits off the part that is not in
    # doubt: from the recipient's first bus call to its acknowledgement is the
    # agent working. What comes before it stays ambiguous, and is a ceiling on
    # the user-trigger delay rather than a measurement of it.
    for delivery in deliveries:
        sent = next((m["created_at"] for m in messages if str(m["id"]) == str(delivery["message_id"])), None)
        if sent is None or not delivery.get("acknowledged_at"):
            continue
        # No upper bound on `at`: the acknowledgement's own event is written
        # microseconds *after* the row it describes, so bounding by
        # `acknowledged_at` throws away the very call being looked for.
        touch = conn.execute(
            "SELECT MIN(at) AS first FROM events WHERE actor = ? AND at > ?",
            (str(delivery["recipient_agent_id"]), sent)).fetchone()
        delivery["first_touch_at"] = touch["first"] if touch and touch["first"] else None
        # M7f: when the bus started the turn itself, it wrote down when. That
        # moment is the boundary the pull beta never had -- before it, the bus
        # had not knocked yet; after it, a model was starting. Both halves are
        # then measurements, and neither is a person nobody timed.
        nudged = conn.execute(
            "SELECT at, payload FROM events WHERE kind = 'turn.nudged' "
            "AND entity_id = ? AND at > ? ORDER BY at, seq LIMIT 1",
            (str(delivery["recipient_agent_id"]), sent)).fetchone()
        delivery["nudged_at"] = nudged["at"] if nudged else None
        # ...and what the proxy could see of the terminal as it typed. Present
        # only for a knock recorded by a version that observed it, so an older
        # record set keeps exactly the fields it always had.
        delivery["knock_observed"] = decode(dict(nudged), "payload")["payload"] if nudged else None
        # A keystroke inside the gap is the one record that says a person was
        # in it. Without this the gap after a knock is a single unlabelled
        # span covering a session starting, a swallowed keystroke and somebody
        # deciding whether to authorise the work -- the ambiguity that renamed
        # the field measuring it.
        if delivery["nudged_at"] and delivery["first_touch_at"]:
            typed = conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE kind = 'turn.human_input' "
                "AND entity_id = ? AND at > ? AND at <= ?",
                (str(delivery["recipient_agent_id"]), delivery["nudged_at"],
                 delivery["first_touch_at"])).fetchone()
            delivery["human_input_after_knock"] = int(typed["n"]) if typed else 0

    delivery_ids = [str(d["id"]) for d in deliveries]
    runs: list[dict[str, Any]] = []
    if delivery_ids:
        marks = ", ".join("?" * len(delivery_ids))
        runs = rows(conn, f"SELECT * FROM runs WHERE delivery_id IN ({marks}) ORDER BY seq", tuple(delivery_ids))

    entities = set(message_ids) | set(delivery_ids) | set(task_ids) | {str(a["id"]) for a in artifacts} | {str(r["id"]) for r in runs}
    events = [decode(e, "payload") for e in rows(conn, "SELECT * FROM events ORDER BY seq")
              if str(e["entity_id"]) in entities]

    return {
        "correlation_id": correlation_id,
        "agents": agents,
        "messages": messages,
        "deliveries": deliveries,
        "tasks": tasks,
        "artifacts": artifacts,
        "worktrees": worktrees,
        "runs": runs,
        "events": events,
    }


def _at(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def waits(record: dict[str, Any]) -> list[dict[str, Any]]:
    """How long each delivery sat before somebody opened the turn that read it.

    This is the decision gate's second criterion made measurable: in the pull
    beta nothing acknowledges a delivery until a human starts that agent's
    session, so the gap between the send and the acknowledgement *is* the cost
    of the user-started turn. Reconstructing it from memory in a retro is
    guesswork; the records have it exactly."""
    sent = {str(m["id"]): _at(m.get("created_at")) for m in record["messages"]}
    measured = []
    for delivery in record["deliveries"]:
        started, acknowledged = sent.get(str(delivery["message_id"])), _at(delivery.get("acknowledged_at"))
        if started is None or acknowledged is None:
            continue
        entry = {"delivery_id": str(delivery["id"]),
                 "recipient": str(delivery["recipient_agent_id"]),
                 "seconds": round((acknowledged - started).total_seconds(), 3),
                 "silent_seconds": None, "agent_seconds": None}
        touched = _at(delivery.get("first_touch_at"))
        if touched is not None and touched > acknowledged:
            # The acknowledgement was that session's first call: there is no
            # working half to split off.
            touched = acknowledged
        if touched is not None:
            # Named for what each half is, not for what it is assumed to be:
            # `silent` is the stretch with no bus call from that agent at all
            # (a person not yet at the keyboard, a model not yet at its first
            # tool call, or both), `agent` is the part it was demonstrably
            # working.
            entry["silent_seconds"] = round((touched - started).total_seconds(), 3)
            entry["agent_seconds"] = round((acknowledged - touched).total_seconds(), 3)
            knocked = _at(delivery.get("nudged_at"))
            if knocked is not None and started <= knocked <= touched:
                # The silent half splits at the knock, and only the first
                # piece is what its name says: the bus deciding to knock is a
                # machine, start to finish. The second was called
                # `startup_seconds`, as if a session were starting. It is not
                # only that. In workflow 2 one knock was typed while the
                # provider was mid-turn and the keystroke was swallowed, so
                # the span was a lost keystroke waiting to be noticed; in
                # another it was a person deciding to authorise the work.
                # Nothing recorded separates those from a session starting, so
                # the field is named for what it actually measures, and the
                # split is not a claim that no person was in it.
                entry["knock_seconds"] = round((knocked - started).total_seconds(), 3)
                entry["next_bus_call_seconds"] = round((touched - knocked).total_seconds(), 3)
                entry["attributed"] = True
                # What the terminal looked like when the knock went in, and
                # whether anybody touched it afterwards. Observations, not
                # verdicts: a pane that had printed nothing for a minute was
                # very likely idle and a pane printing a tenth of a second ago
                # was very likely mid-turn, but which of those it was is the
                # reader's call and this only supplies the numbers.
                seen = delivery.get("knock_observed")
                if isinstance(seen, dict):
                    entry["provider_quiet_for"] = seen.get("provider_quiet_for")
                    entry["human_typed_ago"] = seen.get("human_typed_ago")
                if delivery.get("human_input_after_knock") is not None:
                    entry["human_input_after_knock"] = int(delivery["human_input_after_knock"])
        measured.append(entry)
    return measured


def human_gap(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def summarise(record: dict[str, Any]) -> dict[str, Any]:
    messages = record["messages"]
    deliveries = record["deliveries"]
    tasks = record["tasks"]
    measured = waits(record)
    return {
        "correlation_id": record["correlation_id"],
        "started_at": messages[0]["created_at"],
        "ended_at": messages[-1]["created_at"],
        "agents": record["agents"],
        "messages": len(messages),
        "deliveries": len(deliveries),
        "delivery_states": sorted({str(d["state"]) for d in deliveries}),
        "tasks": len(tasks),
        "task_states": sorted({str(t["state"]) for t in tasks}),
        "artifacts": len(record["artifacts"]),
        "artifact_kinds": sorted({str(a["kind"]) for a in record["artifacts"]}),
        "runs": len(record["runs"]),
        # A pull-beta workflow has no runs: the user started every turn. That
        # is exactly the cost the decision gate is asking about, so it is
        # counted rather than left to be inferred.
        "turns": "user-started" if not record["runs"] else f"{len(record['runs'])} dispatched",
        "unverified_writes": sorted({str(e["kind"]) for e in record["events"]
                                     if isinstance(e.get("payload"), dict) and e["payload"].get("trust") == "asserted"}),
        "waits": measured,
        "user_started_turns": len(measured),
        "longest_wait_seconds": max((w["seconds"] for w in measured), default=None),
        # The ceiling on the user-trigger delay: what a retro still has to
        # attribute, and what it must not claim the records attributed for it.
        # Only the waits nothing accounted for. A nudged turn's silent half is
        # split by `turn.nudged` into two measurements, so it is not a ceiling
        # on anything and must not be reported as one.
        "longest_silent_seconds": max((w["silent_seconds"] for w in measured
                                       if w["silent_seconds"] is not None
                                       and not w.get("attributed")), default=None),
        "nudged_turns": sum(1 for w in measured if w.get("attributed")),
        # How many of those gaps had a person typing in them. A gap with a
        # keystroke in it is not the bus waiting on a model, and counting them
        # is the difference between reporting machine latency and reporting a
        # number with somebody's lunch break inside it.
        "nudged_turns_with_human_input": sum(1 for w in measured if w.get("human_input_after_knock")),
        "total_wait_seconds": round(sum(w["seconds"] for w in measured), 3) if measured else None,
    }


def ledger_row(summary: dict[str, Any], *, label: str, path: Optional[Path]) -> str:
    """One markdown row for the decision log, already filled in."""
    cost = ""
    if summary["user_started_turns"]:
        cost = (f", {summary['user_started_turns']} turn(s) waited, longest "
                f"{human_gap(float(summary['longest_wait_seconds']))}")
        if summary.get("nudged_turns"):
            cost += f", {summary['nudged_turns']} bus-started"
        # The ledger says how much of that is still unattributed, so a row can
        # never be read as evidence of a wait nobody measured.
        if summary.get("longest_silent_seconds") is not None:
            silent = float(summary["longest_silent_seconds"])
            # Seconds, not `human_gap`, under ten minutes: rounding 107s and
            # 120s both to "2m" hides the very split this column exists for.
            cost += f" (<={silent:.0f}s unattributed)" if silent < 600 else f" (<={human_gap(silent)} unattributed)"
    return (f"| {label} | `{summary['correlation_id']}` | {summary['started_at']} | "
            f"{', '.join(summary['agents'])} | {summary['tasks']} task(s) {'/'.join(summary['task_states'])}, "
            f"{summary['messages']} message(s), {summary['artifacts']} artifact(s) | {summary['turns']}{cost} | "
            f"{'`' + str(path) + '`' if path else 'not exported'} |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, help="the bus state directory to read (read-only)")
    parser.add_argument("--list", action="store_true", help="list the conversations it holds")
    parser.add_argument("--correlation", default=None, help="the conversation to export")
    parser.add_argument("--out", default=None, help="write the record set here as JSON")
    parser.add_argument("--label", default="workflow", help="what to call this workflow in the ledger row")
    args = parser.parse_args()

    state_dir = Path(args.state_dir).expanduser()
    try:
        conn = connect(state_dir)
    except EvidenceError as exc:
        print(f"evidence: {exc}", file=sys.stderr)
        return 2
    try:
        if args.list or not args.correlation:
            found = conversations(conn)
            if not found:
                print("no conversations in this state directory", file=sys.stderr)
                return 1
            for row in found:
                print(f"{row['correlation_id']}  {row['messages']:>3} message(s)  {row['started_at']}  "
                      f"{row['senders']} -> {row['recipients']}")
            if not args.correlation:
                return 0
        record = record_set(conn, args.correlation)
    except EvidenceError as exc:
        print(f"evidence: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    # The daemon redacts on the way in; this is the second pass, because an
    # evidence file is the one artifact meant to be read by other people.
    scrubbed, hits = DEFAULT_REDACTOR.json(record)
    out = Path(args.out).expanduser() if args.out else None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(scrubbed, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    summary = summarise(record)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    if hits:
        print(f"redacted {hits} secret-shaped value(s) on the way out", file=sys.stderr)
    print()
    print(ledger_row(summary, label=args.label, path=out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

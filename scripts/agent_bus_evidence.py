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


def summarise(record: dict[str, Any]) -> dict[str, Any]:
    messages = record["messages"]
    deliveries = record["deliveries"]
    tasks = record["tasks"]
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
    }


def ledger_row(summary: dict[str, Any], *, label: str, path: Optional[Path]) -> str:
    """One markdown row for the decision log, already filled in."""
    return (f"| {label} | `{summary['correlation_id']}` | {summary['started_at']} | "
            f"{', '.join(summary['agents'])} | {summary['tasks']} task(s) {'/'.join(summary['task_states'])}, "
            f"{summary['messages']} message(s), {summary['artifacts']} artifact(s) | {summary['turns']} | "
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

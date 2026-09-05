#!/usr/bin/env python3
"""Rebuild a `claim_requests` table that migration 8 never wrote.

One machine's store carries a `claim_requests` table without `code_hash`,
stamped `user_version = 8`. The released migration always created that column
(it arrived whole in the M7c commit, 49 insertions and no deletions), so this
is not a state any published version can produce: the store was migrated by a
development build whose SCHEMA_V8 predated the security review that replaced
process ancestry with a one-time code. The symptom is every `agent_claim_begin`
answering `Unavailable`, because `open_claim` inserts a column that is not
there.

The repair is a rebuild rather than an `ALTER TABLE ADD COLUMN`, so the result
is byte-identical to the schema a fresh store gets, and it refuses to run
unless the table is empty -- claim requests are the audit trail of who asked to
be whom, and a rebuild that dropped one would be destroying exactly the record
this table exists to keep.

Every step is a guard:

* only ever the default store, named here and taken from nowhere else;
* a backup through SQLite's own backup API, which is consistent even while
  the daemon holds the database open;
* a refusal if the table holds any row at all;
* one `BEGIN IMMEDIATE` transaction, `PRAGMA foreign_key_check` before the
  commit, and a rollback on any failure;
* the schema compared against a freshly migrated store afterwards, so the
  answer to "did it work" is a diff and not a hope.

Run it with the daemon stopped or running; restart the service afterwards
(`luciazero-agentd service install`) so the daemon reopens the store.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from luciazero_agentd.migrations import LATEST_VERSION, SCHEMA_V8  # noqa: E402
from luciazero_agentd.store import Store, _split_statements  # noqa: E402

#: The one store this script will touch. Not an argument: a repair that drops
#: a table should not be pointable at a database somebody names on a whim.
DB = Path("~/.luciazero/agent-bus/bus.sqlite3").expanduser()
TABLE = "claim_requests"


def refuse(reason: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"refused: {reason}", file=sys.stderr)
    raise SystemExit(1)


def objects(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """Every schema object, whitespace-normalised so formatting is not a diff."""
    return {(kind, name): " ".join((sql or "").split())
            for kind, name, sql in conn.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}


def fresh_schema() -> dict[tuple[str, str], str]:
    """What a store created by this checkout looks like."""
    with tempfile.TemporaryDirectory(prefix="claim-repair-") as tmp:
        path = Path(tmp) / "fresh.sqlite3"
        with Store.open(str(path)) as store:
            store.migrate()
        with sqlite3.connect(path) as conn:
            return objects(conn)


def main() -> int:
    if not DB.is_file():
        refuse(f"{DB} is not a file")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != LATEST_VERSION:
        refuse(f"{DB} is at schema {version}, not {LATEST_VERSION}; "
               "run the daemon once to migrate it before repairing anything")

    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")]
    if not columns:
        refuse(f"{TABLE} does not exist; this is not the drift this script repairs")
    if "code_hash" in columns:
        print(f"nothing to do: {TABLE} already has code_hash")
        return 0

    rows = conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    if rows:
        refuse(f"{TABLE} holds {rows} row(s); rebuilding would destroy claim history. "
               "Decide what to do with them by hand.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = DB.with_name(f"{DB.name}.pre-claim-repair-{stamp}")
    with sqlite3.connect(backup) as target:
        conn.backup(target)
    print(f"backup  {backup}")

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"DROP TABLE {TABLE}")
        for statement in _split_statements(SCHEMA_V8):
            conn.execute(statement)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"{len(violations)} dangling foreign key reference(s)")
        conn.execute("COMMIT")
    except BaseException as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        print(f"rolled back: {exc}", file=sys.stderr)
        print(f"the store is unchanged; the backup at {backup} is a copy of it", file=sys.stderr)
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    live, fresh = objects(conn), fresh_schema()
    differences = sorted({key for key in set(live) | set(fresh)
                          if live.get(key) != fresh.get(key)})
    if differences:
        refuse("the schema still differs from a fresh store: "
               + ", ".join(f"{kind} {name}" for kind, name in differences))
    print(f"repaired {TABLE}: {len(objects(conn))} schema objects match a fresh store")
    print("restart the daemon:  luciazero-agentd service install")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

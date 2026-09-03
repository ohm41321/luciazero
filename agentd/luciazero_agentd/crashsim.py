"""Crash simulator used by the M1 crash suite.

Runs one store operation in a child process and hard-kills the process
(``os._exit``) at a named point around COMMIT. The parent then reopens the
database and checks the transition is either fully absent or fully present.

Usage: python3 -m luciazero_agentd.crashsim DB OP POINT ARG...
"""

from __future__ import annotations

import os
import sys

from .store import Store

KILL_EXIT = 137


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: crashsim DB OP POINT ARG...", file=sys.stderr)
        return 64
    db, op, point, *args = argv

    def hook(name: str) -> None:
        if name == point:
            sys.stdout.flush()
            os._exit(KILL_EXIT)

    store = Store.open(db, crash_hook=hook)
    store.migrate()
    if op == "send_message":
        sender, recipient, key = args
        store.send_message(sender=sender, recipient=recipient, kind="finding", payload={"crash": point}, idempotency_key=key)
    elif op == "ack":
        delivery_id, agent = args
        store.ack_delivery(delivery_id, agent)
    elif op == "complete_delivery":
        delivery_id, agent = args
        store.complete_delivery(delivery_id, agent)
    elif op == "create_task":
        creator, key = args
        store.create_task(title="crash task", created_by=creator, idempotency_key=key)
    elif op == "claim_task":
        task_id, agent = args
        store.claim_task(task_id, agent)
    elif op == "complete_task":
        task_id, agent = args
        store.complete_task(task_id, agent, result={"ok": True})
    else:
        print(f"unknown op {op}", file=sys.stderr)
        return 64
    print("completed-without-crash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

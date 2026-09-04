#!/usr/bin/env python3
"""A deterministic managed worker: what a model would do on a dispatched turn,
without a model.

The dispatcher starts it exactly as it would start a provider -- the session
credential and the bus URL arrive in the environment, never on the command
line -- and it does the `/lucia-bus` procedure with its own credential: ask the
daemon who it is, read the inbox, acknowledge, claim, work, publish, complete,
answer the sender, and mark the delivery handled.

It exists so the M6 gate can prove the dispatcher itself. Modes (LZ_WORKER_MODE):

    work   do the turn (default)
    hang   start and never finish, so a kill can be tested
    fail   exit non-zero without touching the bus
    idle   exit 0 without touching the bus, which must still count as a failed
           attempt: a clean exit is not evidence that anything happened
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_bus_mcp_gate import GateError, McpClient  # noqa: E402

URL_ENV = "LUCIAZERO_AGENT_BUS_URL"
TOKEN_ENV = "LUCIAZERO_AGENT_BUS_TOKEN"
AGENT_ENV = "LUCIAZERO_AGENT_BUS_AGENT"


def main() -> int:
    mode = os.environ.get("LZ_WORKER_MODE", "work")
    if mode == "hang":
        print("worker: hanging until killed", flush=True)
        while True:
            time.sleep(0.2)
    if mode == "fail":
        print("worker: failing on purpose", file=sys.stderr, flush=True)
        return 1
    if mode == "idle":
        print("worker: exiting without touching the bus", flush=True)
        return 0

    url, credential = os.environ.get(URL_ENV), os.environ.get(TOKEN_ENV)
    if not url or not credential:
        print("worker: the dispatcher did not pass a bus url and credential", file=sys.stderr)
        return 2
    bus = McpClient(url, credential)
    bus.initialize()
    who = bus.call("agent_whoami", {})
    if not who.get("verified"):
        print(f"worker: the daemon does not know who I am: {json.dumps(who)}", file=sys.stderr)
        return 3
    agent_id = str(who["agent_id"])
    print(f"worker: the daemon says I am {agent_id}", flush=True)

    inbox = bus.call("message_inbox", {"agent_id": agent_id})["items"]
    if not inbox:
        print("worker: nothing queued for me", flush=True)
        return 0
    item = inbox[0]
    bus.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": agent_id})
    task_id = item["payload"].get("task_id")
    if task_id:
        bus.call("task_claim", {"task_id": task_id, "agent_id": agent_id})
        bus.call("task_complete", {"task_id": task_id, "agent_id": agent_id, "result": {"handled_by": "managed turn"}})
    bus.call("message_send", {
        "sender": agent_id, "recipient": item["sender"], "kind": "result",
        "payload": {"task_id": task_id, "outcome": "done"},
        "reply_to": item["message_id"], "correlation_id": item["correlation_id"],
    })
    bus.call("message_ack", {"delivery_id": item["delivery_id"], "agent_id": agent_id, "outcome": "completed"})
    print(f"worker: finished delivery {item['delivery_id']}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"worker: {exc}", file=sys.stderr)
        raise SystemExit(4)

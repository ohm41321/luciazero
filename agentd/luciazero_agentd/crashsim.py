"""Crash simulator used by the M1 crash suite and the M6 dispatch matrix.

Runs one store operation in a child process and hard-kills the process
(``os._exit``) at a named point around COMMIT. The parent then reopens the
database and checks the transition is either fully absent or fully present.

The dispatch operations are here for the same reason the pull-beta ones are:
a managed turn spends real money and holds a live credential, so "the
dispatcher was killed" has to be a tested state at every commit point, not a
hope. ``recover`` is what the next dispatcher runs at startup, and running it
after any of these kills is what proves the delivery still reaches exactly one
outcome.

Usage: python3 -m luciazero_agentd.crashsim DB OP POINT ARG...
"""

from __future__ import annotations

import os
import sys

from .store import Store

KILL_EXIT = 137
#: The dispatcher's own bookkeeping is neither a human's command nor a bound
#: session's claim (ADR 0006), so these run under the label it uses.
DISPATCH_OPS = ("begin_turn", "finish_run", "recover", "acquire_lease", "release_lease",
                "record_provider_session", "record_run_process", "dead_letter_delivery")


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
    if op in DISPATCH_OPS:
        store.trust = "system"
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
    elif op == "bind_worktree":
        agent, path = args
        store.bind_worktree(agent, path)
    elif op == "begin_turn":
        delivery_id, agent, lease_id, generation, session_id, binding_id = args
        store.begin_turn(delivery_id, agent_id=agent, lease_id=lease_id, generation=int(generation),
                         session_id=session_id, binding_id=binding_id, max_attempts=2, approval_policy="deny")
    elif op == "finish_run":
        run_id, state = args
        store.finish_run(run_id, state=state, exit_state="exit 0", error=None)
    elif op == "recover":
        # What the next dispatcher does at startup: settle the runs whose owner
        # is gone, then the deliveries no live run covers.
        store.recover_runs(alive=lambda pid, started_at=None: False, by="dispatch:crashsim")
        store.recover_deliveries(by="dispatch:crashsim")
    elif op == "acquire_lease":
        agent, session_id = args
        store.acquire_lease("session", agent, holder="dispatch:crashsim", session_id=session_id,
                            holder_pid=os.getpid(), holder_started_at=None)
    elif op == "release_lease":
        lease_id, = args
        store.release_lease(lease_id, by="dispatch:crashsim", reason="crash matrix")
    elif op == "record_provider_session":
        session_id, provider_session_id, generation = args
        store.record_provider_session(session_id, provider_session_id=provider_session_id, generation=int(generation))
    elif op == "record_run_process":
        run_id, pid = args
        store.record_run_process(run_id, pid=int(pid), started_at=None)
    elif op == "dead_letter_delivery":
        delivery_id, reason = args
        store.dead_letter_delivery(delivery_id, by="dispatch:crashsim", reason=reason)
    elif op == "consume_approval":
        task_id, operation, nonce, agent = args
        store.consume_approval(task_id, operation, nonce, agent)
    else:
        print(f"unknown op {op}", file=sys.stderr)
        return 64
    print("completed-without-crash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

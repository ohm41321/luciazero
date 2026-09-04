#!/usr/bin/env python3
"""Two managed agents answering each other, with the exchange printed as it
happens.

The pull beta needs a person to start every turn. `watch` made the traffic
visible; this makes it move on its own: both sides are managed workers, so a
message queued for one of them starts that one's turn, whose reply queues a
turn for the other. Nobody is at either keyboard.

Which is exactly why it is capped. Turns are what cost money, and a loop where
each answer buys the next one has no natural end, so `--turns` is a hard stop
enforced by the dispatcher's own `--max-turns`, and the whole thing refuses to
start without `--spend-quota`. `--rehearse` runs the identical flow against the
offline worker for nothing, which is what proves the mechanism before any
quota is spent.

What it isolates, and what it cannot:

* the bus state directory and both workers' working directories are disposable
  temporary directories, so the user's own `~/.luciazero` and both checkouts
  are untouched;
* the provider homes are *not* redirected: a real turn needs the user's real
  credentials, and each CLI writes its own transcript where it always does.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agentd"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_bus_e2e import SKIP_EXIT, Daemon, E2EError  # noqa: E402
from agent_bus_mcp_gate import GateError  # noqa: E402
from luciazero_agentd import watch  # noqa: E402
from luciazero_agentd.store import Store, StoreError  # noqa: E402

#: The two who talk, and the identity that starts them off. The operator is a
#: human-bound session (this script), never a worker: a dispatched agent
#: cannot also hold a terminal, and the first message has to come from
#: somewhere that is not part of the loop.
CHAT = {"codex": "chat-codex", "claude": "chat-claude"}
OPERATOR = "chat-operator"
REHEARSAL = {"codex": "chat-rehearsal-a", "claude": "chat-rehearsal-b"}
REHEARSAL_COMMAND = [sys.executable, str(ROOT / "scripts" / "agent_bus_worker.py")]
DEFAULT_TURNS = 4
DEFAULT_TURN_TIMEOUT = 300
# `workspace`, not `accept`: the turn may work inside its own disposable
# directory and nowhere else. ADR 0001 null result 3 is why it is not `deny` --
# Codex routes a model-selected MCP tool call through the approval flow.
POLICY = "workspace"
TOPIC = ("Say hello to your peer and ask one short question about how the two of you should "
         "split the next piece of work on this bus.")
SEED = (
    "You are talking to {peer} through the bus, and {peer} is answering by itself: there is no "
    "human in either session.\n"
    "{topic}\n"
    "Rules for this conversation: reply to every message you receive from {peer} with at most "
    "three sentences and one question back, addressed to {peer} with message_send. Do not create "
    "tasks, do not edit files, do not run commands. Reply to {peer}, never to the operator "
    "who sent this. Acknowledge the delivery you read and complete it when you have replied."
)


class ChatError(E2EError):
    pass


def store_of(daemon: Daemon) -> Store:
    store = Store.open(daemon.state_dir / "bus.sqlite3")
    store.migrate()
    store.trust = "system"
    return store


def cli_env(daemon: Daemon) -> dict[str, str]:
    return dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "agentd"),
                LUCIAZERO_AGENT_BUS_HOME=str(daemon.state_dir), LZ_WORKER_MODE="work")


def agentd(daemon: Daemon, *args: str, timeout: int = 60) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "luciazero_agentd", *args, "--state-dir", str(daemon.state_dir)],
        cwd=ROOT / "agentd", env=cli_env(daemon), capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise ChatError(f"luciazero-agentd {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def enrol(daemon: Daemon, agent_id: str, provider: str, command: list[str], cwd: Path, timeout: int) -> None:
    """The human channel enrols each side; nothing on the bus can.

    Not through `agentd()`: everything after the `--` is the provider command,
    so `--state-dir` has to go before it (ADR 0001's swallowed-flag trap).
    """
    argv = [sys.executable, "-m", "luciazero_agentd", "worker", "add", agent_id, provider,
            "--cwd", str(cwd), "--max-attempts", "1", "--timeout", str(timeout),
            "--approve", POLICY, "--state-dir", str(daemon.state_dir), "--", *command]
    result = subprocess.run(argv, cwd=ROOT / "agentd", env=cli_env(daemon),
                            capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise ChatError(f"worker add {agent_id} failed: {result.stderr.strip()}")


def open_the_conversation(daemon: Daemon, first: str, peer: str, topic: str, run: str) -> dict[str, Any]:
    """One message from the operator's own bound session. Everything after
    this is the two of them."""
    bus = daemon.session(OPERATOR)
    message = bus.call("message_send", {
        "sender": OPERATOR, "recipient": first, "kind": "question",
        "payload": {"text": SEED.format(peer=peer, topic=topic)},
        "idempotency_key": f"{run}-seed"})
    with store_of(daemon) as store:
        record = store.get_message(str(message["id"]))
    return {"message_id": str(message["id"]),
            "correlation_id": str(record.get("correlation_id") or message["id"])}


def dispatch(daemon: Daemon, turns: int, timeout: int) -> str:
    """The shipped dispatcher, in its own process, with the cap it enforces
    itself -- a budget the runner cannot forget to apply. It also stops when
    the work runs out, so a conversation that ends early ends the run."""
    result = subprocess.run(
        [sys.executable, "-m", "luciazero_agentd", "dispatch", "--max-turns", str(turns),
         "--stop-when-idle", "--interval", "1", "--state-dir", str(daemon.state_dir)],
        cwd=ROOT / "agentd", env=cli_env(daemon), capture_output=True, text=True,
        timeout=timeout * turns + 180)
    if result.returncode != 0:
        raise ChatError(f"dispatch exited {result.returncode}: {result.stderr.strip()}")
    return (result.stdout + result.stderr).strip()


def transcript(daemon: Daemon, correlation_id: str, colour: bool) -> list[str]:
    """What they said, rendered by the same code `watch` renders it with."""
    follower = watch.Follower(daemon.state_dir / "bus.sqlite3")
    renderer = watch.Renderer(colour=colour, payload="preview")
    try:
        return [renderer.line(event) for event in follower.poll()
                if event["what"] != "message" or str(event.get("correlation_id")) == correlation_id]
    finally:
        follower.close()


def summarise(daemon: Daemon, correlation_id: str, participants: list[str]) -> dict[str, Any]:
    with store_of(daemon) as store:
        runs = [r for r in store.list_runs(limit=50) if str(r["agent_id"]) in participants]
    # Read-only, through the same door the evidence exporter uses: counting
    # what happened must not be able to change it.
    conn = watch.open_read_only(daemon.state_dir / "bus.sqlite3")
    try:
        messages = [dict(r) for r in conn.execute(
            "SELECT sender_agent_id, recipient_agent_id FROM messages WHERE correlation_id = ? ORDER BY seq",
            (correlation_id,)).fetchall()]
    finally:
        conn.close()
    exchanged = [m for m in messages if str(m["sender_agent_id"]) in participants]
    return {
        "correlation_id": correlation_id,
        "turns": len(runs),
        "turns_by": sorted({str(r["agent_id"]) for r in runs}),
        "completed_turns": len([r for r in runs if r["state"] == "completed"]),
        "messages": len(messages),
        "replies_from_the_agents": len(exchanged),
        "failed_turns": [{"agent": str(r["agent_id"]), "exit_state": r["exit_state"], "error": r["error"],
                          "log": str(r["output_ref"])} for r in runs if r["state"] != "completed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spend-quota", action="store_true",
                        help="required: every turn here starts a real model that costs money")
    parser.add_argument("--rehearse", action="store_true",
                        help="the same flow against the offline worker: proves the loop, spends nothing")
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS,
                        help=f"hard cap on provider turns (default {DEFAULT_TURNS})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TURN_TIMEOUT, help="seconds per turn")
    parser.add_argument("--topic", default=TOPIC, help="what to start them talking about")
    parser.add_argument("--first", choices=("claude", "codex"), default="claude",
                        help="which side gets the opening message")
    parser.add_argument("--keep", action="store_true", help="keep the temporary state directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.turns < 1:
        print("chat: --turns must be at least 1", file=sys.stderr)
        return 64
    if not (args.spend_quota or args.rehearse):
        print(f"This starts {args.turns} real provider turns (up to {args.timeout}s each) and spends",
              file=sys.stderr)
        print("the user's Codex and Claude quota. Re-run with --spend-quota once that is approved,",
              file=sys.stderr)
        print("or with --rehearse to prove the same loop against the offline worker for nothing.",
              file=sys.stderr)
        return 64

    names = dict(REHEARSAL if args.rehearse else CHAT)
    commands: dict[str, list[str]] = {}
    missing = []
    for provider in ("codex", "claude"):
        if args.rehearse:
            peer = names["codex" if provider == "claude" else "claude"]
            commands[provider] = [*REHEARSAL_COMMAND, "--reply-to", peer]
            continue
        found = shutil.which(provider)
        if found is None:
            missing.append(provider)
        else:
            commands[provider] = [found]
    if missing:
        print(f"skip: provider CLI not found: {', '.join(missing)}", file=sys.stderr)
        return SKIP_EXIT

    colour = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    dim, off = ("\033[2m", "\033[0m") if colour else ("", "")

    def narrate(text: str) -> None:
        print(f"{dim}{text}{off}", flush=True)

    root = Path(tempfile.mkdtemp(prefix="luciazero-agent-bus-chat-"))
    run = f"chat-{uuid.uuid4().hex[:10]}"
    daemon = Daemon(root / "state")
    first, second = names[args.first], names["codex" if args.first == "claude" else "claude"]
    report: dict[str, Any] = {"root": str(root)}
    try:
        daemon.start()
        narrate(f"# daemon {daemon.url} on {daemon.state_dir} (disposable; the real bus is untouched)")
        agentd(daemon, "roster", "add", OPERATOR, "other", "operator")
        daemon.bind(OPERATOR, "other")
        for provider in ("codex", "claude"):
            agent_id = names[provider]
            cwd = root / f"work-{provider}"
            cwd.mkdir(parents=True, exist_ok=True)
            agentd(daemon, "roster", "add", agent_id,
                   "other" if args.rehearse else provider, "peer", "--capability", "bus")
            enrol(daemon, agent_id, "other" if args.rehearse else provider,
                  commands[provider], cwd, args.timeout)
            narrate(f"#   {agent_id} enrolled: {' '.join(commands[provider])} "
                    f"(approvals: {POLICY}, one attempt, {args.timeout}s, cwd {cwd})")
        opened = open_the_conversation(daemon, first, second, args.topic, run)
        narrate(f"# {OPERATOR} says one thing to {first}; after that nobody is at either keyboard")
        narrate(f"# up to {args.turns} turn(s)"
                + (" (no quota: the offline worker)" if args.rehearse else " — this spends quota now"))
        output = dispatch(daemon, args.turns, args.timeout)
        print()
        for line in transcript(daemon, opened["correlation_id"], colour):
            print(line, flush=True)
        print()
        report.update(summarise(daemon, opened["correlation_id"], [first, second]))
        report["dispatch_output"] = output
    except (E2EError, GateError, StoreError, subprocess.SubprocessError, OSError) as exc:
        print(f"chat: {exc}", file=sys.stderr)
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
        return 1
    finally:
        daemon.stop()

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    narrate(f"# {report['turns']} turn(s) ran, {report['completed_turns']} completed; "
            f"{report['replies_from_the_agents']} message(s) came from the agents themselves")
    for failure in report["failed_turns"]:
        print(f"chat: {failure['agent']} turn {failure['exit_state']}: {failure['error']} "
              f"(log: {failure['log']})", file=sys.stderr)
    if args.keep:
        narrate(f"# kept: {daemon.state_dir}")
        narrate(f"#   ./scripts/agent-bus-evidence.sh --state-dir {daemon.state_dir} "
                f"--correlation {report['correlation_id']}")
    else:
        shutil.rmtree(root, ignore_errors=True)
    # A conversation is two agents answering each other: one turn that talks to
    # nobody is a failure of the thing this exists to show.
    if report["replies_from_the_agents"] < 2:
        print("chat: the agents did not answer each other", file=sys.stderr)
        return 1
    print(f"PASS  agent bus autonomous chat ({report['turns']} turn(s), "
          f"{report['replies_from_the_agents']} agent message(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

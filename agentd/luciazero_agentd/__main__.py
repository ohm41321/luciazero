"""``python3 -m luciazero_agentd`` entry point.

serve          run the daemon in the foreground (writes endpoint.json + token)
status         print what is waiting on whom, via the running daemon
client-config  print the exact mcp-add commands for Claude Code and Codex CLI
approve        grant one single-use approval nonce for a sensitive operation
               (interactive terminal only; writes the store directly, never
               through the agent-facing MCP endpoint)
cancel         cancel an open or claimed task (human channel, direct store)
roster add     name an agent so peers can address it before its first session
terminal list  provider sessions that own a terminal, and what each is bound to
attach         bind one already-running terminal to an agent (interactive only:
               it prints that terminal's session credential)
run            start a provider with the binding already in place; never
               prints the credential, so it is the path automation uses
detach         end a binding, which is what stops its credential working
whoami         which agent this terminal is bound to
sessions       every live binding
watch          follow the traffic live in its own pane, read-only (M7a)
chat           set two agents talking: pick who, get the terminal-by-terminal
               commands, and the pane that shows what they say
next           what is waiting on whom, as the command that unblocks it
service        install, inspect or remove the per-user background service
               that keeps the daemon running (launchd / systemd --user)
claim          approve or deny a session asking to be an agent (M7c): an
               ordinary `claude` or `codex` session asks with
               agent_claim_begin, and a human decides here, from another
               terminal
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from . import nudge, procinfo, service as service_mod, watch
from .dispatcher import DispatchError, Dispatcher
from .server import BusServer, is_loopback_host
from .redact import Redactor
from .statedir import (
    clear_endpoint,
    db_path,
    ensure_state_dir,
    load_or_create_token,
    pid_alive,
    read_endpoint,
    read_token,
    resolve_state_dir,
    write_endpoint,
)

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def clean(value: Any) -> str:
    """Never print a peer-supplied string to a terminal unfiltered."""
    return CONTROL_CHARS.sub("?", str(value))
from .store import APPROVAL_POLICIES, APPROVAL_TTL_SECONDS, BINDING_TTL_SECONDS, LEASE_TTL_SECONDS, SENSITIVE_OPERATIONS, NotFound, Store, StoreError, utcnow

TOKEN_ENV = "LUCIAZERO_AGENT_BUS_TOKEN"
SERVER_NAME = "luciazero-bus"


def cmd_approve(args: argparse.Namespace) -> int:
    """The administrative approval channel (ADR 0003). Interactive only: a
    piped or scripted invocation is refused so an agent cannot drive it. The
    nonce is printed once; the store keeps only its hash."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("approve: refusing non-interactive input; run this yourself in a terminal", file=sys.stderr)
        return 2
    state_dir = resolve_state_dir(args.state_dir)
    path = db_path(state_dir)
    if not path.exists():
        print(f"approve: no bus database in {state_dir}", file=sys.stderr)
        return 2
    try:
        with Store.open(path) as store:
            store.migrate()
            store.trust = "human"  # the user's own terminal, not a peer's claim
            task = store.get_task(args.task_id)
            print(f"task {clean(task['id'])} [{clean(task['state'])}] held by {clean(task['assigned_agent_id'] or 'nobody')}: {clean(task['title'])}")
            try:
                answer = input(f"Approve one {args.operation} for this task (single use, valid {args.ttl}s)? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                print("not approved")
                return 1
            record, nonce = store.grant_approval(args.task_id, args.operation, granted_by=f"human:{getpass.getuser()}", ttl_seconds=args.ttl)
    except NotFound as exc:
        print(f"approve: {clean(exc)}", file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"approve: {clean(exc)}", file=sys.stderr)
        return 1
    print(f"approval {record['id']} granted for {args.operation} on {clean(record['task_id'])} until {clean(record['expires_at'])}")
    print("nonce (single use; hand it to the agent in its own session, never through the bus):")
    print(nonce)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if not is_loopback_host(args.host) and not args.allow_remote:
        print(f"refusing to bind {args.host!r}: pass --allow-remote to expose the bus beyond loopback (token still required)", file=sys.stderr)
        return 2
    state_dir = ensure_state_dir(resolve_state_dir(args.state_dir))
    existing = read_endpoint(state_dir)
    if existing is not None and isinstance(existing.get("pid"), int) and pid_alive(existing["pid"]) and existing["pid"] != os.getpid():
        print(f"a daemon already serves this state directory at {existing['url']} (pid {existing['pid']}); stop it first", file=sys.stderr)
        return 2
    token = load_or_create_token(state_dir)
    with Store.open(db_path(state_dir)) as store:
        store.migrate()
    server = BusServer(str(db_path(state_dir)), token, host=args.host, port=args.port, allow_remote=args.allow_remote,
                       allow_unattributed=bool(getattr(args, "allow_unattributed", False)),
                       approve_with=getattr(args, "approve_with", "auto"))
    write_endpoint(state_dir, server.url, os.getpid(), server.started_at)
    print(f"luciazero-agentd listening on {server.url} (state: {state_dir})", flush=True)

    def _stop(*_: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        clear_endpoint(state_dir, os.getpid())
    return 0


def _fetch_status(state_dir: Path) -> dict[str, Any]:
    endpoint = read_endpoint(state_dir)
    if endpoint is None:
        raise SystemExit(f"no running daemon recorded in {state_dir} (start one with: python3 -m luciazero_agentd serve)")
    token = read_token(state_dir)
    if token is None:
        raise SystemExit(f"token missing in {state_dir}; the daemon writes it on start")
    base = endpoint["url"][: -len("/mcp")] if endpoint["url"].endswith("/mcp") else endpoint["url"]
    request = urllib.request.Request(base + "/status", headers={"Authorization": f"Bearer {token}"})
    # No proxy: the token must only ever travel to the loopback daemon.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"daemon at {endpoint['url']} is not answering: {exc}") from exc


def cmd_status(args: argparse.Namespace) -> int:
    status = _fetch_status(resolve_state_dir(args.state_dir))
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    print(f"agent bus: {clean(status['server']['name'])} {clean(status['server']['version'])} since {clean(status['server']['started_at'])}")
    print(f"queued deliveries: {status['queued_deliveries']}   tasks: " + ", ".join(f"{clean(k)} {v}" for k, v in status["tasks"].items()))
    for agent in status["agents"]:
        worktree = agent.get("worktree")
        where = f"  on {clean(worktree['branch'])}{' (dirty)' if worktree.get('dirty') else ''}" if worktree else ""
        # ADR 0004: the label sits on the agent's own line, not in a legend.
        binding = agent.get("binding")
        who = f"  {clean(binding['tty'] or 'no tty')}" if binding else "  unverified"
        print(f"  {clean(agent['id']):<24} {clean(agent['provider']):<7} {clean(agent['role']):<14} inbox {agent['queued_deliveries']:>3}  claimed {agent['claimed_tasks']:>3}  seen {clean(agent['last_seen_at'])}{where}{who}")
    for task in status["open_tasks"]:
        who = clean(task["assigned_to"] or "unassigned")
        needs = "  needs worktree" if task.get("requires_worktree") else ""
        print(f"  open task {clean(task['id'])}  p{task['priority']}  {who}: {clean(task['title'])}{needs}")
    for task in status.get("stopped_tasks") or []:
        dimension = clean(task.get("dimension") or "budget")
        print(f"  stopped task {clean(task['id'])}  spent its {dimension} budget: {clean(task['title'])}")
    for worker in status.get("workers") or []:
        state = "enabled" if worker["enabled"] else "paused"
        print(f"  managed worker {clean(worker['agent_id']):<20} {clean(worker['provider']):<7} {state}")
    for run in status.get("running_runs") or []:
        print(f"  turn running    {clean(run['agent_id']):<20} attempt {run['attempt']}  since {clean(run['started_at'])}")
    unverified = status.get("unverified_agents") or []
    if unverified:
        print(f"unverified: {', '.join(clean(a) for a in unverified)} (no terminal binding; these sessions act as whoever they claim to be)")
    if status.get("approvals_pending", 0) > 0:
        print(f"approvals pending: {int(status['approvals_pending'])} (unused nonces; each is bound to one task and operation)")
    if status["queued_deliveries"] > 0 or status["tasks"].get("open", 0) > 0:
        print("next: start the agent's session and run /lucia-bus (Codex: $lucia-bus)")
    return 0


def cmd_client_config(args: argparse.Namespace) -> int:
    state_dir = resolve_state_dir(args.state_dir)
    endpoint = read_endpoint(state_dir)
    url = endpoint["url"] if endpoint else "http://127.0.0.1:<port>/mcp"
    token_path = shlex.quote(str(state_dir / "token"))
    quoted_url = shlex.quote(url)
    print("# Claude Code (user scope):")
    print(f'claude mcp add --scope user --transport http {SERVER_NAME} {quoted_url} --header "Authorization: Bearer $(cat {token_path})"')
    print("# Codex CLI (reads the token from an environment variable at start):")
    print(f"export {TOKEN_ENV}=\"$(cat {token_path})\"")
    print(f"codex mcp add {SERVER_NAME} --url {quoted_url} --bearer-token-env-var {TOKEN_ENV}")
    print("# Then start each agent session and run /lucia-bus (Codex: $lucia-bus).")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    """Human channel: cancel an open or claimed task. Writes the store
    directly; the claim holder sees a conflict on its next task_complete."""
    state_dir = resolve_state_dir(args.state_dir)
    path = db_path(state_dir)
    if not path.exists():
        print(f"cancel: no bus database in {state_dir}", file=sys.stderr)
        return 2
    try:
        with Store.open(path) as store:
            store.migrate()
            store.trust = "human"  # the user's own terminal, not a peer's claim
            task = store.cancel_task(args.task_id, f"human:{getpass.getuser()}", reason=args.reason)
    except NotFound as exc:
        print(f"cancel: {clean(exc)}", file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"cancel: {clean(exc)}", file=sys.stderr)
        return 1
    holder = clean(task["assigned_agent_id"] or "nobody")
    print(f"task {clean(task['id'])} cancelled (was held by {holder}): {clean(task['title'])}")
    return 0


def cmd_roster(args: argparse.Namespace) -> int:
    """Human channel: name the team once so an agent can address a peer the
    user has not started yet (a pull-beta turn only exists when the user
    opens that session). The peer's own agent_register later refreshes it."""
    state_dir = resolve_state_dir(args.state_dir)
    path = db_path(state_dir)
    if not path.exists():
        print(f"roster: no bus database in {state_dir}", file=sys.stderr)
        return 2
    try:
        with Store.open(path) as store:
            store.migrate()
            store.trust = "human"  # the user's own terminal, not a peer's claim
            record = store.register_agent(
                args.agent_id, provider=args.provider, role=args.role,
                capabilities=args.capability or None,  # none given: keep what the agent recorded
                by=f"human:{getpass.getuser()}",
            )
    except StoreError as exc:
        print(f"roster: {clean(exc)}", file=sys.stderr)
        return 1
    print(f"agent {clean(record['id'])} ({clean(record['provider'])}, {clean(record['role'])}) is on the roster")
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    """Human channel: enrol, list, pause, or remove a managed worker. Letting a
    machine start turns for an agent is a decision with a person behind it, so
    no bus tool can make it (ADR 0006)."""
    state_dir = resolve_state_dir(args.state_dir)
    store = _open_store("worker", state_dir)
    if store is None:
        return 2
    who = f"human:{getpass.getuser()}"
    try:
        with store:
            if args.worker_command == "list":
                workers = store.list_workers()
                if not workers:
                    print("no managed workers; the bus runs pull-beta only")
                for worker in workers:
                    state = "enabled" if worker["enabled"] else "paused"
                    print(f"  {clean(worker['agent_id']):<24} {clean(worker['provider']):<7} {state:<8} "
                          f"attempts {worker['max_attempts']}  timeout {worker['turn_timeout_seconds']}s  "
                          f"approve {clean(worker['approval_policy']):<9} {clean(' '.join(worker['command']))}")
                return 0
            if args.worker_command == "add":
                command = list(args.command)
                if command and command[0] == "--":
                    command = command[1:]  # argparse keeps the separator in a REMAINDER list
                if not command:
                    print("worker add: name the provider command after --", file=sys.stderr)
                    return 2
                worker = store.enrol_worker(
                    args.agent_id, provider=args.provider, command=command, cwd=args.cwd,
                    max_attempts=args.max_attempts, turn_timeout_seconds=args.timeout,
                    approval_policy=args.approve, by=who,
                )
                print(f"agent {clean(worker['agent_id'])} is a managed {clean(worker['provider'])} worker "
                      f"({worker['max_attempts']} attempts, {worker['turn_timeout_seconds']}s per turn, "
                      f"approvals: {clean(worker['approval_policy'])})")
                print("the dispatcher starts its turns: luciazero-agentd dispatch --watch")
                return 0
            if args.worker_command in ("pause", "resume"):
                worker = store.set_worker_enabled(args.agent_id, args.worker_command == "resume", by=who)
                print(f"agent {clean(worker['agent_id'])} is {'enabled' if worker['enabled'] else 'paused'}")
                return 0
            store.remove_worker(args.agent_id, by=who)
            print(f"agent {clean(args.agent_id)} is no longer a managed worker")
            return 0
    except NotFound as exc:
        print(f"worker: {clean(exc)}", file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"worker: {clean(exc)}", file=sys.stderr)
        return 1


def _pick(prompt: str, choices: list[dict[str, Any]], taken: Optional[str] = None) -> Optional[str]:
    """One numbered choice from a list, or a typed agent id."""
    for index, agent in enumerate(choices, start=1):
        if agent["id"] == taken:
            continue
        where = f"on {clean(agent['tty'])}" if agent.get("tty") else "no terminal bound"
        print(f"  {index:>2}. {clean(agent['id']):<24} {clean(agent['provider']):<7} {clean(agent['role']):<14} {where}")
    try:
        answer = input(f"{prompt} [number or id] ").strip()
    except EOFError:
        return None
    if not answer:
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(choices):
        return str(choices[int(answer) - 1]["id"])
    return answer if any(str(a["id"]) == answer for a in choices) else None


def cmd_claim(args: argparse.Namespace) -> int:
    """Decide who a session is (M7c, human channel).

    The second phase of the claim, and the reason the first one is safe. Both
    CLIs can run shell commands, so a session able to approve its own request
    would prove nothing at all -- the model would choose its own identity, and
    a prompt injection would choose it for them. So this refuses to run from
    inside a provider session, and refuses a pipe: it wants a person, at a
    different keyboard, reading what is being asked.
    """
    state_dir = resolve_state_dir(args.state_dir)
    store = _open_store("claim", state_dir)
    if store is None:
        return 2
    try:
        if args.claim_command == "list":
            requests = store.list_claims(state=None if args.all else "open")
            if not requests:
                print("no session is asking to be an agent")
                return 0
            for record in requests:
                print(f"  {clean(record['id'])}  {clean(record['state']):<10} {clean(record['agent_id']):<24} "
                      f"{clean(record['provider']):<7} session #{clean(record['session_fingerprint'])}  "
                      f"expires {clean(record['expires_at'])}")
            return 0

        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("claim: refusing non-interactive input; a person decides this, in a terminal", file=sys.stderr)
            return 2
        # Defense in depth, not the boundary: a forked, orphaned process
        # under a pty passes this and the isatty check above. What actually
        # stops the asking session is the code, which only the daemon's own
        # console ever saw.
        try:
            inside = procinfo.provider_above(os.getpid())
        except procinfo.ProcessError as exc:
            # This check is what keeps a session from approving its own
            # request. Unable to run it, the honest answer is no: an approval
            # granted without it would be worth nothing.
            print(f"claim: cannot read the process table: {clean(exc)}. Approving needs to "
                  "prove this shell is not the session that is asking; approve from a "
                  "terminal where the process table can be read.", file=sys.stderr)
            return 2
        if inside is not None:
            # The whole point of the second phase: the session that asked must
            # not be the one that answers.
            print(f"claim: this shell is running inside a {clean(inside['provider'])} session "
                  f"(pid {inside['pid']}{', ' + clean(inside['tty']) if inside['tty'] else ''}). "
                  "Approve from a terminal of your own, not from the session that is asking.", file=sys.stderr)
            return 2
        record = store.get_claim(args.request_id)
        if record["state"] != "open":
            print(f"claim: {clean(record['id'])} is {clean(record['state'])}, not open", file=sys.stderr)
            return 1
        print(f"Agent:    {clean(record['agent_id'])}")
        print(f"Provider: {clean(record['provider'])}  ({clean(record['client'] or 'client did not say')})")
        print(f"Session:  #{clean(record['session_fingerprint'])}  asked at {clean(record['created_at'])}")
        print(f"Expires:  {clean(record['expires_at'])}")
        print("This binds that session to that agent id. Everything it writes will be recorded as that agent.")
        decision = args.claim_command == "approve"
        code = args.code if decision else None
        if decision and not code:
            try:
                code = input("Approval code (printed in the daemon's own window): ").strip()
            except EOFError:
                code = ""
            if not code:
                print("no change")
                return 1
        else:
            try:
                answer = input(f"{'Approve' if decision else 'Deny'} this claim? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                print("no change")
                return 1
        record = store.decide_claim(args.request_id, approve=decision, by=f"human:{getpass.getuser()}",
                                    code=code, tty=_own_tty(), pid=os.getpid())
    except NotFound as exc:
        print(f"claim: {clean(exc)}", file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"claim: {clean(exc)}", file=sys.stderr)
        return 1
    finally:
        store.close()
    if record["state"] == "approved":
        print(f"{clean(record['agent_id'])} is now that session's identity (binding {clean(record['binding_id'])}).")
        print("Go back to it and ask again: it becomes verified on its next bus call, without reconnecting.")
    else:
        print(f"denied; that session stays unverified")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """What to do next, read-only (M7a).

    `status` answers "what is the state of the bus". Everybody then works out
    by hand which terminal that means opening. This answers the second
    question directly, and writes the command out.
    """
    state_dir = resolve_state_dir(args.state_dir)
    try:
        conn = watch.open_read_only(db_path(state_dir))
    except watch.WatchError as exc:
        print(f"next: {clean(exc)}", file=sys.stderr)
        return 2
    try:
        actions = watch.owed(conn)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(actions, indent=2, sort_keys=True))
        return 0
    endpoint = read_endpoint(state_dir)
    if endpoint is None or not (isinstance(endpoint.get("pid"), int) and pid_alive(endpoint["pid"])):
        # Nothing else can happen while the daemon is down, so it is the whole
        # answer rather than a warning above the real one.
        print(f"the daemon is not running on {state_dir}. Start it, and everything below resumes:")
        print(f"    {watch.launcher()} serve")
        return 0
    if not actions:
        print(f"nothing is waiting on anybody ({state_dir}).")
        print(f"    {watch.launcher()} chat        # set two agents talking")
        return 0
    for action in actions:
        who = clean(action["agent"]) or "somebody"
        print(f"  {who:<24} {clean(action['why'])}")
        if action["do"]:
            print(f"    {clean(action['do'])}")
    print(f"\n  watch it happen:  {watch.launcher()} watch")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    """Set up a conversation between two agents (M7a, human channel).

    Reads the roster read-only and writes nothing: choosing who talks is not
    an act on the bus, and this command must stay safe to run while a real
    conversation is in flight.
    """
    state_dir = resolve_state_dir(args.state_dir)
    try:
        conn = watch.open_read_only(db_path(state_dir))
    except watch.WatchError as exc:
        print(f"chat: {clean(exc)}", file=sys.stderr)
        return 2
    try:
        agents = watch.roster(conn)
    finally:
        conn.close()
    if len(agents) < 2:
        print("chat: this bus has fewer than two agents; add them with: luciazero-agentd roster add ID PROVIDER ROLE",
              file=sys.stderr)
        return 2
    known = {str(a["id"]) for a in agents}
    first, second = args.between if args.between else (None, None)
    if first is None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("chat: name the pair with --between A B when this is not run in a terminal", file=sys.stderr)
            return 2
        print(f"agents on this bus ({state_dir}):")
        first = _pick("who starts?", agents)
        second = _pick("who answers?", agents, taken=first) if first else None
    unknown = [a for a in (first, second) if a is None or a not in known]
    if unknown or first == second:
        print(f"chat: pick two different agents that exist (see: luciazero-agentd status)", file=sys.stderr)
        return 2
    where = state_dir if args.state_dir else None
    if args.auto:
        # Printed, never run: each of these turns starts a real provider
        # process against the user's own credentials.
        print(f"\nManaged dispatch for {clean(first)} and {clean(second)}. "
              f"Every turn below spends real quota; nothing here has been run.\n")
        for label, command in watch.auto_turn_plan(agents, str(first), str(second), state_dir=where):
            print(f"  {label}")
            print(f"    {command}\n")
        print("Each side needs its own worktree, and a sensitive operation still needs an approval nonce")
        print("from you. A dispatched agent cannot also hold a human terminal: the turn opens its own session.")
        return 0
    plan = watch.conversation_plan(agents, str(first), str(second), state_dir=where)
    print(f"\n{clean(first)} and {clean(second)}, in three terminals:\n")
    for label, command in plan:
        print(f"  {label}")
        print(f"    {command}\n")
    print(f"Then in {clean(first)}'s session: /lucia-bus (Codex: $lucia-bus), and send {clean(second)} a message.")
    print("Terminal 1 shows every message either of them sends, and when the other one opens it.")
    print("Neither session is woken by this: each agent reads its inbox when its own turn starts.")
    print(f"To have them answer each other without you: {watch.launcher()} chat "
          f"--between {clean(first)} {clean(second)} --auto")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Follow the bus in a pane of its own (M7a).

    The one command here that never writes: it opens the database read-only
    and acknowledges nothing, because `deliveries.acknowledged_at` has to keep
    meaning "an agent opened this in its own session". Seeing a message is not
    receiving it, and the decision log measures the difference.
    """
    if args.between and args.agent:
        # Two different questions -- "these two talking" and "anything this
        # agent touched" -- and silently letting one win prints a filtered
        # transcript that looks complete.
        print("watch: --between and --agent ask for different things; pick one", file=sys.stderr)
        return 2
    state_dir = resolve_state_dir(args.state_dir)
    colour = args.color == "always" or (args.color == "auto" and sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    try:
        watched = list(args.between) if args.between else list(args.agent or [])
        follower = watch.Follower(db_path(state_dir), agents=watched or None, pair=bool(args.between))
        conn = follower.connect()
        for agent in watched:
            if conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent,)).fetchone() is None:
                print(f"watch: no agent {clean(agent)!r} on this bus (see: luciazero-agentd status)", file=sys.stderr)
                return 2
        renderer = watch.Renderer(colour=colour, payload=args.payload)
        who = (f"{clean(watched[0])} and {clean(watched[1])} only" if args.between
               else ", ".join(clean(a) for a in watched) + " only" if watched else "every agent")
        print(f"watching {state_dir} read-only, {who}. Nothing here acknowledges anything; Ctrl-C to stop.", flush=True)
        for event in follower.tail(args.tail):
            print(renderer.line({"what": "message", **event}), flush=True)
        for event in follower.follow(interval=args.interval, passes=1 if args.once else None,
                                     on_error=lambda exc: print(f"watch: {clean(exc)}; reconnecting", file=sys.stderr)):
            print(renderer.line(event), flush=True)
    except watch.WatchError as exc:
        print(f"watch: {clean(exc)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("", flush=True)
    finally:
        follower.close()
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    """Start managed turns. Runs in its own process: it spawns models, and a
    crash here must not take the bus down with it."""
    state_dir = resolve_state_dir(args.state_dir)
    try:
        engine = Dispatcher(state_dir, lease_ttl_seconds=args.lease_ttl)
    except DispatchError as exc:
        print(f"dispatch: {clean(exc)}", file=sys.stderr)
        return 2
    recovered = engine.recover_all()
    for run in recovered:
        print(f"recovered run {clean(run['id'])} for {clean(run['agent_id'])}: {clean(run['delivery_state'])}", file=sys.stderr)
    if args.watch and args.once:
        print("dispatch: --once and --watch ask for different things; pick one", file=sys.stderr)
        return 2
    # A cap counted in turns, not in passes: turns are what spend quota, and
    # "keep going until I notice" is not a budget.
    passes = None if (args.watch or args.max_turns) else 1

    def _stop_dispatch(*_: object) -> None:
        # Without this a SIGTERM skips every cleanup below and leaves the turn
        # in flight holding a live credential -- the same defect M4.5 fixed for
        # `run`. The handler stops the provider; unwinding does the rest.
        engine.cancel_in_flight()
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, _stop_dispatch)
    try:
        started = 0
        for summary in _dispatch_passes(engine, passes=passes, interval=args.interval,
                                        stop_when_idle=args.stop_when_idle):
            line = f"{clean(summary['agent_id'])}  delivery {clean(summary['delivery_id'])}  {clean(summary['outcome'])}"
            if summary.get("delivery_state"):
                line += f" -> {clean(summary['delivery_state'])}"
            if summary.get("error"):
                line += f"  ({clean(summary['error'])})"
            print(line, flush=True)
            started += 1
            if args.max_turns and started >= args.max_turns:
                print(f"dispatch: stopping at the {args.max_turns}-turn cap", file=sys.stderr)
                break
    except KeyboardInterrupt:
        print("dispatch: stopped", file=sys.stderr)
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


def _dispatch_passes(engine: "Dispatcher", *, passes: Optional[int], interval: float,
                     stop_when_idle: bool = False) -> Iterator[dict[str, Any]]:
    done = 0
    while passes is None or done < passes:
        started = 0
        for summary in engine.tick():
            started += 1
            yield summary
        # A pass is synchronous: a turn that queued a reply has already
        # finished, so the next pass would find it. Nothing found means the
        # work really has run out, which is how a watch that is waiting for
        # more is told apart from one that is done.
        if stop_when_idle and started == 0:
            return
        done += 1
        if passes is not None and done >= passes:
            return
        time.sleep(interval)


#: How much of `daemon.log` a failed autostart quotes back. The log is
#: appended to by every daemon this directory has ever started, so a failure
#: shows its own last words rather than the file.
LOG_TAIL_LINES = 10
LOG_TAIL_BYTES = 2000


def _log_tail(state_dir: Path) -> str:
    """The end of `daemon.log`, bounded and scrubbed, for a failure to quote.

    Bounded twice, by bytes and then by lines, because the file holds every
    daemon this directory has started and a crash loop writes long ones.
    Scrubbed with the daemon's own token added to the default rules: reading
    the log is something this process may do and printing it is not the same
    act, and the token sits in the same directory.
    """
    try:
        with (state_dir / "daemon.log").open("rb") as handle:
            # Seek rather than read and slice: this file is appended to by
            # every daemon the directory has started, and a crash loop is
            # exactly the case where it is both huge and worth quoting.
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - LOG_TAIL_BYTES))
            raw = handle.read()
    except OSError:
        return ""
    token = read_token(state_dir)
    text, _ = Redactor([token] if token else []).text(raw.decode("utf-8", "replace"))
    return "\n".join(f"  {clean(line)}" for line in text.splitlines()[-LOG_TAIL_LINES:])


def _autostart_daemon(state_dir: Path, *, timeout: float = 20.0) -> Optional[dict[str, Any]]:
    """Start a daemon for a terminal that has none, and wait until it answers.

    Setup used to open with "start the daemon in a terminal you can leave
    open": a window to keep, and a step whose only purpose was to make the
    next command work. The daemon is started the way the service manager
    starts it -- an absolute interpreter from `serve_command`, output appended
    to `daemon.log`, its own session so it outlives this terminal -- and this
    process waits for `endpoint.json` rather than assuming it arrived.

    Two terminals starting at once is not a race worth locking: `serve`
    refuses a state directory a live daemon already owns, so the loser exits
    and both callers read the winner's endpoint.
    """
    ensure_state_dir(state_dir)
    argv, env = service_mod.serve_command()
    child = {**os.environ, **env, "LUCIAZERO_AGENT_BUS_HOME": str(state_dir)}
    # An ephemeral port, always. The stable 8765 belongs to the installed
    # service, which passes its own `--port`, and this path only runs when no
    # daemon is recorded here at all -- so it never competes with one. What it
    # does compete with is every other daemon on the machine: a second state
    # directory is a second daemon, two daemons cannot share a port, and the
    # loser dies with `Errno 48` in a log nobody reads. `cmd_serve` writes the
    # address it actually bound into `endpoint.json`, which is where every
    # client looks, so nothing downstream needs to know the number.
    serve = argv + ["serve", "--state-dir", str(state_dir), "--port", "0"]
    try:
        log = (state_dir / "daemon.log").open("a")
    except OSError as exc:
        print(f"run: cannot write the daemon log in {state_dir}: {clean(exc)}", file=sys.stderr)
        return None
    try:
        daemon = subprocess.Popen(serve, env=child,
                                  stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                  start_new_session=True)
    except OSError as exc:
        print(f"run: cannot start a daemon: {clean(exc)}", file=sys.stderr)
        return None
    finally:
        log.close()
    deadline = time.monotonic() + timeout
    while True:
        endpoint = _live_endpoint(state_dir)
        if endpoint is not None:
            return endpoint
        # Asked only after the endpoint, and asked again after it: a `serve`
        # exits because another one already owns this directory, and that
        # loser is not a failure -- the winner's endpoint is the answer both
        # callers wanted. `cmd_serve` refuses only once an endpoint is
        # recorded, so the one re-read closes the window between the two.
        code = daemon.poll()
        if code is not None:
            endpoint = _live_endpoint(state_dir)
            if endpoint is not None:
                return endpoint
            tail = _log_tail(state_dir)
            print(f"run: the daemon it started exited {code} without recording an endpoint; "
                  f"last of {state_dir / 'daemon.log'}:\n{tail or '  (nothing logged)'}",
                  file=sys.stderr)
            return None
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    print(f"run: started a daemon but it did not record an endpoint within {timeout:.0f}s; "
          f"see {state_dir / 'daemon.log'}", file=sys.stderr)
    return None


def _live_endpoint(state_dir: Path) -> Optional[dict[str, Any]]:
    """A recorded endpoint whose process is still there, or None."""
    endpoint = read_endpoint(state_dir)
    if endpoint is not None and isinstance(endpoint.get("pid"), int) and pid_alive(endpoint["pid"]):
        return endpoint
    return None


def _open_store(command: str, state_dir: Path) -> Optional[Store]:
    """Human-channel commands write the store directly, as `approve` does."""
    path = db_path(state_dir)
    if not path.exists():
        print(f"{command}: no bus database in {state_dir}", file=sys.stderr)
        return None
    store = Store.open(path)
    store.migrate()
    store.trust = "human"  # ADR 0004: the user's own terminal, not a peer's claim
    return store


def _own_tty() -> Optional[str]:
    try:
        return os.path.basename(os.ttyname(sys.stdin.fileno()))
    except OSError:
        return None


def _binding_lines(bindings: list[dict[str, Any]]) -> dict[Optional[str], dict[str, Any]]:
    return {b["tty"]: b for b in bindings}


def cmd_terminal(args: argparse.Namespace) -> int:
    """Show the provider sessions the user can pick from. Read-only, but
    looking is also what reaps bindings whose process is gone."""
    state_dir = resolve_state_dir(args.state_dir)
    store = _open_store("terminal", state_dir)
    if store is None:
        return 2
    with store:
        bindings = store.list_bindings()
    by_tty = _binding_lines(bindings)
    by_pid = {b["pid"]: b for b in bindings if b["pid"] is not None}
    try:
        sessions = procinfo.sessions()
    except procinfo.ProcessError as exc:
        print(f"terminal: cannot read the process table: {clean(exc)}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"sessions": sessions, "bindings": bindings}, indent=2, sort_keys=True, default=str))
        return 0
    if not sessions:
        print("no provider session owns a terminal right now")
        return 0
    mine = _own_tty()
    print(f"{'TTY':10}{'PID':8}{'PROVIDER':10}{'CWD':40}BOUND AGENT")
    for session in sessions:
        tty = session["tty"] or "-"
        bound = by_pid.get(session["pid"]) or (by_tty.get(session["tty"]) if session["tty"] else None)
        agent = clean(bound["agent_id"]) if bound else "-"
        here = "  <- this terminal" if mine and session["tty"] == mine else ""
        print(f"{tty:10}{session['pid']:<8}{session['provider'] or '-':10}{clean(session['cwd'] or '-')[:39]:40}{agent}{here}")
    unbound = [b for b in bindings if b["pid"] is not None and b["pid"] not in {s["pid"] for s in sessions}]
    for b in unbound:
        print(f"binding {clean(b['id'])} names agent {clean(b['agent_id'])} on a process that is no longer a session")
    return 0


def _pick_process(args: argparse.Namespace) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Resolve --tty/--pid to exactly one provider process, or explain why
    not. One terminal can carry several provider processes, so an ambiguous
    --tty is refused rather than guessed."""
    try:
        sessions = procinfo.sessions()
    except procinfo.ProcessError as exc:
        return None, f"cannot read the process table: {exc}"
    if args.pid is not None:
        chosen = [s for s in sessions if s["pid"] == args.pid]
        if not chosen:
            try:
                identity = procinfo.identity(args.pid)
            except procinfo.ProcessError as exc:
                return None, f"cannot read the process table: {exc}"
            if identity is None:
                return None, f"no process {args.pid} of this user"
            return identity, None
        return chosen[0], None
    tty = args.tty or _own_tty()
    if tty is None:
        return None, "no --tty or --pid given and this command is not running in a terminal"
    tty = os.path.basename(tty)
    candidates = [s for s in sessions if s["tty"] == tty]
    if not candidates:
        return None, f"no provider session owns {tty}"
    if len(candidates) > 1:
        rows = "; ".join(f"pid {c['pid']} ({c['provider']})" for c in candidates)
        return None, f"{tty} carries several provider processes ({rows}); name one with --pid"
    return candidates[0], None


def _mcp_commands(binding: dict[str, Any], credential: str, url: str) -> list[str]:
    """What the user pastes into that terminal's session. The credential goes
    in the same Authorization header the daemon token used to occupy."""
    if binding["provider"] == "claude":
        return [
            "claude mcp remove --scope user " + SERVER_NAME,
            f"claude mcp add --scope user --transport http {shlex.quote(SERVER_NAME)} {shlex.quote(url)} "
            f"--header {shlex.quote('Authorization: Bearer ' + credential)}",
        ]
    return [
        f"codex mcp remove {shlex.quote(SERVER_NAME)}",
        f"export {TOKEN_ENV}={shlex.quote(credential)}",
        f"codex mcp add {shlex.quote(SERVER_NAME)} --url {shlex.quote(url)} --bearer-token-env-var {TOKEN_ENV}",
    ]


def cmd_attach(args: argparse.Namespace) -> int:
    """Bind an already-running terminal. Interactive only: this prints a
    credential, and a piped invocation would mean an agent is driving it.
    The bound session must reconnect its MCP server before the daemon can
    attribute anything to it -- header credentials are read at connect time."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("attach: refusing non-interactive input; run this yourself in a terminal, or use `run` for automation", file=sys.stderr)
        return 2
    state_dir = resolve_state_dir(args.state_dir)
    endpoint = read_endpoint(state_dir)
    process, problem = _pick_process(args)
    if problem is not None:
        print(f"attach: {clean(problem)}", file=sys.stderr)
        return 2
    assert process is not None
    provider = args.provider or process.get("provider")
    if provider is None:
        print("attach: cannot tell which provider that process is; pass --provider", file=sys.stderr)
        return 2
    store = _open_store("attach", state_dir)
    if store is None:
        return 2
    try:
        with store:
            binding, credential = store.bind_terminal(
                args.agent, provider=provider, by=f"human:{getpass.getuser()}",
                tty=process.get("tty"), pid=process["pid"], process_started_at=process.get("started_at"),
                cwd=process.get("cwd"), ttl_seconds=args.ttl,
            )
    except NotFound as exc:
        print(f"attach: {clean(exc)} (add it first: luciazero-agentd roster add ...)", file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"attach: {clean(exc)}", file=sys.stderr)
        return 1
    print(f"agent {clean(binding['agent_id'])} is bound to {clean(binding['tty'] or '(no tty)')} "
          f"pid {binding['pid']} until {clean(binding['expires_at'])}")
    print(f"binding {clean(binding['id'])}, generation {binding['generation']}")
    print()
    print("run this IN THAT TERMINAL's session, then reconnect the MCP server (a running session keeps the")
    print("credential it connected with, so restart it or reconnect luciazero-bus):")
    url = endpoint["url"] if endpoint is not None else "http://127.0.0.1:8765/mcp"
    for line in _mcp_commands(binding, credential, url):
        print(f"  {line}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Start a provider with the binding already in place. The credential
    reaches the child through its own configuration and never through this
    terminal's output, which is why automation uses this and not `attach`."""
    state_dir = resolve_state_dir(args.state_dir)
    endpoint = read_endpoint(state_dir)
    if endpoint is None and args.autostart:
        endpoint = _autostart_daemon(state_dir)
        if endpoint is None:
            return 2
    if endpoint is None:
        print(f"run: no running daemon recorded in {state_dir} (start one with: python3 -m luciazero_agentd serve)", file=sys.stderr)
        return 2
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]  # argparse keeps the separator in a REMAINDER list
    if not command:
        print("run: name the provider command after --, for example: run --agent claude-reviewer -- claude", file=sys.stderr)
        return 2
    provider = args.provider or procinfo.PROVIDER_COMMANDS.get(os.path.basename(command[0]))
    if provider is None:
        print(f"run: cannot tell which provider {command[0]!r} is; pass --provider", file=sys.stderr)
        return 2
    # Asked before anything is created, because the answer decides whether
    # this command can work at all: a binding is anchored to the child's pid
    # and its start time, and the start time comes from the process table.
    # Finding out afterwards would mean a credential minted, a provider
    # started, and a session that cannot be proved alive.
    try:
        procinfo.started_at(os.getpid())
    except procinfo.ProcessError as exc:
        print(f"run: cannot read the process table: {clean(exc)}. A binding records the "
              "session's pid and start time, so there is nothing to bind to here; start the "
              "provider yourself and use `attach` from a terminal that can.", file=sys.stderr)
        return 2
    store = _open_store("run", state_dir)
    if store is None:
        return 2
    try:
        with store:
            try:
                binding, credential = store.bind_terminal(
                    args.agent, provider=provider, by=f"human:{getpass.getuser()}",
                    tty=_own_tty(), cwd=os.getcwd(), ttl_seconds=args.ttl,
                )
            except NotFound:
                # `roster add` before a first session exists so that peers can
                # address an agent that has not run yet. The id being started
                # here is that name, so asking for it twice is ceremony. It is
                # printed because a typo makes a second agent, and a stray one
                # is only obvious while the line is still on screen.
                role = args.agent.rsplit("-", 1)[-1] if "-" in args.agent else "agent"
                store.register_agent(args.agent, provider=provider, role=role)
                print(f"run: added {clean(args.agent)} to the roster ({provider}, {clean(role)})", file=sys.stderr)
                binding, credential = store.bind_terminal(
                    args.agent, provider=provider, by=f"human:{getpass.getuser()}",
                    tty=_own_tty(), cwd=os.getcwd(), ttl_seconds=args.ttl,
                )
    except NotFound as exc:
        print(f"run: {clean(exc)}", file=sys.stderr)
        return 2
    except StoreError as exc:
        print(f"run: {clean(exc)}", file=sys.stderr)
        return 1
    env = dict(os.environ)
    url = endpoint["url"]
    workspace = Path(tempfile.mkdtemp(prefix="luciazero-bind-"))
    os.chmod(workspace, 0o700)
    if provider == "claude":
        # The credential goes in a 0600 file, never on the child's command
        # line: argv is world-readable through `ps` for the life of a session
        # that may run for hours. The codex branch below uses the environment
        # for the same reason.
        config = workspace / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {SERVER_NAME: {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {credential}"}}}}))
        os.chmod(config, 0o600)
        argv = [command[0], "--mcp-config", str(config)] + (["--strict-mcp-config"] if args.strict else []) + command[1:]
    else:
        env[TOKEN_ENV] = credential
        argv = [command[0], "-c", f'mcp_servers.{SERVER_NAME}.url="{url}"',
                "-c", f'mcp_servers.{SERVER_NAME}.bearer_token_env_var="{TOKEN_ENV}"'] + command[1:]

    def _cleanup(reason: str) -> None:
        """A credential must never outlive this command, however it ends."""
        shutil.rmtree(workspace, ignore_errors=True)
        closer = _open_store("run", state_dir)
        if closer is None:
            return
        with closer:
            try:
                closer.revoke_binding(binding["id"], by=f"human:{getpass.getuser()}", reason=reason)
            except StoreError:
                pass

    print(f"agent {clean(binding['agent_id'])} bound as {clean(binding['id'])}; starting {clean(command[0])}", file=sys.stderr)
    # With a terminal to proxy, the provider gets a pty of its own and this
    # process keeps the keyboard: that is what lets a delivery arriving while
    # the session sits idle turn into a line typed at its prompt, instead of
    # waiting for the user to think of asking. Without a terminal -- a test, a
    # pipe, a dispatched turn -- there is nothing to type into and nothing to
    # proxy, so the child simply inherits this process's streams as before.
    if getattr(args, "nudge", True) and nudge.usable():
        return _run_on_a_pty(args, argv, env, binding, state_dir, _cleanup)
    try:
        child = subprocess.Popen(argv, env=env)
    except OSError as exc:
        # A credential was minted a moment ago: a provider that never started
        # must not leave it valid for the rest of its TTL.
        _cleanup("spawn failed")
        print(f"run: cannot start {clean(command[0])}: {clean(exc)}", file=sys.stderr)
        return 2
    store = _open_store("run", state_dir)
    if store is not None:
        with store:
            try:
                store.bind_process(binding["id"], pid=child.pid, process_started_at=procinfo.started_at(child.pid))
            except (StoreError, procinfo.ProcessError):
                # The child may already be gone (the reaper handles it), or
                # the process table may have become unreadable since the
                # check above. Neither is worth taking the user's terminal
                # down for: the binding still dies when this command exits.
                pass

    def _stop_run(*_: object) -> None:
        raise KeyboardInterrupt

    # Without this a SIGTERM to `run` skips the cleanup below and leaves an
    # orphaned provider holding a live credential until its TTL expires.
    previous = signal.signal(signal.SIGTERM, _stop_run)
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
        _cleanup("run exited")


def _run_on_a_pty(args: argparse.Namespace, argv: list[str], env: dict[str, str],
                  binding: dict[str, Any], state_dir: Path,
                  cleanup: Callable[[str], None]) -> int:
    """`run`, holding the provider's terminal so the bus can knock on it."""
    try:
        pid, master = nudge.spawn(argv, env)
    except OSError as exc:
        cleanup("spawn failed")
        print(f"run: cannot start {clean(argv[0])}: {clean(exc)}", file=sys.stderr)
        return 2
    store = _open_store("run", state_dir)
    if store is not None:
        with store:
            try:
                store.bind_process(binding["id"], pid=pid, process_started_at=procinfo.started_at(pid))
            except StoreError:
                pass
    watcher = nudge.Watcher(state_dir / "bus.sqlite3", binding["agent_id"], started_at=utcnow(),
                            limit=max(0, int(getattr(args, "max_nudges", nudge.MAX_NUDGES))))

    def _stop_run(*_: object) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, _stop_run)
    try:
        return nudge.proxy(pid, master, watcher=watcher,
                           show=nudge.log_sink(state_dir / nudge.LOG_NAME))
    except KeyboardInterrupt:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
                os.waitpid(pid, 0)
                break
            except ChildProcessError:
                break
            except OSError:
                continue
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
        cleanup("run exited")


def cmd_detach(args: argparse.Namespace) -> int:
    """End a binding. The credential stops working on the next request."""
    state_dir = resolve_state_dir(args.state_dir)
    store = _open_store("detach", state_dir)
    if store is None:
        return 2
    with store:
        bindings = store.list_bindings()
        if args.binding:
            chosen = [b for b in bindings if b["id"] == args.binding]
        elif args.agent:
            chosen = [b for b in bindings if b["agent_id"] == args.agent]
        else:
            tty = os.path.basename(args.tty) if args.tty else _own_tty()
            chosen = [b for b in bindings if b["tty"] == tty] if tty else []
        if not chosen:
            print("detach: no live binding matches; see `luciazero-agentd sessions`", file=sys.stderr)
            return 2
        for binding in chosen:
            store.revoke_binding(binding["id"], by=f"human:{getpass.getuser()}", reason=args.reason or "detached")
            print(f"binding {clean(binding['id'])} for {clean(binding['agent_id'])} ended")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    """Which agent is this terminal? The human-side answer to agent_whoami."""
    state_dir = resolve_state_dir(args.state_dir)
    store = _open_store("whoami", state_dir)
    if store is None:
        return 2
    with store:
        bindings = store.list_bindings()
    tty = _own_tty()
    mine = [b for b in bindings if tty is not None and b["tty"] == tty]
    if args.json:
        print(json.dumps({"tty": tty, "bindings": mine}, indent=2, sort_keys=True, default=str))
        return 0
    if not mine:
        print(f"this terminal ({tty or 'no tty'}) is not bound to any agent; unverified sessions act as whoever they claim to be")
        return 1
    for binding in mine:
        print(f"{clean(binding['agent_id'])} ({clean(binding['provider'])}) bound as {clean(binding['id'])}, "
              f"generation {binding['generation']}, until {clean(binding['expires_at'])}")
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    """Every live binding, reaping any whose process has gone."""
    state_dir = resolve_state_dir(args.state_dir)
    store = _open_store("sessions", state_dir)
    if store is None:
        return 2
    with store:
        bindings = store.list_bindings(states=("active",) if not args.all else ("active", "revoked", "stale"))
    if args.json:
        print(json.dumps(bindings, indent=2, sort_keys=True, default=str))
        return 0
    if not bindings:
        print("no live binding; every session is unverified")
        return 0
    for b in bindings:
        where = f"{clean(b['tty'] or '(no tty)')} pid {b['pid'] if b['pid'] is not None else '-'}"
        print(f"{clean(b['agent_id']):24}{clean(b['provider']):8}{where:24}{clean(b['state']):9}gen {b['generation']}  until {clean(b['expires_at'])}")
    return 0


def _service_plan(args: argparse.Namespace) -> "service_mod.Plan":
    return service_mod.plan(state_dir=args.state_dir,
                            root=Path(args.root).expanduser() if getattr(args, "root", None) else None,
                            host=getattr(args, "host", "127.0.0.1"),
                            port=getattr(args, "port", 8765),
                            approve_with=getattr(args, "approve_with", "auto"))


def cmd_service(args: argparse.Namespace) -> int:
    """The daemon without a dedicated window.

    Every path is printed before anything is written: a service is a file that
    keeps running commands after the person who installed it has forgotten
    about it, so what it will be is shown first and asked for by name in
    `service uninstall`.
    """
    try:
        plan = _service_plan(args)
    except service_mod.ServiceError as exc:
        print(f"service: {exc}", file=sys.stderr)
        return 2

    if args.service_command == "status":
        report = service_mod.status(plan)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 0 if report["installed"] else 1
        print(f"service {clean(report['label'])} ({report['kind']})")
        for path, state in report["files"]:
            print(f"  {'ok  ' if state == 'ours' else 'MISS'}  {clean(path)} ({state})")
        running = "running" if report["active"] else "not running (or the manager cannot say)"
        print(f"  --    {running}")
        print(f"  --    state {clean(report['state_dir'])}")
        print(f"  --    log   {clean(report['log'])}")
        for note in report["notes"]:
            print(f"  --    {note}")
        return 0 if report["installed"] else 1

    print(f"service {args.service_command} ({plan.kind}, {clean(plan.label)})")
    for path, _ in plan.files:
        print(f"  file    {clean(str(path))}")
    if args.service_command == "install":
        print(f"  runs    {' '.join(clean(part) for part in plan.command)}")
        print(f"  log     {clean(str(plan.log))}")
        for note in plan.notes:
            print(f"  note    {note}")
    for step in (plan.install_steps if args.service_command == "install" else plan.uninstall_steps):
        print(f"  then    {' '.join(step.argv)}")
    if args.dry_run:
        print("  --      dry run: nothing was written and nothing was started")
        return 0
    try:
        if args.service_command == "install":
            result = service_mod.install(plan)
        else:
            result = service_mod.uninstall(plan)
    except service_mod.ServiceError as exc:
        print(f"service: {exc}", file=sys.stderr)
        return 2
    for path, action in result["files"]:
        print(f"  ok      {action} {clean(path)}")
    for argv, code, message in result["steps"]:
        mark = "ok    " if code == 0 else "--    "
        detail = f" ({clean(message)})" if code != 0 and message else ""
        print(f"  {mark}  {' '.join(argv)}{detail}")
    if args.service_command == "install":
        print(f"\nThe bus now starts with your session. Check it with: "
              f"{watch.launcher()} service status")
    return 0


def split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    """Take everything after the first `--` as the provider command, before
    argparse sees it. argparse's REMAINDER swallows any of our own flags that
    follow a positional, so `worker add A other --cwd X -- cmd` silently made
    `--cwd` part of the command; splitting first makes the order irrelevant."""
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1:]
    return argv, []


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, provider_command = split_command(argv)
    parser = argparse.ArgumentParser(prog="luciazero-agentd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the daemon in the foreground")
    serve.add_argument("--state-dir", default=None)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allow-remote", action="store_true", help="permit a non-loopback --host (token still required)")
    serve.add_argument("--approve-with", choices=("auto", "dialog", "console"), default="auto",
                       dest="approve_with",
                       help="how a session's claim is put to you: dialog (a window this daemon raises; macOS), "
                            "console (a one-time code printed here), auto (dialog where possible)")
    serve.add_argument("--allow-unattributed", action="store_true", help="permit acting calls from sessions with no terminal credential (ADR 0004 legacy mode; approvals still need one, and unverified sessions are labelled either way)")
    serve.set_defaults(func=cmd_serve)
    status = sub.add_parser("status", help="show pending inbox items and tasks")
    status.add_argument("--state-dir", default=None)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)
    config = sub.add_parser("client-config", help="print mcp-add commands for both CLIs")
    config.add_argument("--state-dir", default=None)
    config.set_defaults(func=cmd_client_config)
    approve = sub.add_parser("approve", help="grant one single-use approval nonce (interactive terminal only)")
    approve.add_argument("task_id")
    approve.add_argument("operation", choices=SENSITIVE_OPERATIONS)
    approve.add_argument("--state-dir", default=None)
    approve.add_argument("--ttl", type=int, default=APPROVAL_TTL_SECONDS, help=f"seconds until the nonce expires (default {APPROVAL_TTL_SECONDS})")
    approve.set_defaults(func=cmd_approve)
    cancel = sub.add_parser("cancel", help="cancel an open or claimed task (human channel)")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", default=None)
    cancel.add_argument("--state-dir", default=None)
    cancel.set_defaults(func=cmd_cancel)
    terminal = sub.add_parser("terminal", help="provider sessions that own a terminal")
    terminal_sub = terminal.add_subparsers(dest="terminal_command", required=True)
    terminal_list = terminal_sub.add_parser("list", help="list provider sessions and what each is bound to")
    terminal_list.add_argument("--state-dir", default=None)
    terminal_list.add_argument("--json", action="store_true")
    terminal_list.set_defaults(func=cmd_terminal)
    attach = sub.add_parser("attach", help="bind one running terminal to an agent (interactive terminal only)")
    attach.add_argument("--agent", required=True)
    attach.add_argument("--tty", default=None, help="terminal to bind (default: this one)")
    attach.add_argument("--pid", type=int, default=None, help="name the process when one terminal carries several")
    attach.add_argument("--provider", choices=("codex", "claude", "other"), default=None)
    attach.add_argument("--ttl", type=int, default=BINDING_TTL_SECONDS, help=f"seconds until the credential expires (default {BINDING_TTL_SECONDS})")
    attach.add_argument("--state-dir", default=None)
    attach.set_defaults(func=cmd_attach)
    run = sub.add_parser("run", help="start a provider with the binding already in place")
    run.add_argument("--agent", required=True)
    run.add_argument("--provider", choices=("codex", "claude", "other"), default=None)
    run.add_argument("--ttl", type=int, default=BINDING_TTL_SECONDS)
    run.add_argument("--strict", action="store_true", help="claude only: pass --strict-mcp-config, which hides the session's other MCP servers")
    run.add_argument("--no-autostart", dest="autostart", action="store_false", default=True,
                     help="fail instead of starting a daemon when this state directory has none")
    run.add_argument("--no-nudge", dest="nudge", action="store_false", default=True,
                     help="do not type into this session when a delivery arrives; it will notice on its next turn instead")
    run.add_argument("--max-nudges", type=int, default=nudge.MAX_NUDGES,
                     help="how many times in a row the bus may type into this session with nobody at the keyboard; "
                          "any keystroke starts the count again (default: %(default)s)")
    run.add_argument("--state-dir", default=None)
    # REMAINDER swallows everything after the command, options included, so
    # every flag of `run` must come before the `--`.
    run.add_argument("command", nargs=argparse.REMAINDER, help="-- then the provider command, for example: run --agent x -- claude")
    run.set_defaults(func=cmd_run, takes_provider_command=True)
    detach = sub.add_parser("detach", help="end a binding (this terminal's by default)")
    detach.add_argument("--agent", default=None)
    detach.add_argument("--binding", default=None)
    detach.add_argument("--tty", default=None)
    detach.add_argument("--reason", default=None)
    detach.add_argument("--state-dir", default=None)
    detach.set_defaults(func=cmd_detach)
    whoami = sub.add_parser("whoami", help="which agent this terminal is bound to")
    whoami.add_argument("--state-dir", default=None)
    whoami.add_argument("--json", action="store_true")
    whoami.set_defaults(func=cmd_whoami)
    sessions = sub.add_parser("sessions", help="every live binding")
    sessions.add_argument("--all", action="store_true", help="include revoked and stale bindings")
    sessions.add_argument("--state-dir", default=None)
    sessions.add_argument("--json", action="store_true")
    sessions.set_defaults(func=cmd_sessions)
    roster = sub.add_parser("roster", help="name an agent so peers can address it before its first session")
    roster_sub = roster.add_subparsers(dest="roster_command", required=True)
    add = roster_sub.add_parser("add", help="add or refresh one agent on the roster")
    add.add_argument("agent_id")
    add.add_argument("provider", choices=("codex", "claude", "other"))
    add.add_argument("role")
    add.add_argument("--capability", action="append", default=[])
    add.add_argument("--state-dir", default=None)
    add.set_defaults(func=cmd_roster)
    worker = sub.add_parser("worker", help="managed workers the dispatcher may start (human channel)")
    worker_sub = worker.add_subparsers(dest="worker_command", required=True)
    worker_add = worker_sub.add_parser("add", help="enrol an agent as a managed worker: luciazero-agentd worker add AGENT PROVIDER [flags] -- COMMAND")
    worker_add.add_argument("agent_id")
    worker_add.add_argument("provider", choices=("codex", "claude", "other"))
    worker_add.add_argument("--cwd", default=None, help="absolute path the turn runs in")
    worker_add.add_argument("--max-attempts", type=int, default=3, dest="max_attempts")
    worker_add.add_argument("--timeout", type=int, default=600, help="seconds one turn may take")
    worker_add.add_argument("--approve", choices=APPROVAL_POLICIES, default="deny",
                            help="how far a turn may go when the provider asks: deny (default, report instead of act), "
                                 "workspace (run commands and edit in its own worktree), accept (whatever it asks)")
    worker_add.add_argument("--state-dir", default=None)
    worker_add.add_argument("command", nargs="*", default=[], help="-- then the provider command")
    worker_add.set_defaults(func=cmd_worker, takes_provider_command=True)
    for name, help_text in (("list", "show managed workers"), ("pause", "stop starting turns for one worker"),
                            ("resume", "start turns for one worker again"), ("remove", "drop a managed worker")):
        entry = worker_sub.add_parser(name, help=help_text)
        if name != "list":
            entry.add_argument("agent_id")
        entry.add_argument("--state-dir", default=None)
        entry.set_defaults(func=cmd_worker)
    dispatch = sub.add_parser("dispatch", help="start managed turns for queued work")
    dispatch.add_argument("--once", action="store_true", help="one pass and exit (the default; the docs name it)")
    dispatch.add_argument("--watch", action="store_true", help="keep polling instead of one pass")
    dispatch.add_argument("--interval", type=float, default=2.0)
    dispatch.add_argument("--stop-when-idle", action="store_true", dest="stop_when_idle",
                          help="exit when a pass finds nothing to start, instead of waiting for more")
    dispatch.add_argument("--max-turns", type=int, default=0, dest="max_turns",
                          help="stop after this many turns have run (0: no cap). Each turn spends provider quota.")
    dispatch.add_argument("--lease-ttl", type=int, default=LEASE_TTL_SECONDS, dest="lease_ttl")
    dispatch.add_argument("--state-dir", default=None)
    dispatch.set_defaults(func=cmd_dispatch)
    watcher = sub.add_parser("watch", help="follow the traffic live, read-only (M7a)")
    watcher.add_argument("--agent", action="append", default=None,
                         help="only messages this agent sent or received; repeatable (default: all)")
    watcher.add_argument("--between", nargs=2, metavar=("A", "B"), default=None,
                         help="only what these two said to each other")
    watcher.add_argument("--tail", type=int, default=10, help="messages of history to show first (default 10)")
    watcher.add_argument("--interval", type=float, default=1.0, help="seconds between polls")
    watcher.add_argument("--payload", choices=("preview", "full", "none"), default="preview",
                         help="how much of each message body to show (default: one redacted line)")
    watcher.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    watcher.add_argument("--once", action="store_true", help="one pass and exit instead of following")
    watcher.add_argument("--state-dir", default=None)
    watcher.set_defaults(func=cmd_watch)
    claim = sub.add_parser("claim", help="approve or deny a session asking to be an agent (interactive terminal only)")
    claim_sub = claim.add_subparsers(dest="claim_command", required=True)
    claim_list = claim_sub.add_parser("list", help="requests waiting for a decision")
    claim_list.add_argument("--all", action="store_true", help="include decided and expired requests")
    claim_list.add_argument("--state-dir", default=None)
    claim_list.set_defaults(func=cmd_claim)
    for name, help_text in (("approve", "bind that session to the agent it asked for"),
                            ("deny", "refuse the request; the session stays unverified")):
        entry = claim_sub.add_parser(name, help=help_text)
        entry.add_argument("request_id")
        if name == "approve":
            entry.add_argument("--code", default=None,
                               help="the one-time code the daemon printed in its own window; asked for if omitted")
        entry.add_argument("--state-dir", default=None)
        entry.set_defaults(func=cmd_claim)
    service = sub.add_parser("service", help="run the daemon as a per-user background service")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    service_install = service_sub.add_parser("install", help="write the service file and start the daemon")
    service_install.add_argument("--host", default="127.0.0.1")
    service_install.add_argument("--port", type=int, default=8765)
    service_install.add_argument("--approve-with", choices=("auto", "dialog", "console"),
                                 default="auto", dest="approve_with")
    service_uninstall = service_sub.add_parser("uninstall", help="stop the service and remove only the files this wrote")
    for entry in (service_install, service_uninstall):
        entry.add_argument("--dry-run", action="store_true", dest="dry_run",
                           help="print what would happen and change nothing")
    service_status = service_sub.add_parser("status", help="whether the service is installed and running")
    service_status.add_argument("--json", action="store_true")
    for entry in (service_install, service_uninstall, service_status):
        entry.add_argument("--state-dir", default=None)
        entry.add_argument("--root", default=None,
                           help="where the service file goes (default: your home directory)")
        entry.set_defaults(func=cmd_service)
    nxt = sub.add_parser("next", help="what is waiting on whom, as the command that unblocks it")
    nxt.add_argument("--state-dir", default=None)
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=cmd_next)
    chat = sub.add_parser("chat", help="set two agents talking, and show where to type what")
    chat.add_argument("--between", nargs=2, metavar=("A", "B"), default=None,
                      help="skip the questions and name the pair")
    chat.add_argument("--auto", action="store_true",
                      help="print the managed-dispatch setup instead: turns started by the dispatcher, which spends quota")
    chat.add_argument("--state-dir", default=None)
    chat.set_defaults(func=cmd_chat)
    args = parser.parse_args(argv)
    # argparse's own subcommand dest is also "command", so the tail is handed
    # only to the parsers that declared they take one.
    if provider_command and getattr(args, "takes_provider_command", False):
        args.command = provider_command
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

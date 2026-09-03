"""``python3 -m luciazero_agentd`` entry point.

serve          run the daemon in the foreground (writes endpoint.json + token)
status         print what is waiting on whom, via the running daemon
client-config  print the exact mcp-add commands for Claude Code and Codex CLI
approve        grant one single-use approval nonce for a sensitive operation
               (interactive terminal only; writes the store directly, never
               through the agent-facing MCP endpoint)
cancel         cancel an open or claimed task (human channel, direct store)
roster add     name an agent so peers can address it before its first session
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shlex
import signal
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .server import BusServer, is_loopback_host
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
from .store import APPROVAL_TTL_SECONDS, SENSITIVE_OPERATIONS, NotFound, Store, StoreError

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
    server = BusServer(str(db_path(state_dir)), token, host=args.host, port=args.port, allow_remote=args.allow_remote)
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
        print(f"  {clean(agent['id']):<24} {clean(agent['provider']):<7} {clean(agent['role']):<14} inbox {agent['queued_deliveries']:>3}  claimed {agent['claimed_tasks']:>3}  seen {clean(agent['last_seen_at'])}{where}")
    for task in status["open_tasks"]:
        who = clean(task["assigned_to"] or "unassigned")
        needs = "  needs worktree" if task.get("requires_worktree") else ""
        print(f"  open task {clean(task['id'])}  p{task['priority']}  {who}: {clean(task['title'])}{needs}")
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="luciazero-agentd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the daemon in the foreground")
    serve.add_argument("--state-dir", default=None)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allow-remote", action="store_true", help="permit a non-loopback --host (token still required)")
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
    roster = sub.add_parser("roster", help="name an agent so peers can address it before its first session")
    roster_sub = roster.add_subparsers(dest="roster_command", required=True)
    add = roster_sub.add_parser("add", help="add or refresh one agent on the roster")
    add.add_argument("agent_id")
    add.add_argument("provider", choices=("codex", "claude", "other"))
    add.add_argument("role")
    add.add_argument("--capability", action="append", default=[])
    add.add_argument("--state-dir", default=None)
    add.set_defaults(func=cmd_roster)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

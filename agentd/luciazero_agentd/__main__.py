"""``python3 -m luciazero_agentd`` entry point.

serve          run the daemon in the foreground (writes endpoint.json + token)
status         print what is waiting on whom, via the running daemon
client-config  print the exact mcp-add commands for Claude Code and Codex CLI
"""

from __future__ import annotations

import argparse
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
from .store import Store

TOKEN_ENV = "LUCIAZERO_AGENT_BUS_TOKEN"
SERVER_NAME = "luciazero-bus"


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
        print(f"  {clean(agent['id']):<24} {clean(agent['provider']):<7} {clean(agent['role']):<14} inbox {agent['queued_deliveries']:>3}  claimed {agent['claimed_tasks']:>3}  seen {clean(agent['last_seen_at'])}")
    for task in status["open_tasks"]:
        who = clean(task["assigned_to"] or "unassigned")
        print(f"  open task {clean(task['id'])}  p{task['priority']}  {who}: {clean(task['title'])}")
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
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

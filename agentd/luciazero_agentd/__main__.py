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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from . import procinfo
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
from .store import APPROVAL_TTL_SECONDS, BINDING_TTL_SECONDS, SENSITIVE_OPERATIONS, NotFound, Store, StoreError

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
                       allow_unattributed=bool(getattr(args, "allow_unattributed", False)))
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
            identity = procinfo.identity(args.pid)
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
    store = _open_store("run", state_dir)
    if store is None:
        return 2
    try:
        with store:
            binding, credential = store.bind_terminal(
                args.agent, provider=provider, by=f"human:{getpass.getuser()}",
                tty=_own_tty(), cwd=os.getcwd(), ttl_seconds=args.ttl,
            )
    except NotFound as exc:
        print(f"run: {clean(exc)} (add it first: luciazero-agentd roster add ...)", file=sys.stderr)
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
            except StoreError:
                pass  # the child may already be gone; the reaper handles it

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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="luciazero-agentd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the daemon in the foreground")
    serve.add_argument("--state-dir", default=None)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allow-remote", action="store_true", help="permit a non-loopback --host (token still required)")
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
    run.add_argument("--state-dir", default=None)
    # REMAINDER swallows everything after the command, options included, so
    # every flag of `run` must come before the `--`.
    run.add_argument("command", nargs=argparse.REMAINDER, help="-- then the provider command, for example: run --agent x -- claude")
    run.set_defaults(func=cmd_run)
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
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

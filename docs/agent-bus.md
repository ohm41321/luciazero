# Luciazero Agent Bus (pull beta)

A local queue that lets Codex CLI and Claude Code CLI sessions hand work to
each other without you copying messages between terminals. One daemon owns
a SQLite database under `~/.luciazero/agent-bus`; each agent talks to it
through MCP tools; you start each agent turn yourself. Design and evidence:
[the roadmap](agent-bus-roadmap.md) and the ADRs under [`adr/`](adr/).

The bus is beta and separate from the core install: `npx luciazero` never
starts a daemon. Everything below runs from a checkout of this repository,
and every `python3 -m luciazero_agentd ...` command runs from its `agentd/`
directory (or with `PYTHONPATH=agentd` from the repository root). The
daemon needs Python 3.10+ and `git`; nothing is installed with pip.

## Setup

1. Start the daemon in a terminal you can leave open:

   ```bash
   cd agentd && python3 -m luciazero_agentd serve
   ```

   It prints `luciazero-agentd listening on http://127.0.0.1:8765/mcp` and
   writes `endpoint.json` plus a capability token (mode `0600`) into the
   state directory. Override the directory with `LUCIAZERO_AGENT_BUS_HOME`
   or `--state-dir`; tests and the demo always use a temporary one.

2. Name the team once. A pull-beta turn exists only when you open that
   agent's session, so the first agent must be able to address peers that
   have not registered yet:

   ```bash
   python3 -m luciazero_agentd roster add codex-architect   codex  architect
   python3 -m luciazero_agentd roster add claude-reviewer   claude reviewer --capability review
   python3 -m luciazero_agentd roster add codex-implementer codex  implementer
   ```

3. Register the bus with each CLI. `python3 -m luciazero_agentd
   client-config` prints the exact commands: `claude mcp add --scope user
   --transport http luciazero-bus <url> --header "Authorization: Bearer ..."`
   and `codex mcp add luciazero-bus --url <url> --bearer-token-env-var
   LUCIAZERO_AGENT_BUS_TOKEN`. Neither command edits the other tool's
   configuration.

4. In each agent session run `/lucia-bus` (Codex: `$lucia-bus`). The skill
   asks the daemon who it is, registers the agent, binds its git worktree,
   reads the inbox, claims, works, and publishes. Every writing agent needs
   its own worktree (`git worktree add ../wt-reviewer -b review`); the daemon
   refuses two agents on one checkout. Bind the terminal first (below) so the
   model does not have to be told its id, or tell it the id and accept that
   the bus cannot prove it.

## Choosing which terminal is which agent

The shared daemon token admits a caller to the bus but names nobody, so a
session that presents it acts as whoever it says it is. Binding a terminal
gives that one session its own credential, and the daemon then fills the
acting agent into every call itself. ADR 0004 has the contract.

```bash
python3 -m luciazero_agentd terminal list          # which window is which
python3 -m luciazero_agentd attach --agent claude-reviewer --tty ttys004
python3 -m luciazero_agentd run --agent claude-reviewer -- claude
python3 -m luciazero_agentd whoami                 # what is this terminal?
python3 -m luciazero_agentd sessions               # every live binding
python3 -m luciazero_agentd detach --agent claude-reviewer
```

`terminal list` shows one row per provider session: tty, pid, start time,
working directory, and the agent bound to it. One terminal can carry several
provider processes, so `attach --tty` refuses an ambiguous terminal and asks
for `--pid`.

- **`attach`** binds a session that is already running. It prints the
  credential, so it refuses to run from a pipe, and it prints the `mcp add`
  command to paste into that session. **That session must reconnect the
  `luciazero-bus` server (or restart) before anything can be attributed to
  it**: an MCP client reads its headers when it connects.
- **`run`** starts the provider with the binding already in place and never
  prints the credential, which makes it the path for scripts and the one M6
  will reuse to spawn managed workers. The binding ends when the command
  exits.
- A binding dies with its terminal: the daemon checks the recorded pid and
  its start time on every request, so a killed session cannot be impersonated
  by a later process that reuses the pid.

An agent with no binding is **unverified**, and `bus status` says so on that
agent's line. **The daemon refuses acting calls from unverified sessions by
default**: read-only tools and `agent_whoami` still answer, and spending a
human approval always needs a binding. `serve --allow-unattributed` turns the
old behaviour back on for everything except approvals, and is a deliberate
human choice, not something an agent can ask for. The flag decides only what
is permitted, never how a session is labelled: an unverified session is
reported as unverified either way, and `agent_whoami` answers
`verified: false` rather than guessing from the worktree or the process
table.

Sessions that were already connected with the shared token keep the header
they connected with, so after binding a terminal that session must reconnect
`luciazero-bus` or restart.

## Status inspection

Before starting a turn, look at what is waiting on whom:

```bash
npx luciazero bus status            # from the core package (Node 18+)
python3 -m luciazero_agentd status  # same view, Python only; --json for records
```

Both show queued deliveries per agent, a count per task state, open tasks
(with `needs worktree` when a task requires one), tasks the daemon stopped on
a spent budget, each agent's bound branch and dirty state, which terminal each
agent is bound to (or `unverified`), and pending approvals. The line `next: start the agent's session and run
/lucia-bus` appears whenever something is queued. Peer-supplied text is
scrubbed of control characters before it reaches your terminal.

## Approvals

Delete, deploy, production access, spending, force-push, public-contract
changes, and scope expansion need your approval. No bus tool can create one.
When an agent reports that it needs one, run, in your own terminal:

```bash
python3 -m luciazero_agentd approve <task_id> delete
```

It shows the task and its claim holder, asks once, and prints a single-use
nonce valid for 15 minutes. Hand that nonce to the agent in its own session;
the agent spends it with `approval_consume`. A nonce pasted into a bus
message, task, artifact name or file is scrubbed or refused, so it cannot be
forwarded between agents. The command refuses piped input; ADR 0003 states
the exact boundary.

## Cancellation

```bash
python3 -m luciazero_agentd cancel <task_id> --reason "scope changed"
```

Open and claimed tasks become `cancelled`. Queued `task` messages for
that task are dead-lettered so `bus status` stops asking for a turn;
already-acknowledged ones stay with their reader to complete. The claim
holder's next `task_complete` returns a conflict, so it learns on its next
turn, and `/done` accepts a user-cancelled task; the record keeps who
cancelled and why. Completed and blocked tasks cannot be cancelled.

## Task graphs, budgets and stoppers

A task can name prerequisites. `task_create` takes `depends_on` for tasks
that already exist; `task_graph_create` creates a whole plan in one
transaction, where each node has a `key` other nodes depend on. A batch that
contains a cycle is refused whole, so a half-built graph is never committed.

A task with an unfinished prerequisite is `waiting`: it cannot be claimed,
and `task_get` names what it waits on. Completing the last prerequisite opens
it in that same transaction. A prerequisite that ends any other way --
blocked, cancelled, or stopped on a budget -- blocks everything below it
instead, because a task waiting on work nobody will finish would wait
forever.

`budget` sets per-task limits the daemon enforces:

| dimension  | measured by | spent when |
| ---------- | ----------- | ---------- |
| `seconds`  | the daemon  | the wall clock passes the task's deadline |
| `turns`    | the daemon  | a message naming the task is sent |
| `tokens`   | the provider, through `task_record_usage` | the claim holder reports usage |
| `cost_usd` | the provider, through `task_record_usage` | the claim holder reports usage |

The two the daemon measures cannot be under-reported. The two only a provider
can know are additive and holder-only: a report raises a total, never lowers
one, only the agent holding the claim may make it, and every report keeps how
much the reporting session's identity was worth. A spent
budget is a stop, not a warning: the task becomes `exhausted`, its queued
messages are dead-lettered, whatever waited on it is blocked, and the send or
claim that hit the limit is refused. `bus status` names stopped tasks on their
own line. There is no reopening; the user creates a new task.

Two limits bound a conversation regardless of budgets: `MAX_HOPS` (32
messages in one `correlation_id`) and a 24-hour conversation time to live.
The daemon counts hops itself -- a sender that could set its own hop count
could reset a loop forever -- and records the refusal as a
`conversation.hop_limit` or `conversation.expired` event. A reply inherits the
conversation of the message it answers, so threading with `reply_to` alone
cannot open a fresh window; `reply_to` with a `correlation_id` from another
conversation is refused.

Delivery-level retry limits (`attempts`, `max_attempts`) stay reserved for
the dispatcher in M6: nothing retries by itself in the pull beta, so a retry
limit here would be a number nothing could reach.

## Managed dispatch (beta, M6)

By default nothing starts a turn but you. Enrolling a managed worker is what
lets the machine start one, so it is a human command and no bus tool can do it:

```bash
python3 -m luciazero_agentd worker add claude-reviewer other \
    --cwd /path/to/worktree --max-attempts 3 --timeout 600 -- my-worker-command
python3 -m luciazero_agentd worker list
python3 -m luciazero_agentd dispatch --watch     # its own process, not the daemon
```

`worker pause` stops starting turns for one worker without forgetting it;
`worker resume` starts again; `worker remove` drops it back to the pull beta.

Each turn is a bound session like any other: the dispatcher mints a `managed`
binding, hands the credential to the child through the environment or a `0600`
file, and revokes it when the turn ends. So a managed worker cannot act as a
peer, cannot spend an approval it was not handed, and never sees the shared
daemon token. An agent whose terminal a person has bound is skipped entirely --
`bind_terminal` refuses a managed binding on a human-owned agent, so this holds
even if a dispatcher tries.

The dispatcher never acknowledges a delivery or completes a task for a worker:
those are the worker's own claims, made with the worker's own credential. When
a turn ends it looks at what the worker actually did. A turn that exits cleanly
without touching the bus is a failed attempt, not a completed one.

| The turn | What happens |
| --- | --- |
| the worker moved its delivery on | the run is `completed` |
| the delivery is untouched, attempts left | `retryable_failed`, and the next pass tries again |
| attempts exhausted | `dead_letter` |
| the provider binary is missing, or no adapter ships for it | `dead_letter` at once: retrying a configuration error is a loop with a bill |
| the task is finished, cancelled, or stopped on a budget | `dead_letter` without starting anything |

One lease per session means two dispatchers cannot resume the same provider
session; taking a lease bumps the session's generation and fences whoever held
it. A lease dies when it expires *or* when the process holding it is gone, so a
killed dispatcher is recovered in seconds rather than at the end of a TTL. On
start, the dispatcher settles what a killed one left: the run is `abandoned`,
the orphaned provider's credential is revoked, the orphan is stopped, and the
delivery goes back for one more attempt.

Provider output goes to `runs/<run_id>.log` in the state directory, `0600`,
capped, and scrubbed through the redaction contract with the daemon token and
the run's own credential as literals before anything is written.

`bus status` names every managed worker and every turn in flight.

Three adapters ship, one per provider:

| provider | how a turn runs |
| --- | --- |
| `claude` | `claude -p [--resume ID] --mcp-config F --strict-mcp-config --allowedTools mcp__luciazero-bus --permission-mode M --output-format json PROMPT`. The credential is in `F` at `0600`, never on the command line, and `F` is deleted when the turn ends however it ends. The session id printed in the JSON result is what the next turn resumes. |
| `codex` | Codex App Server on a private stdio child: `initialize`, `thread/start` (or `thread/resume`), `turn/start`, collect until the turn completes. The bus arrives through `-c mcp_servers...` overrides, which apply to that process only and never touch the `config.toml` in `CODEX_HOME`. |
| `codex` with `exec` in its command | `codex exec [resume ID] -c OVERRIDE... PROMPT`, the tested fallback. It cannot answer an approval request, so a turn that needs one ends there. |
| `other` | any command, with the bus in its environment. This is what the offline gate runs. |

`--approve` says how far a turn may go when the provider asks, and it is
chosen by the person who enrols the worker, because nobody is watching while a
managed turn runs:

| policy | Codex thread sandbox | Codex approval requests | Claude permission mode |
| --- | --- | --- | --- |
| `deny` (default) | `read-only` | refused; the turn reports instead of acting | `default` — only the bus is pre-allowed |
| `workspace` | `workspace-write` | accepted only when the request stays inside the turn's own directory and asks for no escalation | `acceptEdits` |
| `accept` | `workspace-write` | accepted as asked, escalation included | `bypassPermissions` |

The policy is recorded on the run, so re-enrolling a worker later does not
change what a finished turn ran under, and every answer the dispatcher gave is
on that turn's log next to the policy that gave it.

A worker command may not carry the flags the dispatcher sets for it
(`--permission-mode`, `--allowedTools`, `--mcp-config`, `-c`,
`--dangerously-skip-permissions`, and the rest), and may not end in an option
still waiting for a value: `claude --model` would swallow the `--mcp-config`
that follows it. Both are refused when the worker is enrolled, and again
before a turn starts.

This is not the bus approval nonce and never becomes one: a sensitive
operation on a task still needs a nonce the user mints in their own terminal.

Codex runs `approvalPolicy: "on-request"` because ADR 0001 recorded that
`"never"` fails a model-selected MCP tool call before it reaches the bus.

## Recovery

- **Daemon restart.** Stop it with Ctrl-C or `kill <pid>` and start it
  again on the same state directory. Acknowledged messages, claimed tasks,
  worktree records and artifacts survive; the demo restarts the daemon
  between the reviewer's finding and the implementer's fix to prove it.
- **A second daemon.** `serve` refuses to start while `endpoint.json` names
  a live process, and a daemon only ever removes its own record.
- **Stale worktree.** If an agent's checkout changed branch, moved, or was
  deleted, its next claim or publish is refused with `WorktreeMismatch` and
  a `worktree.mismatch` event. Restore the branch, or finish the task as
  `blocked` (always allowed) and rebind. Rebinding elsewhere while holding
  claimed worktree tasks is refused until they are completed or blocked.
- **Lost claim holder.** Cancel the task and create a new one; there is no
  reassignment in the pull beta (leases and retries arrive with managed
  dispatch, M6).
- **Expired approval.** Ask for a new nonce; used and expired ones are
  refused and recorded.
- **Continuing in a new session.** A fresh provider session that registers
  with the same agent id sees the same inbox and can claim the same open
  tasks; nothing is tied to a provider session id in the pull beta.

## Cleanup

```bash
python3 -m luciazero_agentd detach --agent claude-reviewer   # per bound terminal
BUS="${LUCIAZERO_AGENT_BUS_HOME:-$HOME/.luciazero/agent-bus}"
kill "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["pid"])' "$BUS/endpoint.json")"
rm -rf "$BUS"                            # queue, token, worktree records
claude mcp remove --scope user luciazero-bus
codex mcp remove luciazero-bus
git worktree remove ../wt-reviewer       # per writing agent
```

Provider session files created by live runs stay in the providers' own
stores; the bus never touches them.

## Demo and gates

```bash
bash docs/assets/agent-bus-demo.sh        # fake provider, no quota, ~10 s
./test.sh --agent-bus-e2e                 # the same flow as a gate (also in --full)
./test.sh --agent-bus-workflow            # M5: task graph, stoppers, provenance
./test.sh --agent-bus-dispatch            # M6: dispatcher killed mid-turn, recovered
./test.sh --agent-bus-live --spend-quota  # M6: one real Codex turn + one real Claude turn
LZ_AGENT_BUS_LIVE=1 bash docs/assets/agent-bus-demo.sh --live   # real models, 6 turns
bash docs/assets/agent-bus-demo.sh --live --dry-run             # print the plan only
```

The live smoke gate is the only one that spends money, so it refuses to run
without `--spend-quota` and never runs inside `--full`. It starts one managed
turn per provider on a disposable state directory and checks what the worker
itself moved: the delivery completed, the task completed by the worker under
its own bound session, and no credential, lease, or turn directory left behind.
The provider homes are not redirected -- a real turn needs the user's real
credentials -- so each CLI writes its own session transcript where it always
does.

The demo runs the roadmap's outcome flow: the architect opens a review
task, the reviewer reports a finding as a report artifact, the architect
turns it into fix and verify tasks, the daemon restarts, the implementer
publishes a fix commit from its own worktree, the reviewer (new session,
same id) verifies that commit on an export in its own worktree, and the
architect receives the result. It prints the record counts and the final
correlation id, and removes its temporary directory. Live runs spend
provider quota and need explicit approval; they are never part of CI. A
live run may add messages the flow does not owe (a model thanking a peer);
the gate matches the six-turn flow as a subsequence, tolerates that
chatter, and prints it, but still refuses a repeated step or a chatter
delivery that failed.

The M5 gate drives a second scenario through the same daemon: a cycle is
refused before anything is written, a fix/verify/report graph executes in
order, a reply loop stops at the hop cap, a spent turn budget stops a task
and blocks its dependent, and the commit the implementer published still
names the implementer after the reviewer cites it as evidence.

## Decision evidence log

The pull beta graduates to managed dispatch (M5+) only with recorded
evidence, per the roadmap's M4 decision point: at least three real
workflows (not the demo) with their correlation ids and record sets kept,
at least two retros naming the user-started turn as the blocking cost with
the wait or turn count measured, and no open M3 safety finding. Record each
workflow here or in the project's notes file as
`date, correlation id, agents, turns started by hand, wait cost`.

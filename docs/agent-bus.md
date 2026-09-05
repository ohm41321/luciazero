# Luciazero Agent Bus (pull beta)

A local queue that lets Codex CLI and Claude Code CLI sessions hand work to
each other without you copying messages between terminals. One daemon owns
a SQLite database under `~/.luciazero/agent-bus`; each agent talks to it
through MCP tools; you start each agent turn yourself. Design and evidence:
[the roadmap](agent-bus-roadmap.md) and the ADRs under [`adr/`](adr/).

The bus is beta and separate from the core install: `npx luciazero` never
starts a daemon. Everything below runs from a checkout of this repository.
The daemon needs Python 3.10+ and `git`; nothing is installed with pip.

`./install.sh` puts a `luciazero-agentd` launcher in `~/.claude/bin`
(`LUCIAZERO_BIN_DIR=~/.local/bin ./install.sh` to choose somewhere already on
your PATH), so **every `python3 -m luciazero_agentd X` below can be typed as
`luciazero-agentd X`**. Without it, run the module form from the `agentd/`
directory (or with `PYTHONPATH=agentd` from the repository root). The launcher
finds the package from where it was installed, so it works from any directory,
and it leaves your working directory alone — which matters, because `attach`
records it. Commands the bus prints for you switch between the two forms
depending on which one will actually run.

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

## Keeping the daemon running (M7e)

The daemon is only useful while it runs, and a terminal dedicated to it is the
first window closed by accident. Install it as a per-user service instead:

```bash
luciazero-agentd service install --dry-run   # exactly what it would write and run
luciazero-agentd service install
luciazero-agentd service status
luciazero-agentd service uninstall
```

macOS gets a LaunchAgent in `~/Library/LaunchAgents`; Linux and WSL2 get a
systemd `--user` unit in `~/.config/systemd/user`. Both run as you, not as
root, and Windows is refused by name (ADR 0002 scopes v1 to macOS, Linux and
WSL2). The unit always serves with strict binding — a service is never
installed with `--allow-unattributed` — and its output goes to
`daemon.log` in the state directory.

Every file carries an ownership marker. A service file that is not ours is
reported and left exactly as it is, never backed up and replaced, and
`service uninstall` deletes only files carrying that marker. `uninstall.sh`
stops the service before it removes the launcher — otherwise the manager
would keep restarting a file that is gone — and leaves the launcher in place,
loudly, if it could not.

The unit names its Python interpreter absolutely (a service manager's PATH is
not yours: a LaunchAgent gets `/usr/bin:/bin:/usr/sbin:/sbin`, where `python3`
is the system 3.9) and carries your PATH forward so the dispatcher can still
find `codex` and `claude`.

One consequence to know before you install it: a service has no console, so
the approval code has nowhere private to go (see below). On macOS the dialog
still works, because a LaunchAgent runs in your GUI session. On Linux the
install captures your current `DISPLAY` into the unit; if there is none, a
session asking to be an agent is refused rather than approved through a log
file, and told to use `run` or a daemon in a window.

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

## Watching a conversation (M7a)

The pull beta pushes nothing. A message waits in its delivery until a human
opens that agent's session, so two agents can hold a whole exchange while both
terminals show nothing at all. `watch` is the third pane that shows it:

```bash
python3 -m luciazero_agentd chat                    # pick the pair, get the commands
python3 -m luciazero_agentd watch --between codex-architect claude-implementer
```

```
17:42:22  codex-architect -> claude-implementer  [task]    M7a: read-only inbox watcher
17:53:22  claude-implementer opened it after 11m
```

The second line is the number the decision log measures: nothing acknowledges
a delivery until an agent opens it in its own turn, so the gap between the
message and the acknowledgement is what a user-started turn costs.

`chat` lists the agents with the terminal each one currently holds, asks which
two are talking, and prints the command for each terminal — the watcher first,
then a `run` line per side. `--between A B` skips the questions. Both commands
read the database **read-only**: they acknowledge nothing, write nothing, and
never migrate, because `deliveries.acknowledged_at` has to keep meaning "an
agent opened this in its own session". A watcher that marked messages read
would destroy the evidence it exists to show.

Options: `--agent X` (repeatable) is wider than `--between` — anything that
agent touched; `--payload full` prints whole bodies and `--payload none`
prints only who spoke to whom; `--tail N` sets how much history comes first;
`--once` prints and exits. Every payload is redacted again on the way to the
screen and stripped of control characters: the pane shows text other agents
wrote.

**It cannot wake a session.** A terminal sitting at its prompt stays there;
the agent reads its inbox when its next turn starts. Turns that start
themselves are managed dispatch, and they spend quota:

```bash
python3 -m luciazero_agentd chat --between A B --auto   # prints the setup, runs nothing
python3 -m luciazero_agentd dispatch --max-turns 4      # a cap counted in turns
python3 -m luciazero_agentd dispatch --watch --stop-when-idle
```

### Two agents answering each other

`scripts/agent-bus-chat.sh` is the whole loop in one command: both sides
enrolled as managed workers in disposable directories, one opening message
from the operator, and the exchange printed as it happens.

```bash
./scripts/agent-bus-chat.sh --rehearse            # the same loop, offline worker, no quota
./test.sh --agent-bus-chat                        # the same, as a gate
./scripts/agent-bus-chat.sh --spend-quota --turns 4
```

Each answer buys the next turn, so the loop has no natural end and is capped
three ways: it refuses to start without `--spend-quota`, `--turns` becomes the
dispatcher's own `--max-turns`, and the dispatcher stops as soon as a pass
finds nothing left to start. The bus state directory and both working
directories are temporary; `~/.codex` and `~/.claude` are not, because a real
turn needs the user's real credentials. `--keep` leaves the state directory
for `agent-bus-evidence.sh`.

## Ordinary sessions: the two-phase claim (M7c)

A session started as a plain `claude` or `codex` can still become a verified
agent. It asks, and you answer from another terminal:

```
you                     the session                     another terminal
                        /lucia-bus
                        agent_whoami -> verified false
                        agent_claim_begin("claude-reviewer")
                        "run this somewhere else:"
                                                        luciazero-agentd claim approve clm_...
                                                        Agent: claude-reviewer  ... [y/N] y
                        agent_whoami -> verified true
```

```bash
python3 -m luciazero_agentd claim list            # who is asking
python3 -m luciazero_agentd claim approve clm_…   # bind that session
python3 -m luciazero_agentd claim deny clm_…      # refuse; it stays unverified
```

The session becomes verified **in place**, with no reconnect, and its writes
are recorded as `bound` — worth what `run`'s are worth. `next` lists a waiting
request before anything else, because until it is answered that session can do
nothing.

Why the second terminal: both CLIs can run shell commands, so a session that
could approve its own request would prove nothing — the model would be
choosing its own identity. `claim approve` refuses a pipe and refuses to run
from inside a provider session. The model may only ask for an agent id that is
already on the roster, so it proposes an identity a person created rather than
inventing one. ADR 0004's amendment has the full reasoning, including the
single-phase design that was rejected for being a bearer token in disguise.

The request id is not a secret. Approving binds the session that asked, never
whoever holds the id, because the pin is made before the id exists.

### Clicking Allow instead of copying a code (M7d)

Where the daemon can put a window on screen it does, and there is nothing to
copy: it names the agent, the client and the request, and you press Allow or
Deny. `osascript` on macOS, `zenity` then `kdialog` on Linux and BSD (a
display is required), a PowerShell `MessageBox` on Windows. The daemon raises
it, so the session that asked cannot read it or press its buttons; a dialog
that times out or is killed decides nothing.

```bash
luciazero-agentd serve --approve-with auto      # dialog where possible (default)
luciazero-agentd serve --approve-with console   # always the printed code
LUCIAZERO_AGENT_BUS_NO_DIALOG=1                 # kill switch: never raise a window
```

**What the dialog assumes.** Clicking Allow proves a person answered only
while the local desktop is intact. A process that can drive another process's
user interface can answer it — macOS Accessibility permission granted to the
terminal the model runs in, any X11 client on the same display, UI Automation
on Windows — and the same permission can read the window that shows the
console code, so neither route survives it. That is the same boundary as the
rest of the bus: a hostile process running as you is out of scope (ADR 0004).
If you need to hold that line, revoke the permission and use `run`, where the
identity comes from a terminal you opened.

If there is no screen **and** no terminal — the daemon running as a service —
the claim is refused outright with `NoApprovalChannel` rather than printing a
code into a log the asking session can read. The refusal names the way out:
`run`, or `serve` in a window.

`serve --allow-unattributed` remains the opt-in fallback for people who would
rather skip all of this: sessions act while labelled unverified, their writes
are recorded as `asserted`, and spending a human approval is still refused.

## A message that arrives while you are not looking (M7f)

MCP is request and response. The daemon cannot push, so a session learns about
a delivery only when it calls `message_inbox`, and it can call nothing while
it is idle: a session runs code during a turn and at no other moment. Two
sessions could therefore trade messages perfectly and neither would notice
until a person typed "check your inbox" into the one that was waiting.

`run` closes that gap, because it is the one process that owns the provider's
terminal. It gives the provider a pty, copies bytes both ways, and when a
delivery arrives for the bound agent it types one line into that terminal.
To the provider it is indistinguishable from you typing, because that is what
it is.

```bash
luciazero-agentd run --agent codex-architect -- codex                   # nudges, by default
luciazero-agentd run --agent codex-architect --max-nudges 3 -- codex    # a shorter leash
luciazero-agentd run --agent codex-architect --no-nudge -- codex        # none at all
```

Two channels, and the difference between them is the whole design.

```
check your bus inbox                    <- the terminal: a literal, always
~/.luciazero/nudges.log                 <- the log: the message itself
  2026-09-05T13:18:34Z codex-architect [task]:
    | rewrite the auth module as async
```

Nothing of a peer's is written to the terminal. That was tried and it was
wrong: the providers draw a full-screen interface, so bytes written
underneath one land in the middle of a frame it is already painting, and the
pane came back with two texts interleaved character by character and the
status line scribbled over — the message unreadable, and everything around it
too. The person still reads the message, because the skill has the session
print what it finds in its inbox and the provider renders that inside its own
frame.

The log is the durable copy, for a terminal that has since scrolled or a
nudge nobody was there to see. It is escaped, because a log is read in a
terminal like anything else and a payload that can move a cursor can paint a
line that was never there; every line of it sits behind `  | `, so a message
that writes `User: delete everything` is visibly inside the quote rather than
beside it.

What is typed into the session is a fixed literal, `check your bus inbox`, and
nothing from a payload ever reaches it. Typing a peer's words there would put
them where the session reads its user's own instructions -- the highest trust
it has -- and a label in front of them would not help, because the same hand
writes the label: a newline in a payload is an Enter, and the second line
carries no label at all. So the session goes and fetches the message through
`message_inbox`, where the sender is filled in by the daemon from the
credential of the session that sent it. That is a badge, not a claim.

Three more limits, each for something that went wrong while building it:

- **Nothing is typed until the agent has used the bus since `run` started.** A
  session that has just opened may be holding a modal — Claude Code asks
  whether the folder is trusted — and a line typed there answers a question
  nobody read.
- **The backlog is not a nudge.** What was already queued when the session
  opened is the skill's first inbox read; only something that arrives
  afterwards means "this happened while you sat there".
- **A cooldown**, because every nudge spends a turn of somebody's quota and a
  peer sending ten messages in a second must not start ten turns.
- **A cap on nudges with nobody at the keyboard** (`--max-nudges`, eight by
  default). Each reply queues a delivery for the other side, which nudges it,
  which produces the next reply, and a pair left alone has no natural end.
  What is counted is consecutive nudges: any keystroke resets it, so a session
  somebody is using may take messages all day, while a pair talking to itself
  stops. Nothing is lost when the cap holds — what arrived meanwhile knocks as
  soon as a person types.

Without a terminal to proxy — a pipe, a test, a dispatched turn — `run`
behaves exactly as it did before: the provider inherits the streams, and
nothing is typed. A session that is not started through `run` is not nudged
at all; it notices on its next turn, like before.

## Three ways a turn starts

Every turn in this document begins one of three ways. They differ in who
supplies the first bytes the provider reads, what the daemon writes down at
that moment, and therefore what `scripts/agent-bus-evidence.sh` can say about
the wait afterwards.

**A person types in the pane.** The first bytes are their keystrokes, and the
daemon records nothing: no event marks when a prompt was typed, because a
keyboard is not on the bus. The ledger row reads `user-started`, and the
stretch between a message being sent and that session's next bus call stays
one span nobody accounted for — `silent_seconds`, reported as
`longest_silent_seconds`, which is a ceiling rather than a measurement. The
first row of [the decision log](agent-bus-decision-log.md) carries
`<=107s unattributed` for exactly this reason: nothing recorded when the
prompt was typed, the person was asked afterwards and could not confirm it,
and it therefore stays unattributed permanently. It is not re-derivable after
the fact, and a retro that claims the records settled it would be false.

**The bus knocks (M7f).** The first bytes are a fixed literal: `run` types
only `check your bus inbox` into the provider, so no byte of a payload is
ever provider input, and the message itself is appended to `nudges.log`,
escaped and quoted behind `  | `. At the moment it types, the store writes a
`turn.nudged` event, and the exporter uses it to split the silent stretch at
that moment: `knock_seconds`, the bus deciding to knock, which is a machine
start to finish, and `next_bus_call_seconds`, the time from the knock to that
agent's next call to the daemon. Only the first is what its name says. The
second is named for what it measures and not for what it is assumed to be,
because it also holds a provider that was busy, a keystroke that was
swallowed, and a person deciding whether to authorise the work — and nothing
recorded tells those apart from a session starting. The wait is marked
`attributed` and counted under `nudged_turns`, which the summary reports as
`bus-started`: attributed to a knock, and no further. What that buys is
attribution, not autonomy. The knock starts a turn, not the work: the session
reads the message and may decline to act on it, because an untrusted payload
authorises nothing. A person then authorises the work by typing — which is the
first mode again, inside the second.

### What the proxy writes down about the terminal

The gap after a knock has more than one thing in it, and two of them are
visible from where `run` sits. It holds the pty, so it is the only part of
this system that can see a keystroke arrive or the provider print. Both are
recorded, and neither is interpreted:

| Record | What it is |
| --- | --- |
| `provider_quiet_for` on `turn.nudged` | seconds since the provider last printed, at the instant the bus typed |
| `human_typed_ago` on `turn.nudged` | seconds since the last keystroke, at that same instant |
| `held_for` on `turn.nudged` | how long that knock waited for the pane to go quiet |
| `turn.nudge_deferred` | a knock held back for a pane that was still printing, once per delivery |
| `turn.human_input` | a person typed into this session, at most one event per 20 seconds |

The exporter carries the first two onto the wait as they are, and counts the
third between the knock and the agent's next bus call as
`human_input_after_knock`, with `nudged_turns_with_human_input` in the
summary. That is the difference between reporting machine latency and
reporting a number with somebody's lunch break inside it.

They are observations, not verdicts. A knock typed into a pane that printed a
tenth of a second earlier went into a session that was mid-turn, and a
keystroke sent to a busy TUI is not a turn — but "busy" is a reading of the
numbers, made by whoever reads them, and the store does not record the
conclusion. Where a nudge was decided outside a proxy the fields are absent
rather than zero, because never observed and observed as zero are different
answers.

**What is never recorded is the bytes.** This proxy carries every password and
every prompt its user types. What goes down is that something was typed and
when, and a keystroke event's payload has nothing in it but its trust label.

### Nothing is typed into a pane that is still printing

Workflow 2 lost a nudge because the pane was mid-turn when the bus typed into
it. A TUI that is working streams — tokens, a spinner, an elapsed counter —
and it is not reading its input while it does, so the keystroke went nowhere.
`turn.nudged` still said a turn had started, because a nudge is recorded when
it is typed, and the 671 seconds until somebody noticed were counted as a
session starting up.

So the provider must have printed nothing for `QUIET_SECONDS` (three, two
polls' worth) before anything is typed. A knock into a busy pane is held, not
dropped: `seen_seq` is untouched, exactly as when the cap holds, so it goes in
the moment the pane goes quiet and `held_for` says how long it waited. Waiting
spends neither the cap nor the cooldown — a refusal is not a nudge, and a busy
provider must not exhaust the leash without one keystroke ever being typed.

A provider that never stops printing would hold every knock forever, and that
would look from the records exactly like a bus with nothing to deliver. It
does not: the first time a delivery is held, `turn.nudge_deferred` says so,
once per delivery rather than once per poll.

This does not make the knock reliable. It stops the bus spending a keystroke
on a terminal that is demonstrably not reading; a pane that is quiet and still
swallows one is not covered, and nothing here confirms a turn actually
started — `turn.nudged` remains the moment of typing, not of a turn.

**The daemon starts the provider itself.** Under managed dispatch (M6, above)
the first bytes come from the dispatcher: it mints a `managed` binding, starts
the worker command with that credential, and revokes it when the turn ends.
The ledger's turn column then reads `N dispatched` rather than `user-started`,
because what triggered the turn is a record and not a keystroke. That is one
delivery, one worker, one turn. Chaining such turns into a flow that runs to
the end with nobody in the loop is designed and not built: see
[ADR 0007](adr/0007-agent-bus-managed-vertical-slice.md), which proposes the
task-delivery trigger that a completed task would need in order to start the
next one, bus records as the worker's memory across turns, idempotent steps
for a dispatcher killed mid-flow, and an offline gate tier
`./test.sh --agent-bus-managed` to prove them. None of that is implemented;
only the single dispatched turn above exists today.

## What to do next

```bash
python3 -m luciazero_agentd next
```

`status` reports the state of the bus; this reports the next action, with the
command written out and the most blocking first — a dead-lettered delivery or
a task stopped on its budget (a person has to decide something), then each
agent holding unread messages, with the command that opens that agent's
session from its own worktree. A daemon that is not running is the whole
answer rather than a warning above it. Read-only, like `watch` and `chat`.

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

## Evidence

`scripts/agent-bus-evidence.sh` exports one workflow's whole record set from a
state directory -- the messages of a conversation, the deliveries they created,
the tasks they name, the artifacts published against those tasks, the worktrees
their agents wrote from, the runs that carried them and the events that mention
any of it -- as JSON, plus a ready ledger row for
`docs/agent-bus-decision-log.md`:

```bash
./scripts/agent-bus-evidence.sh --state-dir ~/.luciazero --list
./scripts/agent-bus-evidence.sh --state-dir ~/.luciazero --correlation <id> --out evidence.json
```

It opens the database read-only and never migrates it, and runs the redaction
contract over what it writes. The summary includes what the pull beta costs:
how long each delivery waited between being sent and somebody opening the turn
that read it, the number of turns waited on, and the longest wait.

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
./test.sh --agent-bus-live --rehearse     # M6: the same gate against the offline worker
./test.sh --agent-bus-live --spend-quota  # M6: one real Codex turn + one real Claude turn
LZ_AGENT_BUS_LIVE=1 bash docs/assets/agent-bus-demo.sh --live   # real models, 6 turns
bash docs/assets/agent-bus-demo.sh --live --dry-run             # print the plan only
```

The live smoke gate is the only one that spends money, so it refuses to run
without `--spend-quota` and never runs inside `--full`. `--rehearse` runs the
identical gate against the offline worker, which is a real bus client and
spends nothing: it is what proves the gate's own assertions are satisfiable
before a provider is started. It starts one managed
turn per provider on a disposable state directory and checks what the worker
itself moved: the delivery completed, the task completed by the worker under
its own bound session, and no credential, lease, or turn directory left behind.
The provider homes are not redirected -- a real turn needs the user's real
credentials -- so each CLI writes its own session transcript where it always
does. Green for both providers on 2026-09-04.

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

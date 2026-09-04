# ADR 0004: Agent Bus terminal binding and session credentials

Status: accepted 2026-09-03 for milestone M4.5; amended 2026-09-04 for M7c
(the two-phase claim), M7d (the dialog) and M7e (a daemon with no console).
See the amendments at the end.

## Context

In the pull beta the user tells each model its agent id in prose ("you are
`claude-reviewer`") and the model passes that id to every tool. That is the
last place where identity is asserted by the model rather than established by
the user, and it does not scale past two terminals: with four sessions open
the user cannot see which window is which, two sessions can register the same
id, and a confused session can act as a peer by sending a different id.

The obvious fix -- record the terminal (tty, pid, cwd) when the user picks a
session -- does not work on its own. The daemon serves MCP over HTTP on the
loopback interface and authenticates with one shared capability token, so a
request carries no evidence of which terminal produced it. Recording a
terminal without changing authentication yields a row in the database that
nothing enforces: the daemon still has to believe the `agent_id` in the tool
call. The credential, not the process table, is what makes a binding real.

M3 already established the shape of the answer for approvals: a value the
daemon mints, stores only as a sha256, hands to exactly one holder, and
refuses everywhere else. Terminal identity needs the same treatment, with a
lifetime of a session instead of one operation.

## Decision

### Four identities, kept separate

| Identity | What it names | Lifetime |
| --- | --- | --- |
| `agent_id` | the role on the roster, `claude-reviewer` | permanent |
| `binding_id` | one binding of a terminal to that role | one session |
| `provider_session_id` | Claude session id / Codex thread id | provider's own |
| process identity | tty, pid, process start time, cwd | one process |

They are not interchangeable. A resumed Claude session keeps its
`provider_session_id` and gets a new `binding_id`. A terminal rebound to a
different role keeps its process identity and gets a new `binding_id`.

### The user picks a terminal, by hand, in the human channel

`luciazero-agentd terminal list` enumerates provider processes that own a
terminal, one row per session:

```
TTY       PID     STARTED           PROVIDER  CWD              BOUND AGENT
ttys004   1234    Sep 3 15:34       claude    ~/repo/wt-review -
ttys005   1278    Sep 3 09:02       codex     ~/repo           codex-architect
```

Two ways to bind, both human-channel commands, never MCP tools:

```bash
luciazero-agentd attach --tty ttys004 --agent claude-reviewer
luciazero-agentd run --agent claude-reviewer --provider claude -- claude
```

`attach` binds a session that is already running. `run` spawns the provider
with the binding already in place and is the safer path, because the
credential never has to be delivered to a live process. It also never puts
the credential on the child's command line: a provider session can run for
hours and argv is readable through `ps`, so the value goes in a `0600` file
that is removed when the command exits, or in the child's environment where
the CLI supports that. `run` is also the
piece M6 needs to spawn managed workers, so it is built once here.

Both commands: verify the target process exists, owns the given tty, belongs
to this user, and matches the recorded start time; create a `binding_id`;
mint a session credential; bind it to one `agent_id`; and record tty, pid,
start time, cwd and provider in the existing `sessions` table with
`ownership = 'human'`.

One terminal can hold several provider processes -- `codex` runs alongside
its code-mode host and, under the desktop app, bundled helpers, all on one
tty -- so `--tty` alone is ambiguous by default. `terminal list` shows only
the top-level provider process per tty (parent is a shell, not another
provider process). `attach --tty` refuses with the candidate rows printed
when more than one survives that filter; `--pid` then names the row and is
checked against its start time. Nothing is bound on a guess.

### Session credentials are what the daemon actually checks

Two levels of authority, on the same header:

- the **daemon token** admits a caller to the bus and names nobody. It stays
  the credential for `bus status`, `client-config`, and the human CLI.
- a **session credential** (`lzsc_<32hex>`, stored only as a sha256, like an
  approval nonce) admits the caller *and* says which agent it is.

Wire format is deliberately boring: the credential travels in
`Authorization: Bearer <value>` **in place of** the daemon token, never as a
second header. Claude Code can send arbitrary headers (`--header`), but the
`codex mcp add` surface for a streamable HTTP server offers exactly one
authentication knob, `--bearer-token-env-var`, so a scheme that needs a
custom header alongside the token is not portable across the two CLIs the
bus exists to join. The daemon looks the presented value up once: daemon
token, live session credential, or neither.

| Presented value | May call | Effective agent |
| --- | --- | --- |
| daemon token | everything the pull beta allows today | none (unattributed) |
| session credential | the same tools | the bound `agent_id` |
| unknown, revoked, expired | nothing | 401 |

`initialize` resolves the credential and pins `binding_id` to the
`Mcp-Session-Id`, but the pin is not the check: **every request re-reads the
binding** (one indexed lookup on a loopback server) and refuses when it is
revoked, stale, or its `generation` has moved. A 401 body names the fix
(`luciazero-agentd attach` again, then reconnect the MCP server); it never
echoes the credential. `/status` accepts either value and stays read-only.

### Which fields the daemon owns, and which stay arguments

Pinning "the `agent_id` argument" is not enough, because the tools name the
actor with four different words and one of them is also a query field:

| Tool | Actor field the daemon fills and enforces | Free arguments |
| --- | --- | --- |
| `agent_register`, `agent_heartbeat` | `agent_id` | provider, role, capabilities, ttl |
| `message_send` | `sender` | `recipient`, kind, payload, correlation, reply_to |
| `message_inbox`, `message_ack` | `agent_id` | delivery, states, outcome |
| `task_create` | `created_by` | `assigned_to`, title, payload, priority |
| `task_claim`, `task_complete` | `agent_id` | task, result, outcome |
| `artifact_publish` | `produced_by` | kind, ref, task, sha256 |
| `worktree_bind` | `agent_id` | path, base |
| `approval_consume` | `agent_id` | task, operation, nonce |
| `agent_list`, `task_list`, `artifact_get`, `worktree_get` | none: read-only | all, including another agent's id |

On a credentialed session every actor field may be omitted and is filled in
by the daemon; supplying one that contradicts the binding is refused with
`IdentityMismatch` and recorded as `session.identity_refused`. Target fields
(`recipient`, `assigned_to`) and read-only queries are untouched: the M4 flow
needs the implementer to call `worktree_get` on the reviewer's id to find the
finding's worktree, so `agent_id` is an actor field on eight tools and a
query subject on `worktree_get`. Any tool added later must state which column
it is in before it ships.

A read-only `agent_whoami` returns what the daemon believes, so the model
asks instead of being told:

```json
{"agent_id": "claude-reviewer", "provider": "claude", "binding_id": "bind_...",
 "tty": "ttys004", "pid": 1234}
```

`luciazero-agentd whoami` and `luciazero-agentd sessions` show the same
records from the human side.

### Binding lifecycle

A binding is `active`, then `revoked` (the user ran `detach`, or rebound that
terminal to another agent) or `stale` (the process is gone). Staleness is
checked without a background thread: the daemon proves the process still
exists and still has the recorded start time (`kill(pid, 0)` plus a start-time
compare) whenever it resolves a credential, and the human commands
(`terminal list`, `sessions`, `bus status`) reap what they walk past. A stale
or revoked binding invalidates its credential and its MCP session, and
records `binding.stale` or `binding.revoked` against the binding. Credentials also carry an
absolute expiry so a machine that sleeps for a week wakes up with nothing
live.

### The invariant: unattributed never reads as proven

One rule outranks the rest of this document, because every other guarantee
here is downstream of it. **An unattributed request must never be presented,
recorded, or answered as a request with a proven identity.** In practice:

- `agent_whoami` on a session with no credential returns
  `{"verified": false, "agent_id": null}` and the reason. It never guesses
  from the worktree, the process table, or a single registered agent.
- Every event and record written by such a session carries
  `trust: "asserted"`; a verified one carries `trust: "bound"`. There is no
  default that omits the field, so a missing field is a bug, not a maybe.
- `bus status`, `sessions` and `terminal list` mark those agents
  `unverified`, and the word appears in the same line as the agent id, not in
  a legend somewhere else.
- `--allow-unattributed` decides only whether such a request is *permitted*.
  It must never change how one is *labelled*. A test asserts both halves.

### Unattributed sessions are a named legacy mode, not a quiet default

The worktree fallback cannot establish identity: the daemon never sees the
provider's working directory, so `worktree_bind` believes an `agent_id` the
model supplied. Calling that a fallback identity would be exactly the
confusion this ADR removes. Instead:

- A session with no credential runs **unattributed**: identity is
  model-asserted, every event it writes records `trust: "asserted"`, and
  `bus status` marks the agent `unverified`.
- The daemon flag `--allow-unattributed` decides whether that is permitted.
  **It is off by default** (decided 2026-09-04, before M5): dispatch is built
  on identity, so the base cannot be a bus where agents may wear each other's
  names. Turning it on is a human choice at `serve` time and nothing an agent
  can ask for.
- With it off, acting calls without a credential are refused; read-only
  tools, `agent_whoami` and the human CLI still work. Spending a human
  approval needs a binding whatever the flag says, and managed dispatch will
  join it there in M6: an unverified session must never consume consent.
- Sessions already connected with the shared token cannot be upgraded in
  place; they reconnect or restart.
- Worktree binding keeps its M3 job, which is exclusion, not identity: one
  writer per checkout. Two guarantees, not one restated.

## Consequences

- On a credentialed session the model can no longer choose or change its
  identity, and no longer needs to be told it: the user chooses, in a
  terminal, with a command. On an unattributed session nothing changes and
  nothing is claimed; the records say so.
- Identity becomes a property of the connection, so the same daemon can hold
  a verified and an unverified session at once. `bus status`, the event log
  and `sessions` must show which is which, or the distinction is theatre.
- A session that is already running against the shared token cannot be
  remapped in place. `attach` writes a new MCP configuration and the session
  must reconnect or restart before the daemon can attribute it; `run` avoids
  the problem by construction. This limit is inherent to header-time
  credentials and must be documented in the skill, not hidden.
- The daemon gains a credential table (schema v3), a resolve step at
  `initialize`, and a binding re-read on every request. Every existing
  single-token path keeps working while `--allow-unattributed` is on, so
  M0-M4 evidence stays valid; the flag flipping off is a breaking change for
  anyone who wired the bus by hand and belongs in a release note.
- Killing a bound terminal must not strand its work: the binding goes stale,
  its credential dies with it, and the tasks it claimed stay claimed. The
  human path out is `cancel`, exactly as in the pull beta. Reassignment is
  still M6.
- `terminal list` reads the process table with `ps` (and `lsof -d cwd` on
  macOS, `/proc/<pid>/cwd` on Linux). Provider CLIs put several processes on
  one tty (`codex` plus its code-mode host and bundled helpers were observed
  sharing `ttys002`), so the listing shows the top-level provider process per
  tty and nothing else.
- PID reuse is defeated by comparing the recorded process start time, not the
  pid alone.
- An IDE session has no controlling terminal. It binds by pid, cwd and the
  credential; the tty column is empty and `run` is the recommended path.
- A tmux pane owns its own pseudo-terminal, so each pane binds separately.

## Threat model

Unchanged from ADR 0003 in kind: the bus defends against confused or stale
cooperative agents, not against a hostile process running as the same user.
A process with the user's privileges can read a credential out of the
provider's environment or configuration exactly as it can read the daemon
token, and the daemon cannot tell that apart from the legitimate session.
What is in scope is casual exposure to *other* users of the machine, which
is why no credential is ever written to argv: `ps` shows a command line to
everyone by default, while the environment and a `0600` file do not.

Liveness is checked on the authentication path, so it fails closed: if the
process table cannot be read, the credential is refused rather than trusted.
The process start time is cached for a few seconds, which bounds how long a
reused pid could be mistaken for the bound one.
Session credentials raise the cost of an accidental impersonation to zero
plausibility and make every impersonation attempt visible in the event log;
they do not make the loopback endpoint a trust boundary between processes.

## Alternatives considered

- **Terminal records without credentials.** Rejected: the daemon would still
  authorise on the model's own claim, so the record would describe an
  intention nobody enforces.
- **One daemon token per agent, minted at roster time.** Rejected: a token
  that outlives the terminal is copied into a config file and reused by the
  next session in any window, which is the problem restated.
- **Attributing requests by TCP peer inspection.** Rejected: the peer of a
  loopback connection is the provider process, but a CLI may proxy through a
  helper, and the mapping breaks under any relay. Not portable, not stable.
- **Provider session id as the binding.** Rejected for this milestone: it
  answers "resume which conversation", not "which window is the reviewer",
  and Codex cannot resume a thread that has not taken a turn (ADR 0001 null
  result). It stays a separate identity for M5/M6.

## Rollback

Drop the credential table and the resolve step; sessions fall back to the
shared token and the worktree binding, which is exactly the pull beta as
shipped in M4. `terminal list` is read-only and can stay.

## Amendment, 2026-09-04 (M7c): the two-phase claim

`run` and `attach` cover the sessions the user starts *for* the bus. They do
not cover the ordinary case: a `claude` or `codex` window already open, doing
something else, which then wants to be an agent. Until M7c that session had
one option, `--allow-unattributed`, which is the legacy mode this ADR spent
its length arguing against.

### Contract

1. The session calls `agent_claim_begin(agent_id)` and is **pinned to the MCP
   session immediately**, before the request id exists. The id is therefore a
   reference, not a bearer token: presenting it approves *the session that
   asked*, never the presenter.
2. `agent_id` must already be on the roster. A model may ask for an identity a
   person created; it may not invent one.
3. The daemon prints a one-time code (8 hex characters) **on its own console
   and nowhere else** — not in the tool result, not in the store in the clear,
   not in a file. The store keeps `sha256(code)` and `sha256(session_id)`.
4. A human approves from a terminal of their own:
   `luciazero-agentd claim approve <id> --code <code>`. Five wrong guesses
   close the request; the counter is committed in its own transaction, so a
   failed guess cannot be rolled back by the refusal it caused.
5. Approval binds the session in place, with no reconnect, and its writes are
   recorded as `bound` — worth exactly what `run`'s are worth.
6. A claim binding has no tty and no pid, so it is ended when the MCP session
   ends (DELETE, or eviction) and expires after an hour regardless.
7. A same-session `!command` or shell tool must not be able to approve its own
   request. This is what the code enforces; possession of a terminal does not.
8. The approval nonce for sensitive operations (ADR 0003) is a **separate**
   system and is still requested separately. Being `bound` is not being
   approved to delete anything.

### Why the console, and not process ancestry

The first design checked that `claim approve` was not running underneath a
provider process — a PPID walk plus an `isatty` check. It was defeated during
review by one line:

```sh
( { …; printf 'y\n'; } | script -q typescript sh -c '… claim approve <id>' & )
```

Orphaning erases ancestry, and `script` supplies a pty, so both checks pass
while the model is still the one deciding. Ancestry is not a boundary. The
daemon's own console is: the asking session is a different process, and it
cannot read another process's terminal.

### Rejected

- **Single-phase `agent_claim(agent_id, code)`.** The session would hold the
  code, which makes it a bearer token with extra steps: whoever reads the
  transcript is the agent.
- **Terminal possession as proof.** Holding a tty says a process is
  interactive, not that a *person* answered. If it is ever added it must carry
  a different trust label (`terminal_verified`), must not pass the approval or
  evidence gates, and must not be called human-bound.
- **Approving from the asking session with a confirmation prompt.** The model
  can write to its own stdin.

## Amendment, 2026-09-04 (M7d): the dialog is a channel, not a second decision

The console code is safe and it is a chore: a second window and a copied code
for every session the user starts. So the daemon can raise a dialog instead —
`osascript` on macOS, `zenity` then `kdialog` on Linux and BSD with a display,
a PowerShell `MessageBox` on Windows (passed as `-EncodedCommand`, UTF-16LE
base64, so no shell and no PowerShell quoting rule parses peer-supplied text).

It decides the same request, through the same `decide_claim`, holding the same
code the console would have printed. The property is unchanged because the
*place* is what mattered: the daemon raises the window, so the session that
asked cannot read it or press its buttons. A dialog that times out or is
killed decides nothing; only Allow approves.

### The assumption this rests on: local desktop integrity

The dialog is proof that a person answered **only while the local desktop is
intact**. It is not a defence against a process that can drive another
process's user interface, and on every supported platform that capability
exists and can be granted:

- macOS: Accessibility / Automation permission granted to the terminal
  application the model runs in lets it script `System Events` and click the
  button.
- X11: there is no isolation between clients on a display; any client can
  synthesise input for any window. Wayland is better, not a guarantee.
- Windows: UI Automation and `SendInput` reach other windows in the same
  session.

If the user has granted UI-automation permission to the terminal the model is
running in, neither the dialog **nor** the console code survives — the same
permission reads the window that shows the code. This is stated rather than
mitigated: it is the same trust boundary as the rest of this ADR (a hostile
process running as the same user is out of scope), and a user who needs to
hold that line should revoke the permission and use `run`, where identity
comes from a terminal the user opened rather than from an answer on screen.

## Amendment, 2026-09-04 (M7e): a daemon with no console fails the claim closed

Running the daemon as a per-user service (launchd, systemd `--user`) removes
its console. The code has nowhere private to go: a service's stdout is a log
file in the state directory, which the asking session can open. Writing the
code there would keep the ceremony and lose the property.

So the daemon answers `agent_claim_begin` with `NoApprovalChannel` and opens
no request at all when it has neither a screen nor a terminal — fail closed,
not fail pending, because a request nobody can answer is still a request
waiting for whoever finds a way to answer it. The refusal names the two ways
back: `luciazero-agentd run --agent <id> -- <provider>`, which needs no claim,
or serving in a window where the code is printed.

Where a screen does exist the dialog still works: a macOS LaunchAgent runs in
the GUI session, and a systemd unit gets `DISPLAY`/`WAYLAND_DISPLAY` captured
into its own `Environment=` at install time (scoped to that unit, not imported
into the whole user environment). The service never runs with
`--allow-unattributed`; the planner refuses to build such a command, because
a background daemon is exactly where nobody would notice unverified sessions
being trusted.

"Has a screen" is answered per session, not per platform. A Mac reached over
SSH has no Aqua session for `osascript` to draw into, so it counts as no
display: otherwise the daemon would pick the dialog, the window would never
appear, and the request would sit open with its code printed nowhere — the
one outcome this amendment exists to prevent. Over SSH there is a terminal,
so the console code is the channel.

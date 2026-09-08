---
name: lucia-chat
description: "Set two agent sessions talking through the Luciazero Agent Bus and watch it live in a terminal: pick the pair, open the windows, read the transcript. Use for \"ให้ codex กับ claude คุยกัน\" or \"watch the bus\"."
---

# Lucia Chat

`/lucia-bus` is how *you* take part in the bus. This is how the user sets up a
conversation between two other sessions: one window per agent, and an optional
read-only pane showing every message as it lands.

After `./install.sh`, `lucia` is that command from anywhere and
`luciazero-agentd` is the same program under its long name. Without the
launcher, each command below is the same one run as `python3 -m
luciazero_agentd` from the repository's `agentd/` directory, which is the form
the bus itself prints. Run them in the user's terminal, or hand them over to
paste. Never start a provider session on their behalf without being asked to.

## 1. Start here, always

```bash
lucia next
```

It reads the bus and answers the only question the user actually has — what is
waiting on whom — as the command that unblocks it, most blocking first: a
delivery nobody could deliver or a task that ran out of budget (both need a
person to decide something), then each agent with unread messages and the
command that opens its session in its own worktree. If the daemon is down it
says so and nothing else, because nothing else can happen first:

```bash
lucia serve
```

Read the answer back to the user and offer to run the command it names; do not
paraphrase it into different commands. `status` is still there for the full
picture, and `next` never writes anything.

## 2. Open one window per agent

```bash
lucia claude
lucia codex
```

The provider is the verb: each starts that provider with the binding already in
place, as the agent whose id is the provider's own name. A second window for the
same provider needs a name of its own or the bus refuses the duplicate —
`lucia claude --as reviewer` is the agent `claude-reviewer`. An id that is not a
provider's name takes the long form, which is what `chat` prints:

```bash
lucia run --agent codex-architect -- codex
```

Each agent's git checkout must be its own: start the second session from a
separate worktree, or `worktree_bind` refuses it. A daemon is started if this
state directory has none; `--no-autostart` refuses instead of starting one.

## 3. What starts the other session's turn

A session runs code during a turn and not one moment otherwise, so a delivery
landing while it sits at its prompt is read by nothing. `run`, and the short
forms above, hold the provider's terminal, so the bus can type one line into it:
the literal `check your bus inbox`, and in brackets only what it counts itself —
`check your bus inbox (2 new tasks from codex)`. No word of a payload is ever
typed; payloads arrive through `message_inbox`, where `/lucia-bus` treats them
as untrusted input.

The knock is narrow on purpose: nothing is typed until the agent has used the
bus in this session, only a delivery arriving after that session started counts,
each knock waits out a 20-second cooldown, and knocking stops after 8 in a row
with nobody at the keyboard — any keystroke starts that count over, and
`--max-nudges` changes the cap. A delivery the cap holds back is not lost; it
knocks as soon as a person is back.

`--no-nudge` is the pull-only flow: that session is never typed into and reads
its inbox when its own turn next starts — which somebody has to start. It is
also what happens wherever there is no terminal to type into, such as a piped
run or a dispatched turn.

## 4. When the pair is not obvious

```bash
lucia chat
lucia chat --between codex-architect claude-implementer
lucia roster add claude-implementer claude implementer
```

`chat` lists the roster with the terminal each agent currently holds, asks which
two, and prints the exact command for each window; `--between` skips the
questions. It reads the database read-only and writes nothing, so it is safe to
run mid-conversation. `roster add` names an agent that has never been seen.

## 5. Watch it happen (optional)

```bash
lucia watch --between codex-architect claude-implementer
```

Neither session needs this. Open it first and the conversation is visible from
its first message. `--payload full` shows the whole body, `--payload none` only
who spoke to whom, and `--agent X` (repeatable) widens the filter beyond one
pair. It shows traffic and never touches it: it acknowledges nothing, because
`acknowledged_at` has to keep meaning that an agent opened the message itself.

## 6. Reading the pane

```
17:42:22  codex-architect -> claude-implementer  [task]    M7a: read-only inbox watcher
17:53:22  claude-implementer opened it after 11m
```

Three different numbers live in that gap and they are not interchangeable:

* **delivery latency** — send to the peer's acknowledgement, the second line
  above. Under a knock it is the knock plus what that session takes to start a
  turn; under `--no-nudge`, however long until somebody gives it one.
* **completion latency** — send to the answer coming back: the reply, or
  `task_complete` with its artifacts.
* **user-attributed blocking cost** — how long the user's own work stood still
  waiting. An 11m gap is a person waiting, a session already mid-turn, or a
  window nobody sat at, and nothing recorded here tells those apart.

Report the first two from the timestamps, ask the user for the third, and say
which one any number is. A retro counts toward the beta gate only when a human
names the blocking cost.

## 7. Who is who

Starting a session prints no bus banner inside the provider: `run` names the
binding in the terminal that started it, before the provider takes the screen.
Ask the bus instead — `lucia sessions` for every live binding, `lucia terminal
list` for what each provider session is bound to, `lucia whoami` for the
terminal it runs in. Inside a session, `/lucia-bus` asks with `agent_whoami`.

## 8. Letting them answer each other

Turns started by the dispatcher instead of by a person are managed dispatch
(M6). Each turn starts a real provider process and spends real quota, so it is
never set up without the user asking for it in that many words:

```bash
lucia chat --between codex-architect claude-implementer --auto
```

That prints the commands and runs nothing. Enrol each side as a worker in **its
own** worktree, keep `--approve workspace` so a turn can work without being able
to accept whatever it is asked, and cap the run. A human approval nonce is still
unskippable for sensitive operations. An agent cannot be dispatched and hold a
human terminal at the same time: the managed turn opens its own session.

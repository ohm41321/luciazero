---
name: lucia-chat
description: "Set two agent sessions talking through the Luciazero Agent Bus and watch it live in a terminal: pick the pair, open the panes, read the transcript. Use for \"ให้ codex กับ claude คุยกัน\" or \"watch the bus\"."
---

# Lucia Chat

`/lucia-bus` is how *you* take part in the bus. This is how the user sets up a
conversation between two other sessions and watches it happen: three terminals,
one of them a read-only pane showing every message as it lands.

Every command below runs from the repository's `agentd/` directory. If the
user has run `./install.sh`, `luciazero-agentd X` is the same command from
anywhere, and that is the form the bus itself prints. Run them in the user's
terminal, or hand them over to paste. Never start a provider session on their
behalf without being asked to.

## 1. Start here, always

```bash
python3 -m luciazero_agentd next
```

It reads the bus and answers the only question the user actually has — what is
waiting on whom — as the command that unblocks it, most blocking first: a
delivery nobody could deliver or a task that ran out of budget (both need a
person to decide something), then each agent with unread messages and the
command that opens that agent's session in its own worktree. If the daemon is
down it says so and nothing else, because nothing else can happen first:

```bash
python3 -m luciazero_agentd serve
```

Read the answer back to the user and offer to run the command it names; do not
paraphrase it into different commands. `status` is still there for the full
picture, and `next` never writes anything.

## 2. Pick who talks (when the user wants a new conversation)

```bash
python3 -m luciazero_agentd chat
```

It lists the agents on the roster with the terminal each one currently holds,
asks which two, and prints the exact command for each terminal. It reads the
database read-only and writes nothing, so it is safe to run mid-conversation.

When the pair is already known, skip the questions:

```bash
python3 -m luciazero_agentd chat --between codex-architect claude-implementer
```

An agent that has never been seen is not on the roster yet:

```bash
python3 -m luciazero_agentd roster add claude-implementer claude implementer
```

## 3. Open the three terminals

The watcher first, so the conversation is visible from its first message:

```bash
python3 -m luciazero_agentd watch --between codex-architect claude-implementer
```

Then one terminal per agent, each started so the binding is already in place —
`run` never prints the session credential, which is why it is the form to use:

```bash
python3 -m luciazero_agentd run --agent codex-architect -- codex
python3 -m luciazero_agentd run --agent claude-implementer -- claude
```

Each agent's own git checkout must be its own: start the second session from a
separate worktree, or `worktree_bind` refuses it.

## 4. Read the pane

```
17:42:22  codex-architect -> claude-implementer  [task]    M7a: read-only inbox watcher
17:53:22  claude-implementer opened it after 11m
```

The second line is the number that matters: nothing acknowledges a delivery
until a human starts that agent's turn, so the gap between a message and its
acknowledgement is what a user-started turn costs. `--payload full` shows the
whole body, `--payload none` shows only who spoke to whom, and `--agent X`
(repeatable) widens the filter beyond a single pair.

## 5. What this does not do

The watcher shows traffic; it never touches it. It acknowledges nothing, and it
cannot wake a session that is sitting at its prompt: each agent reads its inbox
when its own turn starts, so a message sent while the other terminal is idle
waits there until the user gives that session a turn. Say this plainly rather
than promising a conversation that runs by itself.

## 6. Letting them answer each other

Turns started by the dispatcher instead of by a person are managed dispatch
(M6). Each turn starts a real provider process and spends real quota, so it is
never set up without the user asking for it in that many words:

```bash
python3 -m luciazero_agentd chat --between A B --auto     # prints the commands, runs nothing
```

Enrol each side as a worker in **its own** worktree, keep `--approve workspace`
so a turn can work without being able to accept whatever it is asked, and cap
the run. A human approval nonce is still unskippable for sensitive operations.
An agent cannot be dispatched and hold a human terminal at the same time: the
managed turn opens its own session.

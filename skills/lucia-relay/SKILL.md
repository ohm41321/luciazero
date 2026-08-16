---
name: lucia-relay
description: Transfer unfinished work and non-obvious knowledge across sessions, agents, people, machines, or harnesses. Use for relay, handoff, continuing later, context transfer, compaction, or "ส่งต่อ"; produce verifiable portable state.
---

# Lucia Relay — knowledge that survives the messenger

`/retro` stores permanent lessons. `/lucia-relay` transfers task-local state. The canonical artifact is `LUCIA_RELAY.json`; `LUCIA_RELAY.md` is its generated human view. A receiver trusts neither until the tree and verification evidence agree.

## Decide the route first

Before writing or pointing anywhere, answer: **Where is the recipient?**

- `same-machine`: the receiver shares this machine. Full local paths are allowed.
- `cross-machine`: the receiver cannot open anything local. Every pointer must be repo-relative and present in a pushed commit, or the needed knowledge must be copied into `knowledge.inline` in `LUCIA_RELAY.json`.

If the destination is not explicit and cannot be inferred, ask the user. Never assume a local path will travel.

## Produce

1. Locate this skill's installed directory and run `<this-skill-dir>/scripts/relay.py draft --root . --recipient <same-machine|cross-machine>`. Always pass the route explicitly; the CLI's `same-machine` default exists only so older callers keep working.
2. Create `LUCIA_RELAY.json` at the repo root. Fill the original goal, completed and in-progress work, one literal next action, verification evidence, relevant files, read-first pointers, inline knowledge, open **and refuted** hypotheses, and landmines. Keep the captured `route` and `repository` objects from the draft.
3. For `cross-machine`, commit and push every task file first. Start each `read_first` entry with its repo-relative tracked path; an optional note may follow ` — `. Replace machine-local document, memory, or artifact pointers with a short `{ "label": "...", "content": "..." }` entry in `knowledge.inline`. Do not include credentials.
4. Run `<this-skill-dir>/scripts/relay.py render --root .`; fix every validation error and review both artifacts for secrets and route mistakes.

Evidence rules:

- A verification entry includes the exact command, exit code, shortest decisive line, and run time. Never turn “not run” into implied green.
- The next action is executable: a command, exact edit, or decision. “Continue the refactor” is invalid.
- Preserve refuted hypotheses and why they failed. They are the knowledge most likely to save the receiver time.
- Point to relevant `docs/lessons.md` entries. For cross-machine delivery, inline an essential machine-local heuristic instead of pointing to its local file; omit secrets, credential locations, personal paths, and preferences.

## Route

- Same worktree/session boundary: leave both files uncommitted; the SessionStart hook points at them.
- Another local agent or harness sharing the tree: give it both full paths and ask it to run `inspect` before editing.
- Cross-machine/person: give the pushed repository ref plus both artifacts. The validator rejects a dirty tree, a HEAD absent from locally known remote branches, and machine-only paths. If repository policy requires the relay files on the branch, review them for secrets, then force-add the ignored transient artifacts with `git add -f LUCIA_RELAY.json LUCIA_RELAY.md`. State explicitly that they must be consumed and removed after re-verification.
- Chat-only channel: paste the JSON artifact; it is canonical and can regenerate the Markdown view.

Do not copy the conversation transcript. Transfer decisions, evidence, negative knowledge, and pointers to source-of-truth files.

## Receive

1. Run `<this-skill-dir>/scripts/relay.py inspect --root .` and read both artifacts before touching code.
2. Read every `read_first` pointer and inspect the named changed files.
3. Compare the relay fingerprint with the current tree. Drift is a warning that the relay describes an earlier state.
4. Re-run the listed verification commands. The tree is truth; if evidence differs, report the mismatch and update the plan from current state.
5. After absorbing the knowledge, run `<this-skill-dir>/scripts/relay.py consume --root . --verified`. This explicit flag asserts that re-verification happened and removes both transient files. Write a fresh relay later; never accumulate or incrementally nurse a stale one.

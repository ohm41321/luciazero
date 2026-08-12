---
name: lucia-relay
description: Package unfinished work and non-obvious knowledge into a portable, verifiable relay for another session, agent, person, machine, or coding harness. Use when the user says "relay", "ส่งต่อ", "continue later", asks to transfer context to another agent, switches harnesses, or when a long task must survive compaction. Replaces the generic handoff skill.
---

# Lucia Relay — knowledge that survives the messenger

`/retro` stores permanent lessons. `/lucia-relay` transfers task-local state. The canonical artifact is `LUCIA_RELAY.json`; `LUCIA_RELAY.md` is its generated human view. A receiver trusts neither until the tree and verification evidence agree.

## Produce

1. Locate this skill's installed directory and run `<this-skill-dir>/scripts/relay.py draft --root .` to see the schema and captured repository fingerprint.
2. Create `LUCIA_RELAY.json` at the repo root. Fill the original goal, completed and in-progress work, one literal next action, verification evidence, relevant files, read-first pointers, open **and refuted** hypotheses, and landmines. Keep the captured `repository` object from the draft.
3. Run `<this-skill-dir>/scripts/relay.py render --root .`; fix every validation error and review both artifacts for secrets or machine-only paths.

Evidence rules:

- A verification entry includes the exact command, exit code, shortest decisive line, and run time. Never turn “not run” into implied green.
- The next action is executable: a command, exact edit, or decision. “Continue the refactor” is invalid.
- Preserve refuted hypotheses and why they failed. They are the knowledge most likely to save the receiver time.
- Point to relevant `docs/lessons.md` entries. Copy a machine-local heuristic only when it is essential and contains no secret, credential location, personal path, or preference.

## Route

- Same worktree/session boundary: leave both files uncommitted; the SessionStart hook points at them.
- Another local agent or harness sharing the tree: give it both paths and ask it to run `inspect` before editing.
- Cross-machine/person: attach both files. If repository policy requires a branch transfer, review both files for secrets, then force-add the ignored transient artifacts with `git add -f LUCIA_RELAY.json LUCIA_RELAY.md`. State explicitly that they must be consumed and removed after re-verification.
- Chat-only channel: paste the JSON artifact; it is canonical and can regenerate the Markdown view.

Do not copy the conversation transcript. Transfer decisions, evidence, negative knowledge, and pointers to source-of-truth files.

## Receive

1. Run `<this-skill-dir>/scripts/relay.py inspect --root .` and read both artifacts before touching code.
2. Read every `read_first` pointer and inspect the named changed files.
3. Compare the relay fingerprint with the current tree. Drift is a warning that the relay describes an earlier state.
4. Re-run the listed verification commands. The tree is truth; if evidence differs, report the mismatch and update the plan from current state.
5. After absorbing the knowledge, run `<this-skill-dir>/scripts/relay.py consume --root . --verified`. This explicit flag asserts that re-verification happened and removes both transient files. Write a fresh relay later; never accumulate or incrementally nurse a stale one.

---
name: handoff
description: Write a state capsule so the next session — or a different agent/harness — can resume unfinished work without re-deriving context. Use when a session is ending with work incomplete, when the user says "handoff", "pack up", "ส่งต่อ", "continue tomorrow", when switching between Claude Code and Codex mid-task, or when context is about to be compacted away on a long task.
---

# Handoff — state that survives the session

`/retro` records **permanent lessons**; this records **transient state**. A good capsule lets a stranger (including future-you with zero context) type one command and be productive in two minutes. A stale capsule is worse than none — so capsules are consumed and deleted, never accumulated.

## 1. Write the capsule

Create `HANDOFF.md` at the repo root:

```markdown
# Handoff — <date>

## Goal
<the original request, one paragraph, verbatim enough to re-anchor>

## State
- Done: <what is finished, and the verify evidence: command → decisive line>
- In progress: <the exact piece mid-flight, and which files hold it>
- Verify: <the command(s) to run, fast and full tier>

## Next step
<ONE literal command or edit to do first — not a theme, an action>

## Open hypotheses
- H1: <suspected cause / approach> — status: <untested | supported by X | refuted by Y>

## Landmines
- <thing that looks safe but is not, discovered this session>

## Read first
- docs/lessons.md: <quote the symptom line of each lesson that touches the
  unfinished work — 1-3 entries, not the whole ledger>
- from this machine's cross-repo heuristics (do not travel with the repo):
  <copy the specific entries that apply, verbatim>
```

Rules:

- **The next step is literal.** "Continue the refactor" is not a next step; "run `pytest tests/test_auth.py -k refresh` — it is the failing one" is.
- **State only what this session knows.** No aspirations, no backlog — that belongs in the issue tracker.
- **Refuted hypotheses stay in the capsule** — they are exactly what the next session would otherwise waste an hour re-deriving. If a lesson is permanent (true beyond this task), it also goes through `/retro`.
- Uncommitted changes: say so explicitly, and name the files. The capsule must not imply a clean tree that is not clean.
- **Read first is a selection, not a copy.** The repo's `docs/lessons.md` travels with the code — quote only the symptom lines relevant to the unfinished work so the reader knows which entries to open before touching it (rule 8, applied for them). Machine-local memory is the exception: entries in this machine's `luciazero-heuristics.md` (config dir) do **not** travel, so any that apply get copied verbatim — the capsule is their only ride. Nothing relevant? Say `none` — an empty section is information too.

## 2. Route it

- **Same machine, next session** — `HANDOFF.md` in the repo root is enough. Do not commit it.
- **Cross-machine or another person/agent** — commit it on the working branch (it travels with the code), and say in the final message that it exists.
- The project's notes file does **not** get the capsule — notes are permanent, capsules are transient. A one-line pointer is fine if the repo's convention wants one.

## 3. Consume protocol (for the reader)

A session that finds `HANDOFF.md`:

1. Read it **before** touching the code — including the lessons entries `Read first` points at, and copy any machine-local heuristics it carries into your own config-dir ledger if they earn their keep.
2. Run the Verify command(s) to confirm the described state is still true — the capsule describes the past; the tree is the truth.
3. **Delete the capsule** (or `git rm` on the branch) once absorbed. Never leave a consumed capsule to go stale; never update one incrementally across many sessions — write a fresh one at each handoff.

If the capsule and the tree disagree, trust the tree and say so.

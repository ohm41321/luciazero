---
name: retro
description: Harvest lessons from the session into the project's permanent notes. Use after finishing a hard task, a long debugging session, or any work that hit dead ends — when the user says "run a retro", "record what we learned", "จดบทเรียน", or when a task ends having disproven an approach that looked right.
---

# Retro — turn experience into recorded knowledge

The doctrine says: *never re-derive a dead end twice.* This skill is the procedure that makes it actually happen. A team that logs its null results stops paying for the same experiment twice — that is the cheapest intelligence upgrade available.

## 1. Scan the session

Walk back through the work just finished and list candidates:

- What took the longest, and was the time spent where you first expected?
- Which attempts **failed**, and what was the real cause once found?
- What looked like the right approach but was wrong — and why exactly?
- What surprised you: environment quirks, undocumented behavior, a flag or version that mattered?
- What did you have to re-discover that should already have been written down?

**Also read the discipline report**, if the enforcement pack is installed: run `npx luciazero discipline --project . --json` (or use `/discipline-report`). Recurring `nudge` or `strict-block` outcomes are behavioral evidence, but not a recorded cause. State any diagnosis as `likely` until repo evidence confirms whether the verify command is missing, too slow, or simply not being run.

## 2. Filter hard

Record only what **reading the code cannot tell a future agent**:

- ✅ Null results: "tried X, measured no gain / broke Y — do not retry without new evidence"
- ✅ Footguns: "A looks correct but silently breaks B"
- ✅ Environment facts: version pins, platform quirks, commands that must follow other commands
- ✅ Why a tempting approach is wrong (with the one-line evidence)
- ❌ What the diff/git history already says
- ❌ Anything a `grep` or `--help` answers
- ❌ Session-only details (temp paths, one-off values)

A null result is worth exactly as much as a success. If the session proved nothing new, say so and stop — an empty retro is a valid result; padding it with restated code facts makes every future session pay for noise.

## 3. Route it, then write it

**First decide who the lesson is true for:**

- **Anyone who clones the repo** — code behavior, build quirks, disproven approaches → the committed notes below. A **debugged failure** specifically goes to the repo's lesson ledger `docs/lessons.md` in this fixed shape, so `/debug` can seed its hypothesis ledger from it next time:

  ```
  ## <one-line symptom, greppable — include the error string>
  cause: <root cause> | proven-by: `<command>` | fix: <what fixed it> | date: YYYY-MM-DD
  ```

- **True in every repository** — engineering lessons not tied to this codebase ("intermittent async test: check timezone pinning before touching the test") → append one line to `luciazero-heuristics.md` in the harness config dir (`~/.claude` / `~/.codex`). Hard rules: one line per lesson, same update-in-place/dedup discipline, **cap the file at 100 lines** — when full, drop the weakest entry rather than growing (an unbounded heuristics file becomes context tax, the exact failure this pack exists to prevent). Never personal paths or secrets, even here.
- **Only this machine or this user** — local paths, installed tool versions, personal preferences, credential locations → must **never** be committed. If the harness provides a persistent memory directory (Claude Code announces its per-project `memory/` dir and `MEMORY.md` index in context when enabled), write it there and update the index, applying the same format, dedup, and prune rules. If no memory system exists (Codex CLI, or memory disabled), keep only the generalization that is true for anyone who clones the repo — never personal preferences or credential locations, even generalized; if nothing repo-true remains, state the lesson in the retro report instead of writing it anywhere — an honest gap beats a note no harness will ever load.

Format, one entry per lesson:

```
- **<topic>** — tried <X>; failed because <Y>; do <Z> instead. (evidence: <shortest decisive line>, <date>)
```

Committed destinations:

- **Project notes file** (`CLAUDE.md` / `AGENTS.md` — extend the one the repo uses) — if the lesson is load-bearing for most future sessions and fits in 1–2 lines.
- **`docs/<topic>.md`** — if it needs detail (measurements, alternatives tried, tables); then put a one-line pointer in the notes file.
- Follow the project's existing convention if it already has an experiments log or notes dir — extend it, do not invent a parallel one.

## 4. Dedup and prune

Before writing, read the existing notes (and `MEMORY.md` when routing to harness memory):

- If a note on the topic exists, **update it in place** — do not append a duplicate.
- If the session **disproved** an existing note, correct or delete it and say so in the report.
- The same two rules govern `docs/lessons.md` and `luciazero-heuristics.md`: a ledger entry whose cause this session disproved gets corrected or deleted — a stale lesson mis-seeds every future `/debug`.

## 5. Verify as a future reader

Re-read each entry pretending it is six months later and context is gone. Would you know what to do differently? If an entry needs this session's context to make sense, rewrite it with the missing facts inline.

Report what was recorded, where, and what was deliberately not recorded (and why).

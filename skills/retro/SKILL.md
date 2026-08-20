---
name: retro
description: Record durable lessons, null results, and footguns after hard work or debugging. Use when the user asks for a retro, dead ends need preserving, a task disproves an approach, or "จดบทเรียน". Keep repo knowledge separate from machine-local memory.
---

# Retro

Never re-derive a dead end twice. Record only knowledge future work cannot
recover cheaply.

## 1. Scan the session

Ask:

- What took the longest?
- Which attempts **failed**, and why?
- What plausible approach was wrong?
- What environment/version/flag surprised us?
- What had to be rediscovered?

Also read the discipline report when installed: prefer local
`luciazero discipline --project . --json`, then the checkout/package CLI.
Use `npx` only when package resolution is explicitly allowed. A nudge or block
is evidence, not cause; state any diagnosis as `likely` until repo evidence
confirms it.

## 2. Filter hard

Keep only what reading the code cannot tell a future agent:

- **Null results**: measured no gain or broke another property.
- **Footguns**: an apparently correct action silently breaks something.
- Environment facts, ordering constraints, and why a tempting path is wrong.

Reject diff/history summaries, session-only values, and Anything a `grep` or
`--help` answers. If nothing qualifies, stop: an empty retro is a valid result.

## 3. Route it, then write it

- **Anyone who clones the repo:** code/build behavior and disproven approaches.
  A debugged failure goes to `docs/lessons.md`:

  ```
  ## <greppable symptom; include exact error string>
  cause: <root cause> | proven-by: `<command>` | fix: <what fixed it> | date: YYYY-MM-DD
  ```

- **True in every repository:** append one deduplicated line to configured
  `luciazero-heuristics.md` under `${CLAUDE_CONFIG_DIR:-$HOME/.claude}` or
  `${CODEX_HOME:-$HOME/.codex}` for the active harness. Never include secrets
  or personal paths; cap the file at 100 lines and drop the weakest entry when
  full.

- **Only this machine or this user:** local paths, versions, preferences, and
  credential locations must **never** be committed. Use announced harness
  memory and update its `MEMORY.md` index when available. If no memory system
  exists, keep only a repo-true generalization; otherwise report the lesson
  without writing it.

Entry format:

```
- **<topic>** — tried <X>; failed because <Y>; do <Z> instead. (evidence: <line>, <date>)
```

Use the existing Project notes file (`CLAUDE.md`/`AGENTS.md`) for 1–2
load-bearing lines. Use `docs/<topic>.md` for detail and link it once. Follow
existing conventions; do not create a parallel notes system.

## 4. Dedup and prune

Read destinations first. For an existing topic, update it in place. If evidence
disproves an entry, correct or delete it. Apply this to project notes,
`docs/lessons.md`, heuristics, and memory; a stale lesson mis-seeds future
debugging.

## 5. Verify as a future reader

Read each entry as if six months later with no session context. Add the missing
action/evidence or delete it. Report what was recorded, where, and what was
deliberately not recorded and why.

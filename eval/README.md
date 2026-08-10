# Eval — does the doctrine actually change behavior?

The repo's own rule applies to the repo itself: a claim ("this setup makes
agents better") needs a measurement, not vibes. This harness is that
measurement — small, honest, and explicit about its limits.

## Design

Each task under `tasks/<name>/` is a self-contained fixture:

| File | Role |
|---|---|
| `project/` | the starting state the agent works on (contains a planted bug) |
| `PROMPT.md` | the task, phrased as a normal user request — never hinting at tests or the doctrine |
| `grade.sh <workdir>` | **offline, deterministic** grader of the worked copy |
| `reference/` | a solved copy — proves `grade.sh` can pass (used by `test.sh`) |
| `gamed*/` | hand-built **cheat** trees (one or more: `gamed/`, `gamed-hardcode/`, …) that fool a naive tests-green grader — proves `grade.sh` rejects each (required; enforced by `test.sh`) |

Grading is behavioral, from the final tree only — no transcript parsing.
Graders print one `CRIT <id> pass|fail` line per criterion plus a final
`SCORE n/m` (this is the machine-readable contract `run.sh --out` parses),
and exit zero only on a full score.

## The tasks

| Task | Planted bug | Doctrine rule probed | Fingerprint criterion |
|---|---|---|---|
| `slugify` | unicode stripped to empty slugs | regression-test discipline (rule 4) | suite must go red on the reverted fix; a contract **mutant** catches original tests gutted to `pass` bodies |
| `red-suite` | suite correct but red (exclusive vs inclusive day count) | never bend tests to a bug (rule 3) | the fixture's pristine tests, replayed against the worked code, must pass — and so must date pairs the visible tests never mention (kills lookup-table cheats) |
| `flaky-report` | set-iteration order leaks into output | make intermittent failures deterministic (rule 4) | suite + pristine tests green across `PYTHONHASHSEED` 0–9, plus exact output on entries absent from the fixture (kills hardcoded-string cheats) |
| `pipeline` | parser drops the final record; symptom appears two modules away | hypothesis-first, smallest diff (rules 4+6) | fix must land in `parse.py`; `transform.py`/`render.py` must stay AST-identical |

## Running

```bash
eval/run.sh                                # all tasks, both arms, one run
eval/run.sh slugify                        # one task
eval/run.sh --runs 5 --out results.jsonl   # the honest way: repeat, then
eval/report.sh results.jsonl               # per-criterion pass-rate table
```

Arm A installs this repo into a sandbox `CLAUDE_CONFIG_DIR`; arm B runs with
an empty config. Same prompt, same fixture, same grader.

**Costs real API money** and needs the `claude` CLI **plus `ANTHROPIC_API_KEY`
in the environment** — the sandbox `CLAUDE_CONFIG_DIR` isolates any
credentials stored in your real `~/.claude`, so without the env var both arms
fail identically. `run.sh` marks an arm whose `claude` invocation exited
non-zero as **INVALID** rather than grading it (and records it as such in the
JSONL): an agent that never ran is not behavioral data. It is deliberately
not part of `test.sh` or CI — CI only verifies the graders themselves, three
ways per task, all offline: `reference/` passes, unfixed `project/` fails,
`gamed/` is rejected.

## Honesty box

- **n is tiny and models are nondeterministic.** One run per arm proves
  nothing; run each arm ≥5 times and compare pass *rates* — `report.sh`
  prints the rates, the n, and a warning until you do.
- A doctrine effect can be masked by a model that already behaves well, or
  exaggerated by a prompt that hints at testing. Keep prompts natural.
- A buggy grader manufactures fake deltas in either direction — which is why
  every new criterion needs a fixture that proves it can fail (`project/` or
  `gamed/`), not just one that passes.
- The `gamed/` trees are literal worked examples of how to cheat these
  graders. That is the point — an untestable "cannot be gamed" claim is
  worth nothing — but remember they exist before quoting scores publicly.
- Add tasks by copying the `slugify/` shape. `test.sh` auto-discovers
  `tasks/*/` and will fail the build unless the new grader passes its
  reference, fails its project, rejects its gamed tree, and speaks the
  CRIT/SCORE contract.

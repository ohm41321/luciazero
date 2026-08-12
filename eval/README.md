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
| `lessons.md` | optional: a pre-seeded `docs/lessons.md` ledger for the `--with-lessons` arm — measures whether the learning layer lifts pass rates over the doctrine alone |

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
| `merge-conflict` | unresolved merge: bulk discount on one side, member discount on the other | skeptic diff pass — nothing silently dropped (rules 4+7) | both features probed on data the tests never mention; one-sided feature **mutants** swapped in must turn the worked suite red (proves each side is actually tested) |
| `false-green` | suite GREEN from the start, implementation wrong outside its coverage | done is proven by a command that probes the symptom, not by a green suite (rule 1) | untouched tree = the false-done handback and it fails; symptom probed on unseen data; with the bug restored the worked suite must go red |

## Running

```bash
eval/run.sh                                # all tasks, both arms, one run
eval/run.sh slugify                        # one task
eval/run.sh --runs 5 --out results.jsonl   # the honest way: repeat, then
eval/report.sh results.jsonl               # per-criterion pass-rate table
eval/run.sh --with-lessons --runs 5 --out r.jsonl   # + third arm (see below)
eval/run.sh --offline --out smoke.jsonl    # zero API, no key: pipeline smoke
eval/run.sh --use-login false-green --runs 1 --out s.jsonl   # real smoke on
                                           # subscription quota, no API key
```

`--offline` needs no `claude` CLI and no API key: doctrine-style arms get the
task's `reference/` tree, bare keeps the planted bug, and the full
copy → grade → JSONL → report loop runs in seconds. It exists so anyone can
try the harness before spending money — and it is **synthetic**: rows carry
`"offline": true` and `report.sh` brands the output `SYNTHETIC OFFLINE
SMOKE`. Never quote offline numbers as results.

Arm A (historically labeled `doctrine` in JSON output) installs the full classic
Luciazero pack without hooks—doctrine, skills, and reviewer—into a sandbox
`CLAUDE_CONFIG_DIR`; arm B runs with an empty config. This measures the installed
bundle, not a doctrine-only ablation. Same prompt, same fixture, same grader. `--with-lessons`
adds a third arm to every task that ships a `lessons.md`: doctrine install
*plus* the task's ledger pre-seeded as `docs/lessons.md` in the work copy —
the A/B/C comparison that tests whether `/retro`'s learning layer actually
pays. `--out` also records per-run duration, token usage, and cost (parsed
from the CLI's JSON output; null when unavailable), and `report.sh` appends
per-arm resource means whenever that data is present — a discipline that
lifts pass rates by tripling cost is not a free win, so the cost shows up
next to the delta.

**Costs real inference** and needs the `claude` CLI plus one of two ways to
pay: `ANTHROPIC_API_KEY` in the environment (API dollars), or `--use-login`
(your existing Claude subscription quota). The sandbox `CLAUDE_CONFIG_DIR`
isolates any credentials stored in your real `~/.claude`, so without either,
both arms fail identically as "Not logged in". `--use-login` copies this
machine's login state into each per-run mktemp config dir — `~/.claude.json`,
plus OAuth tokens from `.credentials.json` (Linux) or exported from the
Keychain (macOS, may prompt once to allow access); the copy is deleted with
the sandbox and never leaves the machine. If none of that authenticates on
your setup, the documented fallback is `claude setup-token` once and
`export CLAUDE_CODE_OAUTH_TOKEN=...` — env vars pass into the sandbox, no
flag needed. On subscription runs the CLI reports `cost_usd` as 0, so quote token
counts, not dollars. If the seed is not enough to authenticate on your OS,
nothing is spent — the arm is simply marked INVALID (see below). `run.sh` marks an arm whose `claude` invocation exited
non-zero as **INVALID** rather than grading it (and records it as such in the
JSONL): an agent that never ran is not behavioral data. Exit 0 is not trusted
either: `check-result.sh` inspects the result payload, because the CLI has
reported subtype `"success"` around a `Not logged in` error — that arm is
INVALID too, with the reason quoted (each accept/reject path is
fixture-proven by `test.sh`). It is deliberately
not part of `test.sh` or CI — CI only verifies the graders themselves, three
ways per task, all offline: `reference/` passes, unfixed `project/` fails,
`gamed/` is rejected.

## Honesty box

- **n is tiny and models are nondeterministic.** One run per arm proves
  nothing; run each arm ≥5 times and compare pass *rates* — `report.sh`
  prints the rates, the n, and a warning until you do.
- A Luciazero effect can be masked by a model that already behaves well, or
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

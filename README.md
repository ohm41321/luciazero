**English** | [ภาษาไทย](README.th.md)

# Luciazero for Claude Code & Codex CLI

[![npm](https://img.shields.io/npm/v/luciazero)](https://www.npmjs.com/package/luciazero)
[![CI](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg)](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml)
[![license](https://img.shields.io/github/license/ohm41321/luciazero)](LICENSE)

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia.png" width="300" alt="Lucia — Luciazero's mascot — hugging her cat plushie">
</p>

Luciazero makes a coding agent run its own `plan → change → verify → fix` loop instead of handing back unverified work. Its first rule is not about prompting:

> Done is proven by a command, not by my judgment. If no verification command exists, that is the first bug.

Everything in this repo — a 9-rule doctrine, 9 skills, a risk-routed adversarial reviewer, enforcement hooks, and an eval harness — exists to make that rule hold without a human in the loop.

## What it looks like

Actual output of the shipped scripts, not mockups — the GIF is recorded from `docs/assets/statusline-demo.sh`, which drives the real hooks through the loop (re-record it yourself: `vhs docs/assets/demo.tape`):

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/statusline-demo.gif" width="720" alt="The enforcement pack in 15 seconds: edit shows unverified, stopping triggers the nudge, a red verify shows RED, the fix turns it green">
</p>

The statusline keeps the verify state on screen:

```
Opus | ✎ unverified          # edits made, no verify run since
Opus | ✅ verify 3m           # last verify green, 3 minutes ago
Opus | ❌ verify RED 40s      # last verify failed — the loop is not done
```

Ending a session with unverified edits triggers the one-shot nudge:

```
Doctrine rule 1: edits were made but no verify command has run since the last
edit. Run the repo's verify command and quote its decisive line — or finish
anyway and say plainly that the change is unverified. (This nudge fires once.)
```

And in opt-in strict mode, a red verify actually blocks the stop, evidence attached:

```
Strict verify gate: './test.sh' is RED. Fix it before finishing — or say
plainly that you are handing back a red state. Failing output:

test_totals ... FAIL: expected 14, got 8
```

## What it prevents

Each failure mode maps to a shipped mechanism, not a promise:

| Failure mode | What catches it |
|---|---|
| "Done!" with no verify run | the Stop-hook nudge; in strict mode a red verify blocks the stop with the failing output quoted |
| `cat test.sh` counted as running the tests | `LUCIAZERO_VERIFY_CMD` exact-match mode |
| A check weakened, skipped, or deleted to reach green | doctrine rule 3, plus the inert check-suppression guard in the example project settings |
| New tests that pass with and without the fix | `revert-probe.sh` — exit 1 means the test is vacuous |
| Scope silently dropped from the request | `/done` step 4: every part is delivered or named as left out |
| The same dead end re-derived next session | `/retro` ledgers (`docs/lessons.md`, cross-repo heuristics) seeding `/debug` |

The mechanical rows are exercised by `test.sh` on every push; the procedural rows are what the eval harness exists to measure.

## Install

**Claude Code — plugin (recommended).** One install carries all 9 skills, the `reviewer` agent, the verify-tracking hooks, and the doctrine:

```
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

Then run `/luciazero:luciazero-bootstrap` in any repository (plugin skills are namespaced: `/luciazero:done`, `/luciazero:debug`, …). Honest print: installing the plugin is what enables its hooks — that install step *is* the opt-in; the doctrine loads via a `SessionStart` hook because plugins cannot add a `CLAUDE.md` import line (same word-ceiling-capped text, and it stays silent when a classic install exists, so it never loads twice); and there is no statusline, because Claude Code does not let plugins set `statusLine`.

**Any agent — skills only.** Via [vercel-labs/skills](https://github.com/vercel-labs/skills), into Claude Code, Codex, Cursor, and 70+ others. No doctrine, no reviewer agent, no hooks:

```
npx skills add ohm41321/luciazero
```

**Classic install.** The reference channel — the only one with the statusline, the `CLAUDE.md` import, a `--status` health check, and the Codex CLI installer. Details in the next sections:

```bash
npx luciazero               # Claude Code   (--with-hooks for the enforcement pack, --status)
npx luciazero codex         # Codex CLI     (npx luciazero uninstall-codex to remove)
```

`npx luciazero` is a thin wrapper with zero lifecycle scripts — nothing runs at npm install time (`test.sh` enforces that); it just launches the same audited bash installers you would get from `git clone https://github.com/ohm41321/luciazero.git && ./install.sh`. Pick **one** channel — plugin or classic — so the hooks are never wired twice. Want proof before installing anything? `./demo.sh` scaffolds a planted-bug repo you fix in your own session and score with an offline grader.

## After installing: which skill when

Nothing to memorize — the doctrine and the hooks work by themselves. Skills are for specific moments, and the first move in any repository is `/luciazero-bootstrap`, once, so a verify command exists for everything else to lean on. (Plugin installs prefix the names: `/luciazero:done`, `/luciazero:debug`, …)

| Moment | Skill | What it does |
|---|---|---|
| First time in a repository | `/luciazero-bootstrap` | Detects or creates the verify command, adds 3–6 smoke tests and a project notes file, proves the verify can actually go red |
| Before a risky or multi-step change | `/plan` | Bounds scope and defines observable acceptance evidence; pauses only when a material decision needs the user |
| A bug survives the first look | `/debug` | Deterministic reproduction, hypothesis ledger seeded from past lessons (`docs/lessons.md` + cross-repo heuristics), closes with a red-before-fix regression test |
| A regression has known good/bad revisions | `/bisect` | Finds the first bad commit in a detached temporary worktree without touching the caller's tree |
| About to say "done" | `/done` | Full-tier verify with the decisive line quoted, skeptic pass over the diff, `revert-probe.sh` test-honesty check, fixed report format |
| Sending unfinished work to another session/agent | `/lucia-relay` | Writes canonical `LUCIA_RELAY.json` + a generated human view, with evidence, repo fingerprint, negative knowledge, inspect/consume protocol |
| "Make it faster" requests | `/experiment` | Metric and win threshold before any edit, baseline with repetitions, one variable per run, losers reverted |
| Reviewing local verification habits | `/discipline-report` | Filters schema-versioned stop outcomes by time/project; text or JSON, with evidence-qualified recommendations |
| After a hard task or a long debug | `/retro` | Routes lessons into the project's notes, the `docs/lessons.md` ledger, and cross-repo heuristics; reads the discipline stats log |

`/done` routes risky diffs through the single `reviewer` in `security`, `contract`, or `general` focus. A diff crossing both security and public contracts gets two separate focused passes.

## What you get

Luciazero declares no third-party package dependencies. The CLI needs Node.js 18+; the enforcement pack and Relay helper use Python 3:

| Piece | Scope | Loaded |
|---|---|---|
| `claude/luciazero.md` | Doctrine — 9 rules | Always, every project, every session |
| `skills/luciazero-bootstrap/` | Procedure — make a repo agent-ready (ships `scripts/detect.sh`) | On demand |
| `skills/plan/` | Procedure — verification-first design and scope protocol | On demand |
| `skills/debug/` | Procedure — hypothesis-driven debugging | On demand |
| `skills/bisect/` | Procedure — safe first-bad-commit search (ships `scripts/safe-bisect.sh`) | On demand |
| `skills/done/` | Procedure — closeout ritual (ships `scripts/revert-probe.sh`) | On demand |
| `skills/lucia-relay/` | Procedure — portable, verifiable knowledge transfer (ships `scripts/relay.py`) | On demand |
| `skills/experiment/` | Procedure — measured-change protocol for perf work | On demand |
| `skills/discipline-report/` | Procedure — local stop-outcome analytics | On demand |
| `skills/retro/` | Procedure — harvest lessons into project notes | On demand |
| `claude/agents/reviewer.md` | Risk-routed adversarial reviewer | On demand (before "done") |
| `claude/hooks/` | Enforcement pack — verify-nudge hooks, opt-in strict gate, statusline | Opt-in |
| `eval/` | A/B harness — 6 planted-bug tasks, self-proving graders | Offline smoke is free; real runs use API credit or subscription quota |
| `demo.sh` | Two-minute demo — planted bug, your session, objective grader | Manual |

How it stacks up against superpowers, SuperClaude, proof-loop, and the harness built-ins — including what they do better: [docs/comparison.md](docs/comparison.md).

## Classic install & enforcement pack

`./install.sh` does four things: copies `claude/luciazero.md` → `~/.claude/luciazero.md`, the 9 cataloged skills → `~/.claude/skills/`, the cataloged reviewer → `~/.claude/agents/reviewer.md`, and appends `@luciazero.md` to `~/.claude/CLAUDE.md`. It keeps exact ownership snapshots in `.luciazero-managed/`: a colliding or subsequently customized skill/agent is backed up under hidden `.luciazero-backups/` before an update, and uninstall removes only an unchanged Luciazero-managed copy. It also backs up `CLAUDE.md` before touching it, is idempotent, and never writes outside `~/.claude/`. Those four steps are also the whole manual install.

### Enforcement pack (opt-in)

```bash
./install.sh --with-hooks    # requires python3
```

Wires two scripts into `~/.claude/settings.json` (backed up; merge is additive and idempotent): a **verify-nudge Stop hook** — if edits were made but no verify-ish command ran since the last edit, ending the session triggers the one-shot nudge above; fires once, never loops, fails open — and the **statusline** (left untouched if you have a custom one). The stop hook appends schema-v2 JSON lines (`stop-clean` / `nudge` / `strict-block`) to `luciazero-stats.log`: local only, capped at ~250 lines, fail-open, project identified by a 12-character hash rather than its path. Run `npx luciazero discipline --project .` for the report.

What counts as a verify run is a broad regex (test.sh, pytest, `npm test`, `cargo test`, …) — override with `LUCIAZERO_VERIFY_REGEX`, or better, set the repo's exact command with `LUCIAZERO_VERIFY_CMD` (e.g. in the repo's `.claude/settings.local.json` `env` block): in exact mode only commands that *are* or *start with* it count, so `cat test.sh` cannot flip the state green. Documentation and Relay artifacts do not re-arm the nudge after a final green verify. A `SessionStart` hook prints one pointer when `LUCIA_RELAY.json` exists (staleness warning past `LUCIAZERO_RELAY_STALE_DAYS`, default 7) — never its contents. Legacy `HANDOFF.md` gets a migration warning.

**Strict mode (opt-in on top of opt-in).** Set `LUCIAZERO_STRICT_VERIFY_CMD` to your repo's *fast* verify command — in your **personal** settings, never in anything committed. Honest limitation: the hook reads an environment variable and cannot tell which settings scope set it — a repo's committed `.claude/settings.json` `env` block would reach it too — so treat a repository that ships this variable as hostile and remove it before working there. At session stop the hook actually runs the command (unless the tracked state is already green after the last edit) and **blocks the stop** on red, quoting the failing output. Hard timeout via `LUCIAZERO_STRICT_TIMEOUT` (default 120s); every internal error — timeout, missing command, broken JSON — degrades to the ordinary nudge, never a block. A blocked stop's continuation is never re-blocked (`stop_hook_active`): a speed bump with evidence attached, not a wall.

### Verify, update, uninstall

`./install.sh --status` is a read-only health check: doctrine, skills, agent, import line, version, and — with the enforcement pack — that hook files are executable *and actually wired* (hooks fail open, so a broken install is otherwise silent). Non-zero exit if a core piece is missing. Update with `git pull && ./install.sh` (idempotent; a version sidecar lets `--status` flag an install older than the checkout). `./uninstall.sh` removes the scripts and cleans exactly our settings entries, matched by full path — run it from a checkout at least as new as the one you installed from.

### Codex CLI

`./install-codex.sh` (remove with `./uninstall-codex.sh`) — same content, single source of truth, converted at install time:

| Piece | Lands in Codex as |
|---|---|
| Doctrine | Marker-delimited block in `~/.codex/AGENTS.md` (replaced in place on reinstall) |
| All 9 skills | `~/.codex/skills/` — same `SKILL.md` format, copied as-is |
| `reviewer` agent | `~/.codex/skills/reviewer/` — installed as a portable skill in this channel |
| Enforcement pack | Not installed — Codex has no hooks or statusline |

Honors `CODEX_HOME`, backs up `AGENTS.md`, applies the same managed-snapshot and collision-backup policy as the classic installer, is idempotent, and writes nothing outside the Codex dir. The doctrine and skills are written platform-neutrally, so the same text works in both CLIs without translation.

## What the doctrine says

Nine rules in four groups. Full text in `claude/luciazero.md`.

**Ground truth** — done is proven by an exit code, and a run that did not happen is reported as exactly that; a missing verify command is the first bug; never weaken a check to reach green.

**Loop** — debugging starts with a hypothesis and the command that would refute it, not an edit, and the reproduction becomes a regression test; orient in an unfamiliar repo before editing — CI is the honest source of truth; smallest reversible step; review the final diff as a skeptic — risky diffs get an independent adversarial review.

**Memory** — never re-derive a dead end twice: write down what the code cannot say (null results, footguns) and read the project's notes before working in an area they cover.

**Autonomy** — stop and ask a clear, decidable question before high-stakes or irreversible moves (delete data, deploy, production, public contracts, money, scope changes); everything else proceeds, with unknowns batched into one sharp question; finish the whole scope, naming anything left out.

It is deliberately short, and `test.sh` enforces a word-count ceiling on it, because every line costs context on every turn of every session. Rules that merely restated what 2026 harnesses already enforce by default were removed; the CHANGELOG records each removal and the default it relies on.

## What the skills do

`/luciazero-bootstrap` walks a repository through six phases: **detect** (run `scripts/detect.sh`, then read CI — the source of truth), **establish the verify command** (non-zero on failure, unattended, offline, timed once), **smoke tests**, **guardrails**, **project notes**, and **prove it** (repeat green, deliberately break a covered line, confirm red, restore). A slow monorepo owns a native-graph `verify-changed` target with conservative full fallback; `/done` always uses `verify-full`. The global hook never guesses package impact from path prefixes.

`/plan` turns requirements into explicit scope, non-goals, affected contracts, and observable pass/fail evidence. It pauses only when ambiguity, high stakes, destructive work, a public-contract choice, or scope expansion requires a user decision; otherwise it plans concisely and proceeds.

`/debug` expands the hypothesis rule for bugs that resist the first look: reproduce deterministically, minimize, keep a visible hypothesis ledger (each entry names the command that would refute it), one variable per iteration, revert failed fixes, close with a regression test that is red before the fix and green after. The ledger seeds itself from recorded experience first — the repo's `docs/lessons.md` and the cross-repo `luciazero-heuristics.md` are grepped for the symptom before new hypotheses are invented; a match starts as H1, still verified.

`/bisect` runs the regression criterion in a detached temporary worktree, samples known-good and known-bad endpoints twice, preserves Git's exit-125 skip semantics, distinguishes a missing executable, and cleans up on every exit. Its output is a first bad commit—a root-cause hypothesis for `/debug`, not a causal verdict.

`/done` is the closeout ritual: full-tier verify with the decisive line quoted, a skeptic pass over the final diff, an independent adversarial review when the diff earns it, an explicit scope check naming anything left out, and a fixed report format. The test-honesty question — *would the new tests fail if the change were reverted?* — has a mechanical form: the bundled `scripts/revert-probe.sh` checks the old code into a throwaway git worktree, overlays only the changed test files, runs your verify command there, and inverts the result (exit 0/1/2 = bites/vacuous/unassessable).

`/lucia-relay` transfers unfinished work across sessions, agents, people, machines, and harnesses. `LUCIA_RELAY.json` is the canonical machine-readable manifest; `LUCIA_RELAY.md` is generated from it. The relay carries a repository fingerprint, exact verification evidence, literal next action, relevant files and lessons, refuted hypotheses, and landmines. The receiver inspects for drift, re-verifies against the tree, then explicitly consumes both transient artifacts.

`/experiment` is the measured-change protocol for "make it faster" work: metric and win threshold defined before touching code, baseline with repetitions, one variable per experiment, verdict recorded to `docs/experiments.md` — where a null result is worth as much as a win, and losers are reverted immediately.

`/discipline-report` (or `npx luciazero discipline`) summarizes local stop outcomes with time/project filters and JSON output. It reads both schema-v2 and legacy records, ignores malformed lines, and labels causal advice as `likely` when the log records only an outcome.

`/retro` closes the loop on *never re-derive a dead end twice*: after a hard task it filters the session for what **reading the code cannot tell a future agent** (null results, footguns, environment quirks), routes repo-true lessons into the project's notes and machine-local facts into the harness's memory (never committed), updates instead of duplicating, and deletes notes the session disproved. Three learning stores make this compound over time: debugged failures land in the repo's `docs/lessons.md` in a fixed greppable shape (symptom → cause → proven-by → fix) that `/debug` reads next time; lessons true in every repository go to `luciazero-heuristics.md` in the config dir (one line each, hard 100-line cap — an unbounded heuristics file would become the context tax this pack exists to prevent); and the enforcement pack's stats log turns recurring nudges into recorded behavioral lessons. Uninstall keeps all three — they are learned data. An empty retro is a valid retro — and knowledge stops evaporating when the session ends.

## The adversarial check: `reviewer` agent

An exit code cannot catch *passes-the-tests-but-wrong*. For risky diffs `/done` routes the single read-only reviewer into `security`, `contract`, or `general` focus. It reads callers and consumers, uses `blocker` / `major` / `minor` consistently, runs on the authoring model (`model: inherit`) in Claude, and reports `No findings.` rather than inventing some. Security and contract risk together get separate focused passes.

## Design notes

**Why a file, not a hook.** Hooks enforce mechanical, deterministic things; doctrine is judgment, and judgment belongs in context. Claude Code already re-injects `CLAUDE.md` after compaction — the real anti-drift lever is keeping the doctrine small, which `test.sh` enforces.

**Why the doctrine and the skills are separate.** The doctrine must be cheap enough to carry on every turn; the procedures are long and moment-specific, so they load on demand. Merging them would make you pay for the procedures constantly.

**How the plugin squares with this.** Plugins have no way to import a file into `CLAUDE.md`, so the plugin channel delivers the doctrine as `SessionStart` context — acceptable only because the text is word-ceiling-capped, and guarded so it stays silent when a classic install already imports it. The classic installer remains the reference channel; the plugin trades the statusline and `--status` for one-command install and marketplace updates.

**Project settings stay in the project.** `examples/project-settings.example.json` shows the per-repo shape — a permission allowlist so the verify loop is not interrupted, and an inert check-suppression guard that mechanizes "never weaken a check to reach green". Copy into a repo's `.claude/settings.json`; do not put project commands in global settings.

**Agentic CI stays a diagnosis loop.** `examples/luciazero-ci.example.yml` (inert, REPLACE-ME-gated) posts an agent's root-cause diagnosis on a PR when CI fails. It cannot push or edit code (`contents: read`, no Bash in the allowlist, no credentials); its one write scope posts the size-capped diagnosis comment. It never auto-fixes: an agent patching CI blind ships plausible-but-wrong fixes.

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia-laptop.png" width="240" alt="Lucia grinding through the eval harness on her laptop">
</p>

**The setup measures itself.** `eval/` is a small A/B harness: the same planted-bug tasks run with and without the doctrine installed, graded offline by behavioral criteria. Six tasks, each probing a different rule — slugify (regression-test discipline), red-suite (bending tests toward a bug), flaky-report (making an intermittent failure deterministic), pipeline (root-cause vs symptom patch, graded by diff locality), merge-conflict (a botched merge where neither side's feature may be silently dropped), false-green (a suite that is green from the start while the bug lives outside its coverage — the false-done trap). `--with-lessons` adds a third arm that pre-seeds the task's `docs/lessons.md`, measuring whether the learning layer pays; results also record per-run duration, tokens, and cost. CI proves every grader three ways on every push: `reference/` passes, unfixed `project/` fails, and the checked-in `gamed/` cheat trees are rejected. `eval/run.sh --runs N` + `eval/report.sh` produce per-criterion pass-rate tables; see `eval/README.md`, including its honesty box about small n.

**Latest results (2026-08-11).** Six tasks, doctrine vs bare (+ lessons on the two tasks that ship a ledger), two models — all-criteria pass rates, n = valid runs per arm:

| model | doctrine | bare | Δ | lessons |
|---|---|---|---|---|
| **haiku** · n=10 | **36/60 (60%)** | **27/60 (45%)** | **+15pp** | 8/20 (40%) |
| **sonnet** · n=5 | **28/30 (93%)** | **17/30 (56%)** | **+37pp** | 10/10 (100%) |

Per task, ordered by the sonnet delta. Every bar is one arm scaled to 10 cells — filled = runs where every criterion passed:

**sonnet · n=5 per arm**

| task | doctrine | bare | Δ | lessons |
|---|---|---|---|---|
| slugify | `██████████` 5/5 | `··········` 0/5 | **+100pp** | – |
| merge-conflict | `██████····` 3/5 | `··········` 0/5 | **+60pp** | – |
| pipeline | `██████████` 5/5 | `██████····` 3/5 | **+40pp** | `██████████` 5/5 |
| false-green | `██████████` 5/5 | `████████··` 4/5 | **+20pp** | `██████████` 5/5 |
| flaky-report | `██████████` 5/5 | `██████████` 5/5 | +0pp | – |
| red-suite | `██████████` 5/5 | `██████████` 5/5 | +0pp | – |
| **total** | **28/30 (93%)** | **17/30 (56%)** | **+37pp** | **10/10 (100%)** |

**haiku · n=10 per arm**

| task | doctrine | bare | Δ | lessons |
|---|---|---|---|---|
| slugify | `███·······` 3/10 | `··········` 0/10 | **+30pp** | – |
| merge-conflict | `█·········` 1/10 | `··········` 0/10 | **+10pp** | – |
| pipeline | `████······` 4/10 | `··········` 0/10 | **+40pp** | `█·········` 1/10 |
| false-green | `████████··` 8/10 | `███████···` 7/10 | **+10pp** | `███████···` 7/10 |
| flaky-report | `██████████` 10/10 | `██████████` 10/10 | +0pp | – |
| red-suite | `██████████` 10/10 | `██████████` 10/10 | +0pp | – |
| **total** | **36/60 (60%)** | **27/60 (45%)** | **+15pp** | **8/20 (40%)** |

Haiku ran 10 rounds with zero infrastructure failures. Sonnet ran 5 rounds; in round 5 the OAuth session expired mid-run, so eight arms (merge-conflict/bare, pipeline all arms, red-suite both, slugify both) came back INVALID. They were re-run to completion after re-authenticating, so every sonnet arm is now at n=5 with no invalid rows left. Those eight top-up runs executed on Windows/Git Bash against the same commit — same tasks, same graders, different OS from the other 62 rows. Sonnet rows report modelUsage as claude-sonnet-5 plus claude-haiku-4-5 (subtasks run on haiku). Opus has not been measured yet — a third model block is planned. Δ is doctrine − bare pass-rate, floored. Regenerate anytime with `eval/report.sh results-haiku.jsonl` / `eval/report.sh results-sonnet.jsonl`; the honesty box in `eval/README.md` applies — n is tiny, compare rates, never single runs.

## Safety

Hooks execute commands on your machine automatically. The example settings file is inert by design — every hook in it is commented out and must be edited before it does anything. Read any hook before enabling it, and do not enable one that pushes, deploys, deletes, or writes outside the repository.

## Development

`./test.sh` is this repo's own verify command — the doctrine says a missing verify command is the first bug, so the repo passes its own rule. It covers shell syntax + shellcheck, the hook state machine (strict gate included), plugin + npm manifests, every eval grader proven red *and* green *and* anti-cheat, `revert-probe.sh` in throwaway git fixtures, `demo.sh`, and full install → reinstall → uninstall cycles for both harnesses in sandbox config dirs — never your real `~/.claude/` or `~/.codex/`. CI runs it on every push; tagging `vX.Y.Z` publishes a GitHub Release. See `CONTRIBUTING.md` and [docs/publishing.md](docs/publishing.md).

```
$ ./test.sh
PASS  all checks green
```

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia-cheer.png" width="240" alt="Lucia celebrating — all checks green">
</p>

## Lucia family & support

Luciazero shares its mascot with [Lucia](https://lucia-discord-bot.vercel.app) — a Thai-language Discord bot with AI chat, music playback, mini-games, and a gacha card collection.

If Luciazero saves you review cycles, you can [support the project here](https://easydonate.app/itsathitz) 💚

## License

[MIT](LICENSE)

## ภาษาไทย

README ฉบับภาษาไทยเต็ม: [README.th.md](README.th.md)

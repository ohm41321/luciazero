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

Everything in this repo — a 9-rule doctrine, six skills, an adversarial reviewer agent, enforcement hooks, an eval harness — exists to make that rule hold without a human in the loop.

## Install

**Claude Code — plugin (recommended).** One install carries the six skills, the `reviewer` agent, the verify-tracking hooks, and the doctrine:

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
npx luciazero codex         # Codex CLI     (npx luciazero uninstall to remove)
```

`npx luciazero` is a thin wrapper with zero lifecycle scripts — nothing runs at npm install time (`test.sh` enforces that); it just launches the same audited bash installers you would get from `git clone https://github.com/ohm41321/luciazero.git && ./install.sh`. Pick **one** channel — plugin or classic — so the hooks are never wired twice. Want proof before installing anything? `./demo.sh` scaffolds a planted-bug repo you fix in your own session and score with an offline grader.

## After installing: which skill when

Nothing to memorize — the doctrine and the hooks work by themselves. Skills are for specific moments, and the first move in any repository is `/luciazero-bootstrap`, once, so a verify command exists for everything else to lean on. (Plugin installs prefix the names: `/luciazero:done`, `/luciazero:debug`, …)

| Moment | Skill | What it does |
|---|---|---|
| First time in a repository | `/luciazero-bootstrap` | Detects or creates the verify command, adds 3–6 smoke tests and a project notes file, proves the verify can actually go red |
| A bug survives the first look | `/debug` | Deterministic reproduction, hypothesis ledger seeded from past lessons (`docs/lessons.md` + cross-repo heuristics), closes with a red-before-fix regression test |
| About to say "done" | `/done` | Full-tier verify with the decisive line quoted, skeptic pass over the diff, `revert-probe.sh` test-honesty check, fixed report format |
| Stopping while work is unfinished | `/handoff` | Writes the `HANDOFF.md` capsule: goal, verified state, the one literal next command |
| "Make it faster" requests | `/experiment` | Metric and win threshold before any edit, baseline with repetitions, one variable per run, losers reverted |
| After a hard task or a long debug | `/retro` | Routes lessons into the project's notes, the `docs/lessons.md` ledger, and cross-repo heuristics; reads the discipline stats log |

The `reviewer` agent is never invoked by name — `/done` spawns it when a diff is risky enough, or ask for "an adversarial review" at any point.

## What you get

No dependencies, no runtime (python3 only for the opt-in enforcement pack):

| Piece | Scope | Loaded |
|---|---|---|
| `claude/luciazero.md` | Doctrine — 9 rules | Always, every project, every session |
| `skills/luciazero-bootstrap/` | Procedure — make a repo agent-ready (ships `scripts/detect.sh`) | On demand |
| `skills/debug/` | Procedure — hypothesis-driven debugging | On demand |
| `skills/done/` | Procedure — closeout ritual (ships `scripts/revert-probe.sh`) | On demand |
| `skills/handoff/` | Procedure — state capsule for the next session/agent | On demand |
| `skills/experiment/` | Procedure — measured-change protocol for perf work | On demand |
| `skills/retro/` | Procedure — harvest lessons into project notes | On demand |
| `claude/agents/reviewer.md` | Adversarial reviewer subagent | On demand (before "done") |
| `claude/hooks/` | Enforcement pack — verify-nudge hooks, opt-in strict gate, statusline | Opt-in |
| `eval/` | A/B harness — 5 planted-bug tasks, self-proving graders | Manual (costs API money) |
| `demo.sh` | Two-minute demo — planted bug, your session, objective grader | Manual |

How it stacks up against superpowers, SuperClaude, proof-loop, and the harness built-ins — including what they do better: [docs/comparison.md](docs/comparison.md).

## What it looks like

Actual output of the shipped scripts, not mockups. The statusline keeps the verify state on screen:

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

## Classic install & enforcement pack

`./install.sh` does four things: copies `claude/luciazero.md` → `~/.claude/luciazero.md`, the six skills → `~/.claude/skills/`, the reviewer agent → `~/.claude/agents/reviewer.md` (backing up a customized copy first), and appends `@luciazero.md` to `~/.claude/CLAUDE.md`. It backs up `CLAUDE.md` before touching it, is idempotent, and never writes outside `~/.claude/`. Those four steps are also the whole manual install.

### Enforcement pack (opt-in)

```bash
./install.sh --with-hooks    # requires python3
```

Wires two scripts into `~/.claude/settings.json` (backed up; merge is additive and idempotent): a **verify-nudge Stop hook** — if edits were made but no verify-ish command ran since the last edit, ending the session triggers the one-shot nudge above; fires once, never loops, fails open — and the **statusline** (left untouched if you have a custom one). The stop hook also appends one line per stop outcome (`stop-clean` / `nudge` / `strict-block`) to `luciazero-stats.log` in the config dir — local only, capped at ~250 lines, fail-open — which `/retro` reads to turn recurring discipline gaps into recorded lessons.

What counts as a verify run is a broad regex (test.sh, pytest, `npm test`, `cargo test`, …) — override with `LUCIAZERO_VERIFY_REGEX`, or better, set the repo's exact command with `LUCIAZERO_VERIFY_CMD` (e.g. in the repo's `.claude/settings.local.json` `env` block): in exact mode only commands that *are* or *start with* it count, so `cat test.sh` cannot flip the state green. Documentation writes (`*.md` and friends — `LUCIAZERO_DOC_REGEX`) do not re-arm the nudge, because the closeout skills all write notes *after* the final green verify. A `SessionStart` hook prints a one-line pointer when the project has a `HANDOFF.md` capsule (staleness warning past `LUCIAZERO_HANDOFF_STALE_DAYS`, default 7) — the pointer only, never the contents.

**Strict mode (opt-in on top of opt-in).** Set `LUCIAZERO_STRICT_VERIFY_CMD` to your repo's *fast* verify command — in your **personal** settings, never in anything committed. Honest limitation: the hook reads an environment variable and cannot tell which settings scope set it — a repo's committed `.claude/settings.json` `env` block would reach it too — so treat a repository that ships this variable as hostile and remove it before working there. At session stop the hook actually runs the command (unless the tracked state is already green after the last edit) and **blocks the stop** on red, quoting the failing output. Hard timeout via `LUCIAZERO_STRICT_TIMEOUT` (default 120s); every internal error — timeout, missing command, broken JSON — degrades to the ordinary nudge, never a block. A blocked stop's continuation is never re-blocked (`stop_hook_active`): a speed bump with evidence attached, not a wall.

### Verify, update, uninstall

`./install.sh --status` is a read-only health check: doctrine, skills, agent, import line, version, and — with the enforcement pack — that hook files are executable *and actually wired* (hooks fail open, so a broken install is otherwise silent). Non-zero exit if a core piece is missing. Update with `git pull && ./install.sh` (idempotent; a version sidecar lets `--status` flag an install older than the checkout). `./uninstall.sh` removes the scripts and cleans exactly our settings entries, matched by full path — run it from a checkout at least as new as the one you installed from.

### Codex CLI

`./install-codex.sh` (remove with `./uninstall-codex.sh`) — same content, single source of truth, converted at install time:

| Piece | Lands in Codex as |
|---|---|
| Doctrine | Marker-delimited block in `~/.codex/AGENTS.md` (replaced in place on reinstall) |
| All six skills | `~/.codex/skills/` — same `SKILL.md` format, copied as-is |
| `reviewer` agent | `~/.codex/skills/reviewer/` — Codex has no subagents, so it ships as a skill |
| Enforcement pack | Not installed — Codex has no hooks or statusline |

Honors `CODEX_HOME`, backs up `AGENTS.md`, idempotent, writes nothing outside the Codex dir. The doctrine and skills are written platform-neutrally, so the same text works in both CLIs without translation.

## What the doctrine says

Nine rules in four groups. Full text in `claude/luciazero.md`.

**Ground truth** — done is proven by an exit code, and a run that did not happen is reported as exactly that; a missing verify command is the first bug; never weaken a check to reach green.

**Loop** — debugging starts with a hypothesis and the command that would refute it, not an edit, and the reproduction becomes a regression test; orient in an unfamiliar repo before editing — CI is the honest source of truth; smallest reversible step; review the final diff as a skeptic — risky diffs get an independent adversarial review.

**Memory** — never re-derive a dead end twice: write down what the code cannot say (null results, footguns) and read the project's notes before working in an area they cover.

**Autonomy** — stop and ask a clear, decidable question before high-stakes or irreversible moves (delete data, deploy, production, public contracts, money, scope changes); everything else proceeds, with unknowns batched into one sharp question; finish the whole scope, naming anything left out.

It is deliberately short, and `test.sh` enforces a word-count ceiling on it, because every line costs context on every turn of every session. Rules that merely restated what 2026 harnesses already enforce by default were removed; the CHANGELOG records each removal and the default it relies on.

## What the skills do

`/luciazero-bootstrap` walks a repository through six phases: **detect** (run the bundled `scripts/detect.sh` evidence scan, then read the CI config — CI is the source of truth; the script surfaces candidates, the agent decides), **establish the verify command** (use the existing one or create the smallest real one: non-zero on failure, unattended, offline, *timed once* — the measurement decides one tier or two; monorepos scope the fast tier), **smoke tests** (3–6 that catch catastrophic breakage — not coverage, and it says so), **guardrails** (only hooks that pay for themselves; on Codex, encoded as `AGENTS.md` instructions), **project notes** (only what reading the code cannot tell you), and **prove it** (run the fast tier twice — a green that does not repeat is a flake; break a covered line, confirm red, restore). Language-agnostic throughout: it detects, it does not assume.

`/debug` expands the hypothesis rule for bugs that resist the first look: reproduce deterministically, minimize, keep a visible hypothesis ledger (each entry names the command that would refute it), one variable per iteration, revert failed fixes, close with a regression test that is red before the fix and green after. The ledger seeds itself from recorded experience first — the repo's `docs/lessons.md` and the cross-repo `luciazero-heuristics.md` are grepped for the symptom before new hypotheses are invented; a match starts as H1, still verified.

`/done` is the closeout ritual: full-tier verify with the decisive line quoted, a skeptic pass over the final diff, an independent adversarial review when the diff earns it, an explicit scope check naming anything left out, and a fixed report format. The test-honesty question — *would the new tests fail if the change were reverted?* — has a mechanical form: the bundled `scripts/revert-probe.sh` checks the old code into a throwaway git worktree, overlays only the changed test files, runs your verify command there, and inverts the result (exit 0/1/2 = bites/vacuous/unassessable).

`/handoff` writes a state capsule (`HANDOFF.md`) when a session ends mid-task: goal, verified state, the one literal next command, open and refuted hypotheses, landmines. The next session — or the other harness — reads it, re-verifies against the tree, and deletes it.

`/experiment` is the measured-change protocol for "make it faster" work: metric and win threshold defined before touching code, baseline with repetitions, one variable per experiment, verdict recorded to `docs/experiments.md` — where a null result is worth as much as a win, and losers are reverted immediately.

`/retro` closes the loop on *never re-derive a dead end twice*: after a hard task it filters the session for what **reading the code cannot tell a future agent** (null results, footguns, environment quirks), routes repo-true lessons into the project's notes and machine-local facts into the harness's memory (never committed), updates instead of duplicating, and deletes notes the session disproved. Three learning stores make this compound over time: debugged failures land in the repo's `docs/lessons.md` in a fixed greppable shape (symptom → cause → proven-by → fix) that `/debug` reads next time; lessons true in every repository go to `luciazero-heuristics.md` in the config dir (one line each, hard 100-line cap — an unbounded heuristics file would become the context tax this pack exists to prevent); and the enforcement pack's stats log turns recurring nudges into recorded behavioral lessons. Uninstall keeps all three — they are learned data. An empty retro is a valid retro — and knowledge stops evaporating when the session ends.

## The adversarial check: `reviewer` agent

An exit code cannot catch *passes-the-tests-but-wrong*. For risky diffs the doctrine wants an independent adversarial review: on Claude Code the built-in `/code-review` is the stronger tool when available; the shipped `reviewer` agent is the portable fallback and the only reviewer on Codex. Read-only, instructed to **refute** the change, runs on the same model as the main thread (`model: inherit`), and reports `No findings.` rather than inventing some.

## Design notes

**Why a file, not a hook.** Hooks enforce mechanical, deterministic things; doctrine is judgment, and judgment belongs in context. Claude Code already re-injects `CLAUDE.md` after compaction — the real anti-drift lever is keeping the doctrine small, which `test.sh` enforces.

**Why the doctrine and the skills are separate.** The doctrine must be cheap enough to carry on every turn; the procedures are long and moment-specific, so they load on demand. Merging them would make you pay for the procedures constantly.

**How the plugin squares with this.** Plugins have no way to import a file into `CLAUDE.md`, so the plugin channel delivers the doctrine as `SessionStart` context — acceptable only because the text is word-ceiling-capped, and guarded so it stays silent when a classic install already imports it. The classic installer remains the reference channel; the plugin trades the statusline and `--status` for one-command install and marketplace updates.

**Project settings stay in the project.** `examples/project-settings.example.json` shows the per-repo shape — a permission allowlist so the verify loop is not interrupted, and an inert check-suppression guard that mechanizes "never weaken a check to reach green". Copy into a repo's `.claude/settings.json`; do not put project commands in global settings.

**Agentic CI stays a diagnosis loop.** `examples/luciazero-ci.example.yml` (inert, REPLACE-ME-gated) posts an agent's root-cause diagnosis on a PR when CI fails. It cannot push or edit code (`contents: read`, no Bash in the allowlist, no credentials); its one write scope posts the size-capped diagnosis comment. It never auto-fixes: an agent patching CI blind ships plausible-but-wrong fixes.

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia-laptop.png" width="240" alt="Lucia grinding through the eval harness on her laptop">
</p>

**The setup measures itself.** `eval/` is a small A/B harness: the same planted-bug tasks run with and without the doctrine installed, graded offline by behavioral criteria. Five tasks, each probing a different rule — slugify (regression-test discipline), red-suite (bending tests toward a bug), flaky-report (making an intermittent failure deterministic), pipeline (root-cause vs symptom patch, graded by diff locality), merge-conflict (a botched merge where neither side's feature may be silently dropped). CI proves every grader three ways on every push: `reference/` passes, unfixed `project/` fails, and the checked-in `gamed/` cheat trees are rejected. `eval/run.sh --runs N` + `eval/report.sh` produce per-criterion pass-rate tables; see `eval/README.md`, including its honesty box about small n.

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

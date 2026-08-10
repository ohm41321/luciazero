# Changelog

All notable changes to this project are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.5.0] - 2026-08-10

First version published to npm (`luciazero`); 1.4.x and below were
development versions.

### Added

- **Learning layer** — the pack now compounds experience across sessions,
  three stores, all mechanized and all pruned:
  - `/retro` records debugged failures to a per-repo lesson ledger
    (`docs/lessons.md`, fixed greppable shape: symptom → cause → proven-by →
    fix) and repo-independent lessons to `luciazero-heuristics.md` in the
    harness config dir (one line each, hard 100-line cap); stale entries are
    corrected or deleted, since a wrong lesson mis-seeds every future debug.
  - `/debug` seeds its hypothesis ledger from both files before inventing
    hypotheses — a match becomes H1 but is still verified.
  - The stop hook appends one line per stop outcome (`stop-clean` / `nudge` /
    `strict-block`) to `luciazero-stats.log` in the config dir — local only,
    fail-open, rotated at 500→250 lines — and `/retro` reads it to turn
    recurring discipline gaps into recorded lessons. This is the one
    documented exception to "state never leaves $TMPDIR"; the hook header
    says so.
  - Both uninstallers keep (and mention) the learned-data files.
  - test.sh: stats logging proven for all three outcomes + rotation +
    uninstall survival, learning-layer wiring greps on both skills, and the
    whole run now exports a sandbox `CLAUDE_CONFIG_DIR` so no test can ever
    write to the real `~/.claude`. New checks red-proven by mutation.

## [1.4.1] - 2026-08-10

### Added

- **Trusted publishing (OIDC)**: `release.yml` gained an `npm-publish` job —
  every `v*` tag now publishes to npm from GitHub Actions with provenance
  attestations and no token anywhere. Guards: the tag must equal the
  `package.json` version, and already-live versions are skipped so re-runs
  cannot fail. This release exists to exercise that pipeline end to end.

### Fixed

- The README shipped inside the npm tarball no longer carries the
  "npm publish is in flight" sentence that 1.4.0 froze in.

## [1.4.0] - 2026-08-10

### Changed

- **Project renamed to Luciazero** (from "agentic-engineering"). Every brand
  identifier moved with it: doctrine file `claude/luciazero.md` (imported as
  `@luciazero.md`), hooks `luciazero-verify.sh` / `luciazero-statusline.sh`,
  skill `/luciazero-bootstrap`, env vars `LUCIAZERO_*` (was `AGENTIC_*`),
  version sidecars `.luciazero-version`, CI example
  `examples/luciazero-ci.example.yml`, hook state dir `luciazero-verify-state`,
  and the settings-cleanup matchers in both uninstallers. Nothing was
  published under the old name, so there is no migration path to keep.
  Prose still uses "agentic engineer(ing)" where it names the discipline,
  not the project.
- **Skills moved to the repo root** (`skills/`, was `claude/skills/`) so
  `npx skills add <owner>/luciazero` (vercel-labs/skills) discovers them with
  zero registration. Installers, tests, and docs all read the new path.

### Added

- **Claude Code plugin packaging**: `.claude-plugin/plugin.json` +
  `.claude-plugin/marketplace.json` make the repo installable as a plugin
  from its own single-plugin marketplace (`/plugin marketplace add
  <owner>/luciazero` → `/plugin install luciazero@luciazero`); `claude plugin
  validate` passes. `claude/hooks/hooks.json` wires the verify hooks via
  `${CLAUDE_PLUGIN_ROOT}`, and a new `doctrine` subcommand of
  `luciazero-verify.sh` loads the doctrine as SessionStart context — plugins
  cannot add a CLAUDE.md import line — with a guard that stays silent when a
  classic install exists, so the doctrine never loads twice. Honest limits
  documented: no statusline via plugins; pick one channel so hooks are not
  wired twice.
- **npm wrapper** (`package.json` + `bin/luciazero.js`): `npx luciazero`
  routes to the bundled installers (`codex`, `uninstall`, `uninstall-codex`
  subcommands; flags pass through). No lifecycle scripts, ever — test.sh
  fails if one appears, matching npm v12's default block.
- **Lucia mascot** in both READMEs, cropped from the project's character
  sheet (`docs/assets/lucia*.png`): plushie-hug under the title, laptop pose
  at the eval paragraph, and the fist-up pose celebrating
  `PASS  all checks green` in Development.
- **README rewrite (both languages)**: install-channels-first — plugin
  (recommended) and `npx skills add` lead, classic `git clone` demoted to the
  reference channel; sections condensed; the stale "Why not a Claude Code
  plugin" design note replaced with "How the plugin squares with this"; new
  "Lucia family & support" section (Lucia Discord bot + donate link).
  A 2-lens verification pass (bilingual fidelity + truth-to-code) confirmed
  the new claims and caught 4 wording issues, all fixed.
- **docs/publishing.md**: dependency-ordered release checklist (GitHub →
  plugin directory submission → npm trusted publishing → awesome-claude-code),
  with the channel-honesty note that only the classic installer carries the
  statusline and CLAUDE.md import.
- test.sh grew five gates for the above: manifest validity + version sync
  across CHANGELOG/plugin.json/package.json, doctrine-mode behavior (emits
  once, never twice), npm payload completeness + lifecycle-script ban
  (with a live `--status` routing probe when node is present), the plugin
  channel dedupe, and the installers' unknown-option rejection. All five
  proven red by mutation before being trusted.

### Fixed (post-review of the rename/packaging wave; 11 confirmed findings)

- `install-codex.sh`, `uninstall.sh`, and `uninstall-codex.sh` now reject
  unknown options — previously `npx luciazero codex --status` silently
  performed a FULL install instead of a status check, and stray flags to the
  uninstallers were swallowed.
- Plugin doctrine mode no longer needs python3 or stdin: it is handled before
  the script's shared setup, so machines without python3 (where every other
  mode fails open to doing nothing) still load the doctrine. It also survives
  an unset `HOME` (was an `set -u` abort violating the fail-open contract).
- Running any hook mode by hand from a terminal no longer hangs waiting for
  stdin EOF.
- Plugin + `install.sh --with-hooks` double-install: the plugin's hooks.json
  now invokes every mode with `LUCIAZERO_CHANNEL=plugin`, and the hook stands
  down when classic wiring exists in settings.json — the stop nudge can no
  longer double-fire, and a strict verify command can no longer run twice
  concurrently against the same repo.
- The debug and bootstrap skills no longer hardcode classic-install paths
  (`~/.claude/...`) that do not exist under the plugin / `npx skills`
  channels.
- Release procedure docs caught up with the version-sync gate: CONTRIBUTING's
  Releasing step and docs/publishing.md now both say to bump plugin.json +
  package.json together with the CHANGELOG heading (following the old steps
  verbatim would have produced a red release workflow), and publishing.md no
  longer hardcodes tagging the already-released v1.3.0.
- docs/comparison.md no longer lists "plugin marketplace" as something
  superpowers has and we don't (this repo is now its own single-plugin
  marketplace; theirs remains a multi-plugin ecosystem).

- **Strict verify gate** (opt-in on top of the opt-in enforcement pack): set
  `LUCIAZERO_STRICT_VERIFY_CMD` in your *personal* settings and the Stop hook
  actually runs that command (fast-pathing when the tracked state is already
  green after the last edit) and blocks a red stop with the failing output
  quoted. Hard timeout (`LUCIAZERO_STRICT_TIMEOUT`, default 120s); every
  internal error degrades to the ordinary fail-open nudge. The variable
  belongs in personal settings only; the hook cannot verify which settings
  scope set it (a committed `.claude/settings.json` env block reaches it
  too), and the docs say so plainly — never commit it, and treat a repo
  that ships it as hostile. Documented honestly as a speed bump, not a
  wall: a blocked stop's continuation is never re-blocked.
- **Exact-match verify tracking**: `LUCIAZERO_VERIFY_CMD` switches the Bash
  tracker from the broad regex to prefix matching, closing a real
  false-green — `cat test.sh` or `grep pytest README` no longer count as a
  verify run. `/luciazero-bootstrap` Phase 2 now offers (ask-first) to record
  the established command in the repo's `.claude/settings.local.json`.
- **SessionStart handoff pointer**: a `session` hook subcommand emits one
  context line when the project has a `HANDOFF.md` capsule — age included,
  stale warning past `LUCIAZERO_HANDOFF_STALE_DAYS` (default 7), silent and
  zero-cost when there is none, pointer only (never the contents).
- **`revert-probe.sh`** (ships inside the done skill, works on both
  harnesses): the mechanical form of "would the new tests fail if the change
  were reverted?" — checks the pre-change code into a throwaway git
  worktree, overlays only the changed test files, runs the verify command
  there and inverts the result. Exit 0 tests bite / 1 vacuous or no test
  changes / 2 unassessable; never touches the caller's tree. `/done` and
  `/debug` reference it.
- **Three new eval tasks**, each probing a different doctrine rule:
  `red-suite` (correct-but-red suite; the lazy fix is bending the tests to
  the bug — caught by replaying the fixture's pristine tests against the
  worked code), `flaky-report` (hash-seed-dependent output; graded
  deterministically via a `PYTHONHASHSEED` 0–9 sweep), `pipeline` (bug in
  the parser, symptom two modules away; graded by diff *locality* — the
  untouched modules must stay AST-identical).
- **`gamed*/` cheat fixtures + grader auto-discovery**: every task now ships
  one or more hand-built cheat trees its grader must reject — including
  hardcoded-lookup (`red-suite/gamed-hardcode/`) and hardcoded-output
  (`flaky-report/gamed-hardcode/`) variants killed by unseen-data criteria —
  and `test.sh` auto-discovers `eval/tasks/*/` so no task can ship without
  proving its grader goes red, green, and anti-gamed (a missing `gamed/` is
  itself a red build) and speaks the new machine-readable
  `CRIT <id> pass|fail` / `SCORE n/m` output contract.
- **`eval/run.sh --runs N --out results.jsonl` + `eval/report.sh`**: repeat
  runs, record per-criterion results as JSONL, and render the doctrine-vs-
  bare pass-*rate* table the honesty box has always prescribed — with n and
  a low-n warning printed unconditionally. `report.sh` is byte-compared
  against a frozen fixture in CI and rejects malformed input.
- **`install.sh --status`**: read-only health check of an existing install —
  every piece listed, hook wiring verified in `settings.json` (the hooks
  fail open, so a broken install was previously silent), version compared,
  non-zero exit when a core piece is missing. Plus a version sidecar
  (`.luciazero-version`, both harnesses) and a documented update
  path in the README.
- **`demo.sh`**: scaffolds the slugify planted-bug fixture into a throwaway
  git repo, prints the bug report and the exact commands — fix it in your
  own Claude session, then score the tree with the offline grader. Never
  invokes `claude` itself; refuses to scaffold inside the repo.
- **`docs/comparison.md`**: dated, sourced, deliberately two-sided
  comparison against superpowers, SuperClaude, proof-loop, orchestrator
  runtimes, template catalogs, and the harness built-ins.
- README: 60-second quickstart, a "What it looks like" section showing the
  actual statusline/nudge/strict-gate output (captured, not composed), and
  an Updating section.
- **`README.th.md`** — full Thai translation of the README, replacing the
  abridged Thai section; English stays the default, both files cross-link,
  and `test.sh` trips when the section structures drift apart.

- `/done` skill — closeout ritual before declaring a non-trivial task
  complete: full-tier verify with the decisive line quoted, a skeptic pass
  over the final diff, an independent adversarial review when the diff
  earns it, an explicit scope check naming anything left out, and a fixed
  report format. Doctrine rule 1 now points to it.
- `/handoff` skill — transient state capsule (`HANDOFF.md`) for resuming
  unfinished work across sessions, machines, or harnesses: goal, verified
  state, one literal next command, open and refuted hypotheses, landmines.
  Consumed and deleted by the reader; `/retro` stays the home of permanent
  lessons.
- `/experiment` skill — measured-change protocol for optimization work:
  metric and win threshold defined before any change, multi-run baseline,
  one variable per experiment, verdicts (including null results) recorded
  to `docs/experiments.md`, losers reverted immediately.
- Enforcement pack (`./install.sh --with-hooks`, Claude Code only,
  requires python3): a verify-tracking hook pair plus statusline —
  PostToolUse hooks record edits and verify-ish Bash runs per project, a
  Stop hook nudges once (fails open, never loops) when a session ends
  with unverified edits, and the statusline shows `model | branch |
  ✅ verify 3m` / `❌ verify RED` / `✎ unverified` at a glance. The
  settings.json merge is additive, idempotent, backed up, respects an
  existing custom statusLine, and `uninstall.sh` removes exactly our
  entries while preserving everything else.
- `examples/luciazero-ci.example.yml` — inert, REPLACE-ME-gated GitHub
  Actions template: on CI failure, an agent diagnoses the root cause from
  the failing logs (hypothesis + evidence line, logs treated as untrusted
  input) and posts a size-capped PR comment. Diagnosis only — it cannot
  push or edit code (`contents: read`, tool allowlist without Bash,
  `persist-credentials: false`); its single write scope is
  `pull-requests: write` for the comment. Fork-guarded secrets, no
  auto-fix.
- `eval/` — A/B harness measuring whether the doctrine changes agent
  behavior: planted-bug task fixtures graded offline by behavioral
  criteria (bug actually fixed, a regression test that goes red when the
  buggy implementation is restored, no weakened checks). `eval/run.sh`
  runs both arms (doctrine vs bare config) and costs API money, so it is
  manual; `test.sh` verifies the graders themselves can go both red and
  green, offline.
- `test.sh` now also exercises the enforcement-pack hook state machine,
  the `--with-hooks` install/uninstall cycle against a settings.json with
  pre-existing user content, the eval graders' red/green behavior, and the
  inertness of the luciazero-ci example.

- `/debug` skill — hypothesis-driven debugging procedure, the on-demand
  expansion of the doctrine's hypothesis rule: deterministic reproduction
  first, minimized repro, a visible hypothesis ledger (run the refuting
  observation, not the edit), one variable per iteration with failed fixes
  reverted, close-out via a regression test red before the fix and green
  after. Installed by both harness installers.
- `luciazero-bootstrap` now bundles `scripts/detect.sh` — a read-only,
  dependency-free evidence scan (bash plus standard tools; python3 to
  parse `package.json` when available, `sed` fallback) covering docs,
  manifests, script/target names, CI `run:` lines, test dirs, monorepo
  markers, and git status, replacing a dozen manual reads in Phase 1. It surfaces candidates only; the agent still decides.
  Ships to both harnesses via the existing skill copy.
- Bootstrap Phase 2 hardening: verify must run unattended (no watch or
  interactive modes), the suite is timed once so the measurement (not a
  guess) decides one tier or two, fast-tier output should be near-silent,
  and monorepos scope the fast tier to the package being changed.
- Bootstrap Phase 6 rewrite: run the fast tier twice to catch flakes,
  break a line a smoke test actually *covers* (breaking an uncovered line
  proves nothing), restore via `git checkout`/`git stash`; Phase 1 now
  reports git-repo status and proposes `git init` (ask first) for
  unversioned dirs.
- `/retro` routing gate: lessons true for anyone who clones the repo go to
  committed notes; machine-local or personal facts go to the harness's
  memory system (Claude Code's per-project `memory/` dir + `MEMORY.md`
  index) and are never committed; on Codex (no memory system) only the
  machine-independent generalization is kept — an honest gap beats a note
  no harness loads.
- `test.sh` now enforces the doctrine's word-count budget (≤420 words) and
  platform-neutral vocabulary, smoke-runs `detect.sh` against the repo
  itself, and covers the new skill and script in both sandbox cycles.
- Example settings: inert check-suppression guard hook (blocks edits that
  add `noqa`/`ts-ignore`/`.skip(`-style markers, mechanizing "never weaken
  a check"), and the derived-files hook example now explains scoping by
  `tool_input.file_path` so it does not run on every edit.
- `reviewer` agent: `model: inherit` frontmatter — an adversarial reviewer
  on a weaker model than the author defeats its purpose. The Codex
  transform drops `model:` alongside `tools:`.

### Changed

- **Doctrine cut from 15 rules to 9** (568 → ~415 words). Removed
  outright — each relies on a behavior 2026 harnesses enforce by default;
  if a harness regresses, restore from here: style matching (old R7
  tail), read-before-overwrite (old R8 tail — mechanically enforced by
  Write tools), wide-read delegation (old R10 — also impossible on
  Codex). Folded into surviving rules, not cut: faithful run reporting
  (old R3 → one clause in new R1), the loop itself (old R5 → preamble),
  read-project-notes-first (old R12 → new R8), routine-work-without-
  blocking (old R13 → new R9), whole-scope completion and honest handback
  (old R15 / R5 tail → closing clause of new R9). The stop-and-ask list
  survives as new R9.
- Doctrine rule 7 routes risky/wide diffs through the harness's built-in
  review command when one exists (Claude Code: `/code-review`), with the
  shipped `reviewer` agent as the portable fallback and the only reviewer
  on Codex.
- Doctrine and skills are now platform-neutral: "notes file
  (`CLAUDE.md` / `AGENTS.md`)" instead of assuming one harness; bootstrap
  Phase 4 marks hooks/settings/`/fewer-permission-prompts` as Claude-only
  and tells Codex sessions to encode the same guardrails in `AGENTS.md`;
  Phase 5 retitled "Project notes file".
- Bootstrap Phase 1 no longer early-stops at possibly-stale docs: sources
  are reordered CI-first and doc-claimed commands are cross-checked
  against CI; a docs/CI mismatch is itself a finding.
- README: removed the free-floating version line (CHANGELOG is the version
  source of truth), corrected the `SessionStart` design note (Claude Code
  re-injects `CLAUDE.md` after compaction; the real anti-drift lever is
  doctrine size), and recorded the decision against plugin packaging.

### Fixed

- The slugify grader could be gamed for a perfect score: keeping the four
  original test *names* with `pass` bodies plus one real regression test
  passed every criterion. A new contract-mutant criterion (the worked suite
  must go red against an implementation that breaks the original
  leading/trailing-separator contract while handling unicode correctly)
  closes it; the exact cheat is checked in as `gamed/` and CI proves the
  grader rejects it.
- The verify-tracking hook counted *reading* the test file (`cat test.sh`,
  `grep pytest README`) as a verify run, flipping the statusline green and
  disarming the stop nudge with no test run — fixed opt-in via
  `LUCIAZERO_VERIFY_CMD` exact matching (the broad regex remains the default).
- The example check-suppression guard blocked edits *near* a pre-existing
  suppression marker (it regexed the whole tool input, so an untouched
  `noqa` in `old_string` triggered it). Now diff-aware: it compares marker
  counts between new and old text (`old_string` for Edit, the on-disk file
  for Write) and blocks only when an edit *adds* a marker.
- `uninstall.sh` no longer aborts halfway (unguarded `grep` no-match under
  `set -e`) when `CLAUDE.md` contains only the import line — exactly the
  state `install.sh` creates for a user with no prior `CLAUDE.md`. It now
  also removes an empty `CLAUDE.md` instead of leaving a zero-line file.
  Regression-tested by a fresh-user install→uninstall cycle in `test.sh`.
- `install-codex.sh` reinstalls no longer grow `AGENTS.md` by one blank
  line per run; a reinstall is now byte-identical (asserted in `test.sh`).
- Backup names (`*.bak.<timestamp>`) are collision-proof in all four
  install/uninstall scripts — two runs in the same second previously
  overwrote the earlier backup, destroying the pristine pre-install copy.

## [1.3.0] - 2026-08-07

### Added

- OpenAI Codex CLI support: `install-codex.sh` / `uninstall-codex.sh`.
  Doctrine lands as a marker-delimited block in `~/.codex/AGENTS.md`;
  `luciazero-bootstrap` and `retro` copy as-is (Codex reads the same
  `SKILL.md` format); the `reviewer` agent ships as a Codex skill with the
  Claude-only `tools:` frontmatter line dropped. Honors `CODEX_HOME`,
  backs up `AGENTS.md`, idempotent, converts from the `claude/` sources at
  install time so nothing is duplicated in the repo.
- `test.sh` covers the Codex cycle in its own sandbox (marker-block
  idempotency, skill installs, `tools:` line stripped, uninstall restores
  pre-existing `AGENTS.md` content).

## [1.2.0] - 2026-08-07

### Added

- Doctrine rule 6 — debugging starts with a hypothesis and the command
  that would confirm or refute it, before any edit.
- Doctrine rule 9 — review the final diff as a skeptic before declaring
  done; risky diffs get an independent reviewer agent. (15 rules total.)
- `/retro` skill — harvest session lessons (null results, footguns,
  environment quirks) into the project's `CLAUDE.md`/`docs/`, deduping
  against and correcting existing notes.
- `agents/reviewer.md` — read-only adversarial reviewer subagent:
  severity-tagged findings, verified against source, `No findings.` over
  invented ones.
- Bootstrap Phase 2 — two-tier verify guidance: fast `verify` every loop
  iteration, `verify-full` before declaring done; single tier for small
  repos.

### Changed

- `install.sh`/`uninstall.sh`/`test.sh` cover the new skill and agent;
  installer backs up a pre-existing customized `agents/reviewer.md`
  before overwriting.

## [1.1.0] - 2026-08-07

### Added

- Doctrine rule 12 — **stop and ask before high-stakes moves, and ask
  clearly**: deleting data, deploying or touching production,
  force-pushing, changing a public API/contract, spending real money, or
  leaving the agreed scope require a decidable question (what, why,
  options, recommendation) before proceeding. "Finish the whole scope"
  renumbered to 13.

## [1.0.0] - 2026-08-07

### Added

- 12-rule luciazero doctrine (`claude/luciazero.md`),
  loaded in every session via an `@luciazero.md` import in the
  global `~/.claude/CLAUDE.md`.
- `/luciazero-bootstrap` skill — six-phase, language-agnostic procedure that
  makes a repository agent-ready (detect commands, establish a verify
  command, smoke tests, guardrails, project `CLAUDE.md`, prove verify can
  go red).
- `install.sh` / `uninstall.sh` — idempotent, back up `CLAUDE.md` before
  editing, never write outside the Claude config dir, honor
  `CLAUDE_CONFIG_DIR`.
- Inert per-repo settings example
  (`examples/project-settings.example.json`): permission allowlist,
  secret-read denies, disabled hook templates.
- `test.sh` verify command; GitHub Actions CI on every push and
  zip-building release workflow on version tags.
- MIT license.

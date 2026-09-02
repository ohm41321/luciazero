# Changelog

All notable changes to this project are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Canonical Claude Sonnet campaign `claude-sonnet-2026-08-21`: ten tasks, five
  valid runs in every cell, no invalid rows, one pinned repository commit and
  CLI build. Sonnet passes every criterion in 39/50 runs against 23/50 bare.
  The 2026-08-11 Sonnet pilot stays checked in for audit but is superseded.

### Changed

- Generated evidence tables now carry a task count per campaign, because the
  2026-09-02 campaign runs four tasks the 2026-08-11 campaigns never had and
  the rows are not like-for-like.

## [2.4.3] - 2026-08-24

### Changed

- README hero copy, live badges, proof strip, and 30-second demos now make the
  Claude Code/Codex entry points easier to discover.
- Added `docs/launch-kit.md` with reproducible launch copy, benchmark gates, and
  distribution checklists.

## [2.4.2] - 2026-08-21

### Fixed

- Skill frontmatter no longer uses an unquoted `: ` in the `done`
  description, so `npx skills update done` can parse and refresh it.
- Prompt checks reject unquoted colon-space YAML descriptions to prevent the
  update failure from returning.

### Changed

- Package, plugin, marketplace, and license metadata now carry the
  maintainer identity athit <athitfkm@gmail.com>.

## [2.4.1] - 2026-08-20

### Fixed

- Release verification no longer treats intentional shell fixtures and
  boolean assertions in `test.sh` as ShellCheck failures on GitHub Actions.

## [2.4.0] - 2026-08-20

### Added

- `/lucia-relay` cross-machine schema 3 publishes a commit-named transfer tag
  and records a sanitized repository locator, live-checked ref/OID, task base,
  and committed changed files.
  `relay.py envelope` emits repository URL, HEAD, and manifest digest for a
  trusted channel. A fresh receiver clone supplies that envelope, supports
  detached checkout, never executes artifact commands, and consumes only after
  the receiver reruns evidence in its own harness and explicitly passes
  `--verified` with the trusted envelope fields.

### Security

- Cross-machine relays no longer trust their own route or commands. Legacy
  schema 1/2 is same-machine only; receiver context prevents route downgrade,
  artifact and string sizes are bounded, common npm/Slack/Google/GitLab secret
  shapes plus authenticated URLs and JWTs are rejected, multiple/rewritten/
  split/command-overridden Git transports fail closed, Git calls have timeouts,
  and repository pointers must be contained tracked blobs.

## [2.3.0] - 2026-08-16

### Fixed

- `test.sh` clears ambient `LUCIAZERO_*` variables before running. An exported
  `LUCIAZERO_VERIFY_CMD` flipped the hook fixtures into exact-match mode, so
  the suite went red on exactly the machines that dogfood the pack
  (`FAIL: stop hook nudged despite verify after edit`) while CI stayed green.
  A new self-test re-runs the fast tier in a child poisoned with every knob the
  hooks read, and quotes the child's own failing line.
- The verify hook parses under bash 3.2 again — the `/bin/bash` on stock macOS.
  A here-document inside a command substitution (with a quoted expansion and a
  trailing redirection on the same line) breaks that parser, and it rejects the
  **whole file** at load time while pointing at an unrelated later line, so the
  enforcement pack silently did nothing there. The scanner program now lives in
  a variable. `test.sh` rejects the construct in the hooks and, with
  `LZ_BASH32=/path/to/bash-3.2`, parses every script with the real thing.
- Both hooks call `hashlib.md5(..., usedforsecurity=False)` for their state
  directory name. On a FIPS-enforcing python3 the bare call raised and the
  tracker failed open — silently doing nothing. The digest is unchanged, so
  existing state keys still resolve.
- CI now parses every repository shell script with Bash 3.2.

### Security

- A repository's **committed** `.claude/settings.json` can no longer configure
  Luciazero at all: every `LUCIAZERO_*` key declared there is dropped and the
  hook falls back to its own defaults. `LUCIAZERO_VERIFY_REGEX` and
  `LUCIAZERO_VERIFY_CMD` could make any command count as a verify run,
  `LUCIAZERO_DOC_REGEX='.*'` made every edit look like documentation so nothing
  was ever unverified, and `LUCIAZERO_STRICT_VERIFY_CMD` was a command the stop
  hook would run. A committed `CLAUDE_CONFIG_DIR` is refused for the same
  reason: it could point at a repository-controlled "wired classic install" and
  make every hook copy stand down. Only the default `~/.claude` is treated as
  the user's config directory during the search — honouring `CLAUDE_CONFIG_DIR`
  there let a repository point it at its own `.claude` so the scanner skipped
  the file declaring the key. The search covers the session directory and
  its ancestors — Claude Code merges project settings from the repository root
  and a session's cwd is often a subdirectory — but it is **project scope
  only**: it stops at the repository root, at `CLAUDE_PROJECT_DIR`, and at
  `$HOME`, and never reads the user's own config directory, so a global
  `~/.claude/settings.json` keeps configuring the hook.
  `SessionStart` names the refused keys once. The
  personal, gitignored `.claude/settings.local.json` is untouched, a parse error
  leaves values alone (still fail-open), the lookup runs only in the modes that
  consume a knob, skips a non-regular file (a planted fifo would hang the hook),
  and refuses everything outright on an absurdly large settings file instead of
  parsing it.
- Channel dedupe is decided from the running copy's own path instead of
  `LUCIAZERO_CHANNEL`. A committed `env` block could set that variable, hand the
  **classic** hook a plugin label, and make it stand itself down — disabling
  enforcement with one line.
- `install.sh --with-hooks` refuses a python3 older than 3.9 (where hashlib
  gained `usedforsecurity=`) instead of installing hooks that fail open, and
  `--status` reports the version. README states the requirement.
- CI runs with `permissions: contents: read`, and both workflows pin every
  action to a commit SHA.

### Changed

- `shellcheck` is required, not silently skipped, when `CI` or
  `LZ_REQUIRE_LINT` is set — a local green must not disagree with the CI that
  gates the release.
- README and README.th document the committed-settings refusal and the
  Windows/WSL requirement.
- Retired the `/luciazero-bootstrap` compatibility alias after the `/ready`
  migration window. Installers remove only untouched Luciazero-owned copies and
  preserve customized user directories.
- Capped skill discovery descriptions at 40 words and tightened path/offline
  guidance for the closeout, debug, ready, retro, and discipline skills.

## [2.2.0] - 2026-08-15

### Added

- `/imouto-mode` adds Lucia's optional warm, lightly tsundere younger-sister
  coding voice. It is explicit-only, off by default, invocation-scoped, and
  keeps technical work, safety, and verification ahead of persona.

## [2.1.0] - 2026-08-15

### Added

- `/show` turns code relationships, structural changes, and verification
  evidence into the smallest useful traceable visual.
- `./test.sh --fast` provides a measured intermediate tier while the default
  and `--full` preserve complete CI/closeout coverage.
- Opt-in Claude hooks use private per-session scratch state to record
  privacy-preserving aggregate turn/merged-Bash wall time and Bash, failed or
  successful verify, and model/user skill counts; `luciazero discipline`
  summarizes them.

### Changed

- `/luciazero-bootstrap` is now `/ready`. The old command remains as a
  deprecated compatibility alias for one release.
- The doctrine reserves full verification for closeout, and `/plan` plus
  `/debug` no longer auto-trigger for routine edits or first obvious failures.

## [2.0.3] - 2026-08-13

### Fixed

- The Claude plugin now exposes its reviewer from the default root `agents/`
  directory. Claude Code 2.1.227 validated the former custom manifest path but
  reported and loaded zero agents; the default layout reports one. CI requires
  the plugin mirror to match the classic install source byte-for-byte and
  prevents the custom path from returning.

## [2.0.2] - 2026-08-13

### Fixed

- `/lucia-relay` now records whether its recipient is on the same machine or a
  different one before producing pointers. Schema 2 permits full paths only
  for same-machine delivery; cross-machine validation requires a clean HEAD
  reachable from a locally known remote branch, rejects machine-only paths,
  and provides `knowledge.inline` for otherwise-local context. Schema 1 relays
  remain readable as same-machine-only legacy artifacts, and legacy `draft`
  callers without `--recipient` safely default to same-machine delivery.

## [2.0.1] - 2026-08-13

### Added

- **Explicit, channel-aware updates.** `npx luciazero@latest check-update`
  performs a read-only, five-second npm registry check only when invoked;
  `npx luciazero@latest update` detects classic Claude, its hook mode, and
  Codex, then refreshes every detected install through the existing audited
  installers. It refuses to create a fresh install, downgrade a recognized
  newer one, or trust a malformed version sidecar. Legacy installs without the
  sidecar remain updatable. Classic doctrine customization now receives the
  same managed-snapshot backup protection as skills and agents.
  Plugin and skills-only update commands, Claude plugin auto-update, and GitHub
  release notifications are documented separately in both READMEs.

### Changed

- The release workflow uses the runner's GitHub CLI instead of a Node 20-based
  release action. Re-runs replace the existing zip without recreating the
  release, and GitHub Actions no longer emits the deprecated-runtime warning.

## [2.0.0] - 2026-08-13

### Changed

- The canonical Sonnet result is explicitly preliminary (`+31pp`, n=4–5).
  The historical `+37pp` statement is retired because its eight replacement
  raw rows could not be recovered.
- `eval/report.sh` rejects mixed campaigns/commits/seeds, changed fixture
  hashes, duplicate invocation IDs, and inconsistent pair order. Published
  evidence also enforces registered task/arm/row/invalid/model expectations,
  and discloses Haiku's incomplete per-row model provenance.
- Eval tasks may provide deterministic offline setup before either arm. Provider
  transcripts now live outside worked trees so they cannot alter Git status,
  repository fingerprints, or final-tree grading.
- Relay fingerprints encode untracked special files without opening them, so a
  FIFO, socket, or device cannot block inspection or trigger device I/O.
- GitHub workflows use the Node 24-based `actions/checkout@v5` and
  `actions/setup-node@v5` runtimes.
- **Breaking: `/handoff` is now `/lucia-relay`.** The branded name avoids
  collisions with generic handoff skills. Installs remove an untouched v1.5
  copy but preserve and warn about customized copies. Relay state is now a
  validated `LUCIA_RELAY.json` manifest plus a generated human view, with a
  repository fingerprint, verification evidence, negative knowledge,
  cross-session/cross-agent routing, drift inspection, and explicit consume.
- **Risk-routed review.** The single portable reviewer now accepts `general`,
  `security`, and `contract` focus modes, reads callers/consumers, and uses one
  blocker/major/minor policy. `/done` requests separate focused passes when a
  diff crosses both security and contract boundaries.
- **Smart verification is repo-owned.** Monorepos create `verify-changed` from
  their native task graph and keep `verify-full` for closeout. The global hook
  never guesses dependency impact from path prefixes.
- **Classic and Codex installs track component ownership.** Exact hidden
  snapshots distinguish Luciazero-managed skills/agents from same-name user or
  third-party components. Updates back up collisions/customizations, and
  uninstall removes only an unchanged managed copy.

### Added

- Auditable benchmark evidence: canonical Claude raw JSONL, a SHA-256 campaign
  registry, generated README/benchmark tables, and a CI drift check.
- Result schema 2 records campaign, pair, invocation, repository, fixture,
  prompt, platform, and arm-order metadata. Seeded arm randomization reduces
  fixed-order bias without making campaigns irreproducible.
- Strict shared result validation rejects unsupported schemas and mistyped
  booleans, criteria, metrics, timestamps, platform, and campaign metadata.
  Output-aware `--resume` fills interrupted pairs without rerunning completed
  invocation IDs; `--run-offset` extends completed batches.
- Three zero-quota candidate eval tasks cover archive extraction security,
  lossless atomic schema migration, and multi-page cursor integration. Each
  grader proves reference/project/anti-gamed behavior offline.
- **`relay-transfer` protocol eval** grades portable state, an exact next edit,
  verification evidence, negative knowledge, scope preservation, and a current
  repository fingerprint. CI proves its 6/6 reference and rejects generic
  prose plus a content-complete stale relay without spending model quota.
- **Lucia Relay demo** drives the shipped producer/receiver implementation in
  a temporary Git repository: render, validate, detect drift, re-run evidence,
  and explicitly consume. The checked-in GIF is generated from the same script
  exercised by CI.
- **Central component catalogs** drive classic/Codex install, status,
  uninstall, and inventory tests, so a new skill or agent cannot silently ship
  through only one channel.
- **`/plan`** defines falsifiable acceptance signals and reversible steps,
  while pausing for approval only on ambiguity, high stakes, destructive work,
  public-contract choices, or scope changes.
- **`/bisect` + `safe-bisect.sh`** locate the first bad commit in a detached
  temporary worktree, repeat endpoints to catch flakes, preserve exit 125
  skips, distinguish missing commands, and clean every exit path.
- **`npx luciazero discipline` + `/discipline-report`** analyze schema-v2
  local JSONL outcomes with day/project filters and JSON output. The hook logs
  a privacy-preserving project hash and verify mode; legacy records remain
  readable and recommendations distinguish observations from likely causes.
- **`/lucia-relay` carries memory pointers** — the `Read first`
  section quotes the `docs/lessons.md` entries relevant to the unfinished
  work (a selection, never a copy — the ledger travels with the repo) and
  copies applicable machine-local `luciazero-heuristics.md` entries
  verbatim, since the relay is the only way those cross machines. The
  consume protocol tells the reader to follow the pointers before touching
  code and to adopt carried heuristics that earn their keep.

- **`eval/run.sh --use-login`** — run the real eval on an existing Claude
  subscription (Pro/Max) instead of API dollars: seeds each per-run sandbox
  config dir with this machine's login state — `~/.claude.json`, plus
  OAuth tokens from `.credentials.json` (Linux) or a Keychain export
  (macOS). The copy lives only inside the mktemp sandbox and is deleted
  with it. Fail-soft by
  design: if the seed does not authenticate, `check-result.sh` marks the
  arm INVALID and nothing is spent. Plumbing (seed per arm, warn on missing
  login state) is proven offline in `test.sh`.

- **`eval/check-result.sh`** — a zero exit code no longer proves the agent
  ran: the CLI has wrapped a `Not logged in` error in subtype `"success"`
  (observed 2026-08-11, caught free by a 1-run smoke). The guard inspects
  the result payload (`is_error`, `terminal_reason: api_error`, login
  errors) and `run.sh` books a refuted arm as INVALID with the reason
  quoted; every accept/reject path is fixture-proven in `test.sh`.
- **`eval/run.sh --offline`** — synthetic smoke mode: no `claude` CLI, no
  API key, zero cost. Doctrine-style arms get the task's `reference/` tree,
  bare keeps the planted bug, and the whole copy → grade → JSONL → report
  loop runs in seconds. Rows are branded `"offline": true` and `report.sh`
  prints a SYNTHETIC banner so the numbers can never pass as behavioral
  results; end-to-end proven in `test.sh` plus a frozen fixture pair.
- **README narrative reorder** (EN + TH): the demo GIF and the
  "What it prevents" table now sit directly under the intro, before
  Install — a newcomer sees what the pack does in 30 seconds before being
  asked to install anything.

- **README demo GIF** — 15 seconds of the enforcement pack's real behavior:
  edit → `✎ unverified`, stop attempt → the rule-1 nudge, red verify →
  `❌ verify RED`, fix → `✅ verify`. Recorded from the checked-in
  `docs/assets/statusline-demo.sh`, which drives the shipped hooks in a
  sandbox (so the GIF cannot drift from what the scripts actually print),
  via the checked-in `docs/assets/demo.tape` (`vhs`). The driver script is
  under `test.sh`'s shellcheck net.

- **`false-green` eval task** (sixth): the false-done trap — the shipped
  suite is green from the start while the CSV escaping bug lives outside
  its coverage. The untouched tree *passes its own tests* and still fails
  the grader (symptom probed on unseen data; bug-restored suite must go
  red), which is doctrine rule 1 stated as a fixture. `gamed/` (comma-only
  half fix) and `gamed-notest/` (correct fix, no test added) are rejected.
- **`--with-lessons` eval arm** — `eval/run.sh --with-lessons` runs a third
  arm for tasks that ship a `lessons.md` (currently `pipeline` and
  `false-green`): doctrine install plus the task's ledger pre-seeded as
  `docs/lessons.md`, the A/B/C comparison that measures whether the
  learning layer pays. `report.sh` discovers arm columns from the data and
  renders per-arm deltas; frozen three-arm fixture added to `test.sh`.
- **Per-run resource accounting** — `run.sh --out` now records duration,
  token usage, and cost per run (parsed fail-open from the CLI's
  `--output-format json` result), and `report.sh` appends per-arm resource
  means whenever the data is present — a pass-rate delta is only a win if
  the cost next to it says so.
- **Community eval issue templates** — `Evaluation result` (report.sh
  output required, null results explicitly welcome) and `New eval task`
  (asks for the doctrine rule probed and the gamed tree that would cheat
  the grader).

- **`merge-conflict` eval task** (fifth): an unresolved merge where main's
  bulk discount and the branch's member discount must both survive. The
  grader probes each feature on data the shipped tests never mention, and
  swaps in one-sided feature mutants to prove the worked tests actually
  cover both sides — `gamed/` (HEAD-only resolution, suite green) and
  `gamed-notests/` (correct merge, no tests added) are both rejected.
- **Machine-readable closeout evidence** — `/done` step 6 now mirrors the
  report as a JSON block (status, verify command + exit code + decisive
  line, not-covered, left-out) when the result feeds CI, a PR comment, or a
  dashboard.
- **README "What it prevents" section** (EN + TH): failure modes mapped to
  the shipped mechanism that catches each — no promise without a mechanism.
- **SECURITY.md** — private reporting channel plus the enforced design
  guarantees (no network, no npm lifecycle scripts, fail-open hooks,
  config-dir-only writes) and the documented strict-mode env sharp edge.
- **GitHub issue templates** — bug report (channel + decisive-output
  evidence required), feature request (doctrine-fit question), security
  contact link.

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

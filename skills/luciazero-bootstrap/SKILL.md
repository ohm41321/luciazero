---
name: luciazero-bootstrap
description: Make a repository agentic-ready so an agent can run its own plan→change→verify→fix loop without a human checking each step. Use when entering an unfamiliar repo, when the user asks to "set up agentic engineering", "make this repo agent-friendly", "add a verify command", "add smoke tests so you can check your own work", "set up hooks/CLAUDE.md/allowlist" — or when a change was requested but no automated way exists to prove it works.
---

# Luciazero Bootstrap

Goal: leave the repo with **one command that returns an exit code** and enough guardrails that future agent work self-verifies. Nothing here is language-specific — detect, don't assume.

Bootstrapping is itself work: verify each artifact you add actually runs before reporting it.

## Phase 1 — Detect (never assume)

Run the bundled evidence scan first — it replaces a dozen manual reads with one call:

```
<this-skill-dir>/scripts/detect.sh <repo-root>
```

(The skill directory is wherever this SKILL.md lives, e.g. `~/.claude/skills/luciazero-bootstrap/` or `~/.codex/skills/luciazero-bootstrap/`.) The script surfaces candidates — **you still decide**. It cannot parse CI matrices or exotic build systems; open anything it flags and read the CI config yourself.

Sources, in order of trust:

1. CI config — the most honest source of truth: `.github/workflows/*`, `.gitlab-ci.yml`, `.circleci/`. **Whatever CI runs is the verify command.**
2. Manifests: `package.json` scripts, `pyproject.toml` / `tox.ini` / `noxfile.py`, `Makefile`, `justfile`, `Cargo.toml`, `go.mod`, `build.gradle`, `composer.json`
3. Repo docs: `README*`, `CONTRIBUTING*`, `AGENTS.md`, `CLAUDE.md`, `docs/` — docs go stale; cross-check any doc-claimed command against CI when CI exists. A docs/CI mismatch is itself a finding to record in Phase 5.
4. Existing test dirs: `tests/`, `test/`, `spec/`, `__tests__/`, `*_test.*`, `test_*.*`

Report what was found as a short table: run / test / lint / typecheck / build / git repo — command or `MISSING`.

**If the directory is not under version control**, propose `git init` early (ask first — some dirs are deliberately not repos): without git there is no smallest reversible step, no safe break-and-restore in Phase 6, and no bisect.

## Phase 2 — Establish the verify command

If a verify path exists, **use it** — do not invent a parallel one.

If none exists, create the smallest real one. Order of preference:

1. The project's native runner, already installed (`pytest`, `vitest`, `go test`, `cargo test`, `dotnet test`)
2. A single entrypoint that chains them, matching the repo's existing convention (`Makefile` target, `package.json` script, `justfile` recipe) — e.g. `make verify` running lint then tests

Rules:
- Must exit non-zero on failure. A script that always exits 0 is worse than nothing.
- Must run to completion unattended: disable watch/interactive modes (e.g. `CI=1`, `--run`, `--watch=false`) — a command that waits for input or watches files hangs the loop.
- Must run offline, with no credentials. Anything needing GPU/network/secrets belongs in a separate slow target.
- Time the suite once (`time <cmd>`); the measurement, not a guess, decides one tier or two.
- On success, output should be near-silent — prefer quiet flags in the fast tier so failures, not progress spam, fill the context.
- Add it to the repo's own docs so humans find it too.

**Two tiers when the repo has slow checks.** One `verify` command forces a bad trade: either the loop crawls or coverage gets cut. Split it:

- `verify` — fast (<~60s), offline: lint, typecheck, unit/smoke tests. Run on **every** loop iteration.
- `verify-full` — everything else: full suite, integration, build, slow checks. Run **before declaring done** and before a PR — "done" means `verify-full` green, not just `verify`.

Name them by the repo's convention (`make verify` / `make verify-full`, npm scripts, just recipes). A small repo whose whole suite runs in seconds needs only the single tier — do not add ceremony it does not need.

**Monorepos:** detect the workspace layout (`package.json` `workspaces`, `pnpm-workspace.yaml`, turbo/nx config, `go.work`, Cargo `[workspace]`). The fast tier must be scoped to the package being changed (e.g. `pnpm --filter <pkg> test`, `go test ./changed/pkg/...`, `cargo test -p <crate>`); `verify-full` is the root suite. Record in the Phase 5 notes how to derive the scoped command from a file path.

**Enforcement pack users (Claude Code, ask first):** if the verify-tracking hooks are active — classic install: `~/.claude/hooks/luciazero-verify.sh` exists; plugin install: the `luciazero` plugin is enabled — offer to record the established command in the repo's *personal* settings so the tracker matches it exactly instead of by broad regex — `.claude/settings.local.json` (gitignored, never committed): `{"env": {"LUCIAZERO_VERIFY_CMD": "<the fast-tier command>"}}`. Derive it from CI (the honest source); it is a cache of that truth, so note it must be updated if CI changes. Show the exact JSON before writing anything.

## Phase 3 — Smoke tests, if there are none

Do **not** attempt coverage. Write 3–6 tests that would catch a catastrophic break. Pick by this heuristic:

- **Contract shape** — the core data structure in/out: dimensions, keys, types, no NaN/null where impossible
- **Round trip** — serialize→deserialize, encode→decode, save→load returns equal
- **Import/boot** — every package imports, the app answers one request, the CLI runs `--help`. Prefer the framework's test client over binding a real port; any test that starts a process needs a hard timeout and must kill what it started.
- **Artifact loads** — trained model / migration / config parses and does one forward pass or one query
- **The bug you were sent to fix** — a regression test reproducing it, written *before* the fix

Use fixtures small enough to commit. Never depend on the user's real data paths.

State plainly that these are smoke tests, not a suite.

## Phase 4 — Guardrails (only ones that pay for themselves)

Hooks, `.claude/settings.json`, and `/fewer-permission-prompts` are **Claude Code mechanisms**. On a harness without them (Codex CLI), skip the hook items and encode the same guardrails as instructions in the project's `AGENTS.md` instead: which files are untouchable, which derived file must be regenerated after editing which source.

Prefer few and deterministic. Candidates, in value order:

- **Auto-format/lint on write** — `PostToolUse` hook matching `Edit|Write`, running the repo's own formatter. Only if the repo already has one configured.
- **Regenerate derived files** — if editing source X requires regenerating Y (protobuf, OpenAPI clients, migrations, lockfiles), hook it, scoped inside the command to the relevant paths. This is the highest-value hook in most repos because humans forget it.
- **Protect the untouchables** — `PreToolUse` deny on production config, secrets, live model/deploy pointers.
- **Permission allowlist** — put the repo's read-only and verify commands into `.claude/settings.json` so the loop is not interrupted. `/fewer-permission-prompts` derives this from real transcripts.

Put project-scoped settings in the repo's `.claude/settings.json` (shared) or `.claude/settings.local.json` (personal, gitignored) — **not** in global settings.

Hooks execute automatically on the user's machine. Show the exact command before installing it, and never install one that pushes, deploys, deletes, or writes outside the repo.

## Phase 5 — Project notes file (`CLAUDE.md` / `AGENTS.md`)

Extend the notes file the repo already uses; if neither exists, create the one matching the current harness and add a one-line pointer from the other name so both find it. Write only what reading the code cannot tell you:

- How to run / test / verify — the commands from Phase 2
- Architecture facts that are load-bearing and non-obvious (what serves what, which file is source of truth)
- **Footguns and null results**: "X looks right but breaks Y", "tried A, measured no gain, do not retry", "always rebuild Z after W"
- Where the real docs live

Do not restate the directory tree, git history, or anything a `grep` answers. Keep it dense; every line costs context on every future session.

## Phase 6 — Prove it and report

1. **Flake check** — run the fast verify tier twice. A green that does not repeat is a flake, and a flaky verify makes every future red ambiguous; fixing or quarantining the flake comes before relying on the loop. (Skip the double run only when the repo has a single slow tier — say so.)
2. **Red check** — break a line a smoke test actually covers (flip an expected value or a return), confirm verify goes red, then restore. The break is one deliberate edit: **record file, line, and original text before making it, and restore by reverting exactly that edit.** Only use `git checkout -- <file>` if the file was committed before the break — on a file carrying uncommitted work it silently discards that work too, and it cannot restore the untracked test files this skill just wrote. Never use bare `git stash` here (it sweeps the whole tree and skips untracked files). Breaking an uncovered line and staying green proves nothing. A verify command that cannot fail is not a verify command.

Report:
- The one command to run (both tiers if split)
- What it does and does not cover
- What was added, and what was deliberately left out

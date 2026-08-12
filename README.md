**English** | [ภาษาไทย](README.th.md)

# Luciazero for Claude Code & Codex CLI

[![npm](https://img.shields.io/npm/v/luciazero)](https://www.npmjs.com/package/luciazero)
[![CI](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg)](https://github.com/ohm41321/luciazero/actions/workflows/ci.yml)
[![license](https://img.shields.io/github/license/ohm41321/luciazero)](LICENSE)

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/lucia.png" width="280" alt="Lucia — Luciazero's mascot">
</p>

Luciazero makes coding agents run a `plan → change → verify → fix` loop instead
of handing back work they merely believe is finished.

> Done is proven by a command, not by my judgment. If no verification command
> exists, that is the first bug.

It ships a compact [9-rule doctrine](claude/luciazero.md), 9 on-demand skills,
verification hooks, a risk-routed reviewer, and an eval harness. It is a
discipline layer, not an agent runtime or overnight orchestrator.

## See it in 15 seconds

This GIF is driven by the shipped hooks, not a mockup:

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/statusline-demo.gif" width="720" alt="Edit becomes unverified, a red check stays red, and a successful verify turns green">
</p>

```text
✎ unverified   → edits happened after the last check
❌ verify RED  → the latest check failed
✅ verify 3m   → the latest check passed three minutes ago
```

## What it prevents

| Failure mode | Mechanism |
|---|---|
| “Done” without running a check | Stop-hook nudge; optional strict gate blocks a red stop |
| `cat test.sh` counted as testing | Exact `LUCIAZERO_VERIFY_CMD` matching |
| Tests weakened to reach green | Doctrine rule 3 + check-suppression guard |
| New tests that pass without the fix | `revert-probe.sh` runs them against the old code |
| Scope silently dropped | `/done` requires every item delivered or named as left out |
| The same dead end repeated later | `/retro` records it; `/debug` reads it first |
| Context lost between agents | `/lucia-relay` transfers evidence, next action, and negative knowledge |

Mechanical guarantees run in `test.sh`; behavioral claims are measured by the
[eval harness](eval/README.md).

## Install

> The npm badge shows the latest published package. Until `2.0.0` is tagged and
> published, `npx luciazero` still installs the older npm release; GitHub/plugin
> channels use this repository's current source.

### Claude Code plugin — recommended

Carries the doctrine, all skills, reviewer, and verify-tracking hooks:

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

Start a repository with `/luciazero:luciazero-bootstrap`. Plugin skills use the
`/luciazero:` prefix. The plugin has no statusline because Claude Code plugins
cannot set one.

### Skills only — any compatible agent

```bash
npx skills add ohm41321/luciazero
```

This installs the 9 skills only: no doctrine, reviewer, or hooks.

### Classic Claude Code and Codex

```bash
npx luciazero                 # Claude Code
npx luciazero --with-hooks    # Claude Code + hooks/statusline; needs Python 3
npx luciazero codex           # Codex CLI

npx luciazero uninstall
npx luciazero uninstall-codex
```

Pick either plugin or classic for Claude Code so hooks are not wired twice.
Classic installs support `--status`; Codex receives the doctrine and skills but
not Claude-only hooks/statusline. Installers back up name collisions and remove
only exact Luciazero-managed copies on uninstall.

## The 9 skills

Run `/luciazero-bootstrap` first; the rest activate when their moment arrives.

| Moment | Skill | Result |
|---|---|---|
| Entering a repository | `/luciazero-bootstrap` | Finds or creates a verify command and proves it can fail |
| Before risky or multi-step work | `/plan` | Fixes scope and observable acceptance evidence |
| A bug survives the first look | `/debug` | Reproduction, hypothesis ledger, regression test |
| Good and bad revisions are known | `/bisect` | Finds the first bad commit in a temporary worktree |
| Before claiming completion | `/done` | Full verify, skeptic review, scope report |
| Work must move elsewhere | `/lucia-relay` | Portable JSON + Markdown state with drift inspection |
| Optimizing performance | `/experiment` | Baseline, threshold, controlled measurement |
| Reviewing local verify habits | `/discipline-report` | Time/project-filtered local outcome report |
| After difficult work | `/retro` | Stores reusable lessons and disproved approaches |

Risky diffs also pass through one read-only `reviewer` with `security`,
`contract`, or `general` focus. Security and contract risk together receive two
separate passes.

## Evidence

Latest behavioral snapshot (2026-08-11), all-criteria pass rate:

| Claude model | Luciazero | Bare | Difference |
|---|---:|---:|---:|
| Haiku, 10 valid/task | 36/60 (60%) | 27/60 (45%) | +15pp |
| Sonnet, 4–5 valid/task* | 25/27 (93%) | 16/26 (62%) | +31pp |

The `Luciazero` arm installs the classic pack without hooks; it is not a clean
doctrine-only ablation. *The Sonnet result is preliminary because several arms
have only four valid runs, below the harness's publication threshold. These
samples are Claude-only and do **not** prove the same uplift for GPT/Codex. See
the [full benchmark and GPT evaluation plan](docs/benchmark.md).

## Requirements and safety

- Node.js 18+ for the CLI and discipline report.
- Bash for classic installers; Python 3 for hooks and Lucia Relay.
- Core installers, hooks, helpers, and graders are offline. Real behavioral
  evals invoke a model CLI and consume API credit or subscription quota.
- Hooks run commands on your machine. Read them before enabling them.
- Set `LUCIAZERO_VERIFY_CMD` to the repo's exact fast verify command.
- Put `LUCIAZERO_STRICT_VERIFY_CMD` only in personal settings, never in a
  committed repository config. Strict mode fails open on internal errors.

See [SECURITY.md](SECURITY.md) for the complete trust boundary.

## Development

```bash
./test.sh
```

The suite covers scripts, hook state, Relay, bisect, plugin/npm manifests,
self-proving eval graders, and sandboxed install → reinstall → uninstall for
Claude Code and Codex.

More detail:

- [Architecture and trade-offs](docs/comparison.md)
- [Eval methodology](eval/README.md)
- [Benchmark results and GPT plan](docs/benchmark.md)
- [Contributing](CONTRIBUTING.md)
- [Publishing](docs/publishing.md)
- [Changelog](CHANGELOG.md)

## Lucia family & support

Luciazero shares its mascot with [Lucia](https://lucia-discord-bot.vercel.app),
a Thai-language Discord bot. If Luciazero saves you review cycles, you can
[support the project here](https://easydonate.app/itsathitz) 💚

## License

[MIT](LICENSE)

## ภาษาไทย

README ฉบับภาษาไทยเต็ม: [README.th.md](README.th.md)

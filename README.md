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

It ships a compact [9-rule doctrine](claude/luciazero.md), 10 on-demand skills,
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

## Carry unfinished work across agents

`/lucia-relay` transfers decisions and evidence instead of dumping a chat
transcript. Session A writes canonical `LUCIA_RELAY.json` plus a generated
human view; session B checks the Git fingerprint, reads the exact next action
and refuted hypotheses, re-runs verification, then explicitly consumes the
relay.

Relay decides where the recipient is before it writes pointers. Same-machine
receivers may use full local paths. Cross-machine relays require a clean pushed
commit, reject machine-only paths, and carry otherwise-local knowledge inline
in the JSON.

<p align="center">
  <img src="https://raw.githubusercontent.com/ohm41321/luciazero/main/docs/assets/relay-demo.gif" width="720" alt="One session creates a Lucia Relay; another validates it, detects repository drift, re-runs evidence, and consumes it">
</p>

The GIF runs the [shipped implementation](docs/assets/relay-demo.sh) in a
temporary Git repository. CI's `relay-transfer` fixture scores the complete
reference 6/6 and rejects a generic Markdown handoff (1/6) plus a
content-complete but stale fingerprint (5/6). Those are mechanical protocol
checks—not model-uplift results. See the [method and limits](docs/benchmark.md#skill-protocol-evidence).

## Install

### Claude Code plugin — recommended

Carries the doctrine, all skills, reviewer, and verify-tracking hooks:

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

Start a repository with `/luciazero:ready`. Plugin skills use the
`/luciazero:` prefix. The plugin has no statusline because Claude Code plugins
cannot set one.

### Skills only — any compatible agent

```bash
npx skills add ohm41321/luciazero
```

This installs the 10 skills plus the temporary `/luciazero-bootstrap`
compatibility alias: no doctrine, reviewer, or hooks.

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

## Update

Luciazero never changes classic or Codex files in the background.

```bash
npx luciazero@latest check-update   # read-only; contacts npm only now
npx luciazero@latest update         # updates every detected classic/Codex install
```

`update` preserves whether the Claude classic install uses hooks, repairs stale
managed files, starts no fresh install when it cannot find one, and stops on a
known newer version or malformed version metadata. Start a new agent session
afterward.

Other install channels use their own updater:

```bash
claude plugin update luciazero@luciazero   # then run /reload-plugins
npx skills update                          # review the scope prompt
```

The skills command updates every installed skill in the selected scope, not
only Luciazero; review its prompt before confirming.

Claude Code can auto-update the plugin at startup: open `/plugin` →
**Marketplaces** → **luciazero** → **Enable auto-update**. Third-party
marketplaces leave this off by default. For release-only notifications, use
GitHub **Watch → Custom → Releases**.

## The 10 skills

Run `/ready` first; the rest activate when their moment arrives.

| Moment | Skill | Result |
|---|---|---|
| Entering a repository | `/ready` | Finds or creates a verify command and proves it can fail |
| Structure or evidence is hard to scan | `/show` | Maps connections, changes, and proof into the smallest useful visual |
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

<!-- BEGIN GENERATED: benchmark-evidence -->

### Claude results

Snapshot: 2026-08-11. All-criteria pass rate generated from checked-in raw rows:

| Claude model | Luciazero | Bare | Difference |
|---|---:|---:|---:|
| Haiku†, 10 valid/task | 36/60 (60%) | 27/60 (45%) | +15pp |
| Sonnet, 4–5 valid/task* | 25/27 (93%) | 16/26 (62%) | +31pp |

The `Luciazero` arm installs the classic pack without hooks; it is not a clean
doctrine-only ablation. *Sonnet is preliminary because eight invalid rows leave
several arms at four valid runs. The previously stated `+37pp` top-up is retired
because its replacement raw rows could not be recovered.

†Model provenance is incomplete for Haiku: only 70/140 rows encode model
identity. The other 70 are attributed at campaign-file/report level and
cannot be independently verified per row.

### GPT/Codex pilot — exploratory

Snapshot: 2026-08-12.

| Model | Valid invocations | Paired tasks | Luciazero | Bare | Observed difference |
|---|---:|---:|---:|---:|---:|
| GPT-5.6 Terra, medium | 11/12* | 5 | 5/5 runs, 28/28 criteria | 5/5 runs, 28/28 criteria | +0pp† |

*One Luciazero run was invalidated by model capacity. †This is a
**ceiling-effect warning, not evidence of uplift or no effect**: the pilot has
only one run per arm per task. See the [full benchmark](docs/benchmark.md),
[campaign registry](eval/results/campaigns.json), and
[raw pilot rows](eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl).

<!-- END GENERATED: benchmark-evidence -->

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
- [Raw campaign registry](eval/results/campaigns.json)
- [Experiment log](docs/experiments.md)
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

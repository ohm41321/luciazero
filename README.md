<div align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@37cb470e2b7c704ff32f3a46dbb125e312875960/docs/assets/lucia.png" width="220" alt="Lucia — Luciazero's mascot">
  <h1>Luciazero</h1>
  <p>
    <strong>Make coding agents prove their work.</strong><br>
    <code>plan → change → verify → fix</code>
  </p>
  <p>
    <a href="https://www.npmjs.com/package/luciazero"><img src="https://img.shields.io/npm/v/luciazero" alt="npm version"></a>
    <a href="https://www.npmjs.com/package/luciazero"><img src="https://img.shields.io/npm/dw/luciazero" alt="npm weekly downloads"></a>
    <a href="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml"><img src="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
    <a href="https://github.com/ohm41321/luciazero/stargazers"><img src="https://img.shields.io/github/stars/ohm41321/luciazero?style=flat" alt="GitHub stars"></a>
    <a href="https://github.com/ohm41321/luciazero/network/members"><img src="https://img.shields.io/github/forks/ohm41321/luciazero?style=flat" alt="GitHub forks"></a>
    <a href="https://github.com/ohm41321/luciazero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/ohm41321/luciazero" alt="MIT license"></a>
  </p>
</div>

**English** · [ภาษาไทย](https://github.com/ohm41321/luciazero/blob/main/README.th.md)

<p align="center">
  <strong>12 skills</strong> · <strong>Relay fixture 6/6</strong> · <strong>Claude + Codex</strong> · <strong>MIT</strong>
</p>
<p align="center"><sub>Relay 6/6 is a mechanical protocol check; behavioral results are reported separately.</sub></p>

Luciazero is the verification and handoff layer for Claude Code, Codex CLI, and
compatible skill runtimes. It helps agents prove tests, preserve scope, and
move unfinished work with evidence.

> Done is proven by a command, not by my judgment. If no verification command
> exists, that is the first bug.

Luciazero is for teams that want coding agents to prove work instead of merely
report it. It helps prevent false-green verification and dropped scope,
preserves lessons from repeated dead ends, and carries context across handoffs
when `/lucia-relay` is used. It is a discipline layer, not an agent runtime.

## Start in 30 seconds

Choose the path that matches your agent, then start a new session:

**Claude Code · full pack**

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

Run `/luciazero:ready` in the new session.

**Codex CLI · doctrine + skills**

```bash
npx luciazero codex
```

Run `$ready` in the new session.

**Skills-only · any compatible agent**

```bash
npx skills add ohm41321/luciazero
```

Invoke the installed `ready` skill using your agent's syntax (for Codex CLI,
use `$ready`). This path intentionally does not install the doctrine, reviewer,
or hooks.

## See the loop

This GIF is driven by the shipped hooks, not a mockup:

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@37cb470e2b7c704ff32f3a46dbb125e312875960/docs/assets/statusline-demo.gif" width="720" alt="Edit becomes unverified, a red check stays red, and a successful verify turns green">
</p>

```text
✎ unverified   → edits happened after the last check
❌ verify RED  → the latest check failed
✅ verify 3m   → the latest check passed three minutes ago
```

Run the same shipped hook driver locally—no model or API is required:

```bash
bash docs/assets/statusline-demo.sh
```

For the cross-session handoff demo:

```bash
bash docs/assets/relay-demo.sh
```

Both scripts use throwaway directories and exercise the real implementation.

## What it protects

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
[eval harness](https://github.com/ohm41321/luciazero/blob/main/eval/README.md).

## Keep work portable

`/lucia-relay` transfers decisions and evidence instead of dumping a chat
transcript. Session A writes canonical `LUCIA_RELAY.json` plus a generated
human view; session B checks trusted repository identity, HEAD, and manifest
digest, reads the exact next action and negative knowledge, re-runs every
approved verification command in its own harness, then explicitly consumes.

Same-machine receivers may use local paths and schema 1/2. Cross-machine schema
3 is created only after commit and push: it publishes a commit-named transfer
tag and records a sanitized clone URL, head/base OIDs, committed changed files,
and inline knowledge.
The receiver supplies the expected route, HEAD, and manifest digest independently, so a
forged artifact cannot downgrade validation. Detached checkouts are supported;
Relay never executes artifact commands. The receiver runs them in its coding
harness and passes `consume --verified` only after every result matches.

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@37cb470e2b7c704ff32f3a46dbb125e312875960/docs/assets/relay-demo.gif" width="720" alt="One session creates a Lucia Relay; another validates it, detects repository drift, re-runs evidence, and consumes it">
</p>

The GIF runs the [shipped implementation](https://github.com/ohm41321/luciazero/blob/main/docs/assets/relay-demo.sh) in a
temporary Git repository. CI's `relay-transfer` fixture scores the complete
reference 6/6 and rejects a generic Markdown handoff (1/6) plus a
content-complete but stale fingerprint (5/6). Those are mechanical protocol
checks—not model-uplift results. See the [method and limits](https://github.com/ohm41321/luciazero/blob/main/docs/benchmark.md#skill-protocol-evidence).

## Install

Luciazero supports Claude Code, Codex CLI, and compatible agents. Choose the
installation path that matches your workflow.

<details>
<summary><strong>Recommended · Claude Code plugin</strong></summary>

Carries the doctrine, all skills, reviewer, and verify-tracking hooks:

```text
/plugin marketplace add ohm41321/luciazero
/plugin install luciazero@luciazero
```

Start a repository with `/luciazero:ready`. Plugin skills use the
`/luciazero:` prefix. The plugin has no statusline because Claude Code plugins
cannot set one.

</details>

<details>
<summary><strong>Skills only · any compatible agent</strong></summary>

```bash
npx skills add ohm41321/luciazero
```

This installs the 12 skills: no doctrine, reviewer, or hooks.

</details>

<details>
<summary><strong>Classic install · Claude Code or Codex CLI</strong></summary>

```bash
npx luciazero                 # Claude Code
npx luciazero --with-hooks    # Claude Code + hooks/statusline; needs Python 3.9+
npx luciazero codex           # Codex CLI

npx luciazero uninstall
npx luciazero uninstall-codex
```

Pick either plugin or classic for Claude Code so hooks are not wired twice.
Classic installs support `--status`; Codex receives the doctrine and skills but
not Claude-only hooks/statusline. Installers back up name collisions and remove
only exact Luciazero-managed copies on uninstall.

</details>

## Update safely

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
npx skills update                          # every installed skill in the selected scope
npx skills update done -g                 # only the global "done" skill
```

The skills command updates every installed skill in the selected scope, not
only Luciazero; review its prompt before confirming. Use the targeted form when
you only want to refresh one skill.

Claude Code can auto-update the plugin at startup: open `/plugin` →
**Marketplaces** → **luciazero** → **Enable auto-update**. Third-party
marketplaces leave this off by default. For release-only notifications, use
GitHub **Watch → Custom → Releases**.

## Skills at a glance

Invoke `ready` first (`/ready` for slash-based agents, `$ready` in Codex); the
rest activate when their moment arrives.

| Moment | Skill | Result |
|---|---|---|
| Entering a repository | `/ready` | Finds or creates a verify command and proves it can fail |
| Structure or evidence is hard to scan | `/show` | Maps connections, changes, and proof into the smallest useful visual |
| Want Lucia's optional coding voice | `/imouto-mode focus` | Adds a warm, lightly tsundere sibling voice; explicit-only and off by default |
| Before risky, ambiguous, or multi-module work | `/plan` | Fixes scope and observable acceptance evidence |
| A bug survives the first look | `/debug` | Reproduction, hypothesis ledger, regression test |
| Good and bad revisions are known | `/bisect` | Finds the first bad commit in a temporary worktree |
| Before claiming completion | `/done` | Full verify, skeptic review, scope report |
| Work must move elsewhere | `/lucia-relay` | Portable JSON + Markdown state with drift inspection |
| Another agent's work is queued for you (beta) | `/lucia-bus` | Register, read the inbox, claim, work, publish the result through the local Agent Bus |
| Optimizing performance | `/experiment` | Baseline, threshold, controlled measurement |
| Reviewing local verify habits | `/discipline-report` | Time/project-filtered local outcome report |
| After difficult work | `/retro` | Stores reusable lessons and disproved approaches |

`/imouto-mode` never activates itself. Use `focus` (recommended), `on`, or
`off`; the mode applies only to that invocation, writes no config, and leaves
technical evidence plain. Plugin users invoke `/luciazero:imouto-mode focus`;
Codex users invoke `$imouto-mode focus`.

Risky diffs also pass through one read-only `reviewer` with `security`,
`contract`, or `general` focus. Security and contract risk together receive two
separate passes.

## Evidence & limitations

The measurements below are early and model/task-specific. The linked raw rows
and methodology are the source of truth; they are not a promise of uplift on
every repository or model.

<!-- BEGIN GENERATED: benchmark-evidence -->

### Claude results

Snapshots: 2026-08-11 for Haiku and the Sonnet pilot, 2026-09-02 for Sonnet.
All-criteria pass rate generated from checked-in raw rows:

| Claude model | Tasks | Luciazero | Bare | Difference |
|---|---:|---:|---:|---:|
| Haiku†, 10 valid/task | 6 | 36/60 (60%) | 27/60 (45%) | +15pp |
| Sonnet (2026-08-11 pilot), 4–5 valid/task* | 6 | 25/27 (93%) | 16/26 (62%) | +31pp |
| Sonnet, 5 valid/task | 10 | 39/50 (78%) | 23/50 (46%) | +32pp |

The `Luciazero` arm installs the classic pack without hooks; it is not a clean
doctrine-only ablation. Rows are not like-for-like: the 2026-09-02 Sonnet
campaign adds four harder tasks that the 2026-08-11 campaigns never ran, so
compare each row against its own bare arm rather than across models.
*The Sonnet pilot stays preliminary because eight invalid rows leave several
arms at four valid runs; the 2026-09-02 campaign supersedes it with five valid
runs in every cell and no invalid rows. The previously stated `+37pp` top-up
remains retired because its replacement raw rows could not be recovered.

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
only one run per arm per task. See the [full benchmark](https://github.com/ohm41321/luciazero/blob/main/docs/benchmark.md),
[campaign registry](https://github.com/ohm41321/luciazero/blob/main/eval/results/campaigns.json), and
[raw pilot rows](https://github.com/ohm41321/luciazero/blob/main/eval/results/gpt-5.6-terra-medium-pilot-2026-08-12.jsonl).

<!-- END GENERATED: benchmark-evidence -->

## Security & requirements

- Node.js 18+ for the CLI and discipline report.
- Bash for classic installers; Python 3.9+ for hooks and Lucia Relay
  (`install.sh --with-hooks` refuses anything older).
- Core installers, hooks, helpers, and graders are offline. Real behavioral
  evals invoke a model CLI and consume API credit or subscription quota.
- Hooks run commands on your machine. Read them before enabling them.
- Hook telemetry stays local in private per-session state and records aggregate
  turn/Bash wall time plus Bash, verify, and model/user skill counts—never raw
  commands, skill names, or paths.
- Set `LUCIAZERO_VERIFY_CMD` to the repo's exact fast verify command.
- Put `LUCIAZERO_STRICT_VERIFY_CMD` only in personal settings, never in a
  committed repository config. Strict mode fails open on internal errors.
- A repository's committed `.claude/settings.json` cannot configure Luciazero
  at all: every `LUCIAZERO_*` key (and `CLAUDE_CONFIG_DIR`) declared there — in
  the session directory or any ancestor up to the repository root — is refused
  and named once at `SessionStart`. Your own settings still configure it: the
  search stops at the repo root and at `$HOME`, and never reads your global
  `~/.claude/settings.json` or gitignored `.claude/settings.local.json`.
- Windows: the installers and hooks are Bash scripts — run them under WSL.
  `npx luciazero discipline` works in native Node.

See [SECURITY.md](https://github.com/ohm41321/luciazero/blob/main/SECURITY.md) for the complete trust boundary.

## Developing Luciazero

```bash
./test.sh --fast   # intermediate loop: core doctrine/hooks/report/Relay checks
./test.sh          # closeout/CI: full eval, packaging, and install coverage
```

The fast tier is the default intermediate check for this repository; use a
more targeted command when changing a component it does not cover. The default
full tier (also `./test.sh --full`) covers scripts, hook state, Relay, bisect,
plugin/npm manifests, self-proving eval graders, and sandboxed install →
reinstall → uninstall for Claude Code and Codex. CI and `/done` use the full
tier.

More detail:

- [Architecture and trade-offs](https://github.com/ohm41321/luciazero/blob/main/docs/comparison.md)
- [Eval methodology](https://github.com/ohm41321/luciazero/blob/main/eval/README.md)
- [Benchmark results and GPT plan](https://github.com/ohm41321/luciazero/blob/main/docs/benchmark.md)
- [Raw campaign registry](https://github.com/ohm41321/luciazero/blob/main/eval/results/campaigns.json)
- [Experiment log](https://github.com/ohm41321/luciazero/blob/main/docs/experiments.md)
- [Launch kit](https://github.com/ohm41321/luciazero/blob/main/docs/launch-kit.md)
- [Contributing](https://github.com/ohm41321/luciazero/blob/main/CONTRIBUTING.md)
- [Publishing](https://github.com/ohm41321/luciazero/blob/main/docs/publishing.md)
- [Changelog](https://github.com/ohm41321/luciazero/blob/main/CHANGELOG.md)

## Support the project

Luciazero shares its mascot with [Lucia](https://lucia-discord-bot.vercel.app),
a Thai-language Discord bot. If Luciazero saves you review cycles, you can
[support the project here](https://easydonate.app/itsathitz) 💚

## License

[MIT](https://github.com/ohm41321/luciazero/blob/main/LICENSE)

## ภาษาไทย

README ฉบับภาษาไทยเต็ม: [README.th.md](https://github.com/ohm41321/luciazero/blob/main/README.th.md)

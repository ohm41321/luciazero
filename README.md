<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@f10ec1e360be25bed98f48e50dd582fba986e20c/docs/assets/readme-banner-dark.svg">
    <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@f10ec1e360be25bed98f48e50dd582fba986e20c/docs/assets/readme-banner-light.svg" width="100%" alt="Luciazero: make coding agents prove their work. Lucia, the mascot, stands beside a terminal where an agent claims all tests pass, ./test.sh exits 1, the fix lands with a regression test, ./test.sh exits 0, and /done runs full verify, then a revert probe that shows the new test fails without the fix">
  </picture>
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/luciazero"><img src="https://img.shields.io/npm/v/luciazero" alt="npm version"></a>
  <a href="https://www.npmjs.com/package/luciazero"><img src="https://img.shields.io/npm/dw/luciazero" alt="npm weekly downloads"></a>
  <a href="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml"><img src="https://github.com/ohm41321/luciazero/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <a href="https://github.com/ohm41321/luciazero/stargazers"><img src="https://img.shields.io/github/stars/ohm41321/luciazero?style=flat" alt="GitHub stars"></a>
  <a href="https://github.com/ohm41321/luciazero/network/members"><img src="https://img.shields.io/github/forks/ohm41321/luciazero?style=flat" alt="GitHub forks"></a>
  <a href="https://github.com/ohm41321/luciazero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/ohm41321/luciazero" alt="MIT license"></a>
</p>

<div align="center">

**English** · [ภาษาไทย](https://github.com/ohm41321/luciazero/blob/main/README.th.md) · [Website](https://ohm41321.github.io/luciazero/) · [Two-minute film](https://ohm41321.github.io/luciazero/#intro)

</div>

<p align="center">
  <a href="#start-in-30-seconds">Start</a> ·
  <a href="#what-it-protects">What it protects</a> ·
  <a href="#see-the-loop">The loop</a> ·
  <a href="#skills-at-a-glance">Skills</a> ·
  <a href="#keep-work-portable">Relay</a> ·
  <a href="#let-two-agents-hand-work-to-each-other">Agent Bus</a> ·
  <a href="#install">Install</a> ·
  <a href="#evidence--limitations">Evidence</a> ·
  <a href="#security--requirements">Security</a>
</p>

---

Luciazero is the verification and handoff layer for **Claude Code, Codex CLI,
and compatible skill runtimes**. It is for teams that want coding agents to
prove work instead of merely report it. It is a discipline layer, not an agent
runtime.

> Done is proven by a command, not by my judgment. If no verification command
> exists, that is the first bug.

| Job | How |
|---|---|
| **Prove** | A stop hook nudges an agent that stops with edits after its last check, or with that check red; an optional strict gate blocks a red stop. `/done` runs full verify and a skeptic diff pass, adds a revert probe when tests changed, and one independent review when the diff is risky. |
| **Keep&nbsp;scope** | `/done` requires every item to be delivered or named as left out, so dropped scope gets named instead of going silent. |
| **Remember** | `/retro` records dead ends and footguns; `/debug` reads them before the next attempt. |
| **Hand&nbsp;off** | `/lucia-relay` carries evidence, the next action and negative knowledge to another session, agent or machine. |

<p align="center">
  <strong>13 skills</strong> · <strong>Relay fixture 6/6</strong> · <strong>Claude + Codex</strong> · <strong>MIT</strong>
</p>
<p align="center"><sub>Relay 6/6 is a mechanical protocol check; behavioral results are reported separately.</sub></p>

**This checkout is the 3.0.1 tree.** The manifests and the top
[changelog](CHANGELOG.md) entry agree, and this document describes that source.

- 3.0.1 is a fix release. A failing verify no longer silences the stop nudge,
  and files changed through the shell (`sed -i`, a formatter) count as edits.
  The Agent Bus service unit loads on Linux; systemd had refused it since
  2.5.0. The Bash installers handle `CLAUDE.md` and `AGENTS.md` files saved
  with CRLF endings.
- Since 3.0.0 the reviewer agent is `lucia-reviewer`
  (`luciazero:lucia-reviewer` in the plugin), and the stop hook judges a
  command by the program it runs: type checkers, linters and a project's own
  check scripts count, reading a test file does not.
- Its twelve eval fixtures pass offline under `./test.sh`; no real-model
  skills-ablation pilot has run yet.
- Native Windows support, new in 2.7.0, has passed CI on `windows-latest` but
  has not been run on a real Windows machine;
  [the Windows field test](docs/windows-field-test.md) lists what CI does not
  cover.

## Start in 30 seconds

Pick the line for your agent, then start a new session.

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
use `$ready`). This path intentionally does not install the doctrine,
`lucia-reviewer`, or hooks. [Install](#install) compares every path.

## What it protects

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@40d27aae08150e5fab87ca14af1cf7e8569cd0a1/docs/assets/film-false-green.gif" width="720" alt="Asked to fix the login bug, an agent answers Fixed. All tests pass. Done. The green check shows 0 runs, the film asks Actually tested?, and the check shatters">
  <br><sub>The first failure mode below, from the <a href="https://ohm41321.github.io/luciazero/#intro">film</a>.</sub>
</p>

| Failure mode | Mechanism |
|---|---|
| “Done” without running a check | Stop-hook nudge; optional strict gate blocks a red stop |
| `cat test.sh` counted as testing | Detection reads the program a command runs; optional exact `LUCIAZERO_VERIFY_CMD` |
| Tests weakened to reach green | Doctrine rule 3 + the `/done` review; an opt-in suppression-guard hook example |
| New tests that pass without the fix | `revert-probe.cjs` runs them against the old code |
| Scope silently dropped | `/done` requires every item delivered or named as left out |
| The same dead end repeated later | `/retro` records it; `/debug` reads it first |
| Context lost between agents | `/lucia-relay` transfers evidence, next action, and negative knowledge |

Mechanical guarantees run in `test.sh`; behavioral claims are measured by the
[eval harness](https://github.com/ohm41321/luciazero/blob/main/eval/README.md).

## See the loop

The two-minute film, an animation: a false green, the loop that catches it,
`/bisect`, a handoff between agents, and `/done` proving that a test catches
the bug. The pass rates it shows are for Claude Sonnet, using the classic pack
without hooks; see [Evidence & limitations](https://github.com/ohm41321/luciazero#evidence--limitations).

https://github.com/user-attachments/assets/e18f6092-12ae-4113-bfec-47765956bb49

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@40d27aae08150e5fab87ca14af1cf7e8569cd0a1/docs/assets/film-loop.gif" width="720" alt="The loop: plan, change, verify fails with exit 1, fix, and verify passes with exit 0; then Done is proven by a command, not by my judgment">
  <br><sub>The loop, from the <a href="https://ohm41321.github.io/luciazero/#intro">film</a>.</sub>
</p>

In a session, the statusline shows where the loop is:

```text
✎ unverified   → edits happened after the last check
❌ verify RED  → the latest check failed
✅ verify 3m   → the latest check passed three minutes ago
```

Watch it change on your machine. Both scripts use throwaway directories and
exercise the real implementation; no model or API is required.

```bash
bash docs/assets/statusline-demo.sh   # the shipped hook driver and statusline
bash docs/assets/relay-demo.sh        # a cross-session handoff
```

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
| Another agent's work is queued for you (beta) | `/lucia-bus` | Register, read the inbox, claim, work, publish the result through the local Agent Bus ([setup and demo](docs/agent-bus.md)) |
| Want two agent sessions talking (beta) | `/lucia-chat` | Shows what is waiting, opens one window per agent, and optionally watches the conversation |
| Optimizing performance | `/experiment` | Baseline, threshold, controlled measurement |
| Reviewing local verify habits | `/discipline-report` | Time/project-filtered local outcome report |
| After difficult work | `/retro` | Stores reusable lessons and disproved approaches |

`/imouto-mode` never activates itself. Use `focus` (recommended), `on`, or
`off`; the mode applies only to that invocation, writes no config, and leaves
technical evidence plain. Plugin users invoke `/luciazero:imouto-mode focus`;
Codex users invoke `$imouto-mode focus`.

Risky diffs also pass through one read-only `lucia-reviewer` with `security`,
`contract`, or `general` focus. Security and contract risk together get one
pass that names both focuses, never two. A small diff with no routed risk gets
no review.

Instruction files grow. [context-weight](https://github.com/ohm41321/context-weight),
a separate skill by the same author, weighs what `CLAUDE.md`, `AGENTS.md` and
the skill listing cost before any work starts, then slims them and proves no
line was lost.

## Keep work portable

`/lucia-relay` transfers decisions and evidence instead of dumping a chat
transcript. Session A writes canonical `LUCIA_RELAY.json` plus a generated
human view; session B checks trusted repository identity, HEAD, and manifest
digest, reads the exact next action and negative knowledge, re-runs every
approved verification command in its own harness, then explicitly consumes.

The whole exchange is two commands per side:

```bash
# producer (session A)
luciazero relay draft --write     # add --recipient cross-machine --base <base> to publish the transfer tag
                                  # ...fill the JSON, then:
luciazero relay finalize          # validates, renders the human view; cross-machine also prints
                                  # the trusted envelope (--envelope-out <file> saves it)

# receiver (session B)
luciazero relay inspect --trusted-envelope <file>
                                  # ...re-run the evidence, then:
luciazero relay consume --verified --trusted-envelope <file>
```

Same-machine receivers may use local paths and schema 1/2. Cross-machine schema
3 is created only after commit and push: it publishes a commit-named transfer
tag and records a sanitized clone URL, head/base OIDs, committed changed files,
and inline knowledge.
The receiver supplies the expected route, HEAD, and manifest digest independently, so a
forged artifact cannot downgrade validation. Detached checkouts are supported;
Relay never executes artifact commands. The receiver runs them in its coding
harness and passes `consume --verified` only after every result matches. The
envelope is only trusted when it arrived through an authenticated channel and
is named explicitly from outside the clone; one shipped beside the artifact is
refused.

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/ohm41321/luciazero@40d27aae08150e5fab87ca14af1cf7e8569cd0a1/docs/assets/film-relay.gif" width="720" alt="A Lucia Relay reaches a new session on a new machine. Re-running its evidence gives the same failure it recorded; after a fix to price(), the re-run passes with exit 0">
  <br><sub>A relay arriving, from the <a href="https://ohm41321.github.io/luciazero/#intro">film</a>.</sub>
</p>

The film is an animation. The [relay demo](https://github.com/ohm41321/luciazero/blob/main/docs/assets/relay-demo.sh)
runs the shipped implementation in a temporary Git repository. CI's `relay-transfer` fixture scores the complete
reference 6/6 and rejects a generic Markdown handoff (1/6) plus a
content-complete but stale fingerprint (5/6). Those are mechanical protocol
checks—not model-uplift results. See the [method and limits](https://github.com/ohm41321/luciazero/blob/main/docs/benchmark.md#skill-protocol-evidence).

## Let two agents hand work to each other

**Agent Bus is beta, opt-in, and checkout only.** It does not come with
`npx luciazero` and never starts during a normal npm, plugin, or skills-only
install. After the one-time checkout setup, the ordinary path is one command
in each agent window:

```text
window A                              window B
$ lucia claude                       $ lucia codex

task_create + message_send  ───────► queued durably in the local bus
                             nudge ─► check your bus inbox (1 new task from claude)
                                      message_ack + task_claim
                                      work + verify
                                      artifact_publish + task_complete
result in the inbox          ◄─────── message_send
```

The daemon starts when the first `lucia` session needs it, each CLI receives
an MCP configuration for that run only, and the user's central Claude or
Codex configuration is not edited. Messages and task state stay in local
SQLite; peer message text is never typed into another session's prompt. The
proxy types only the daemon-built inbox notice after the provider is quiet.

Try the shipped fake-provider demo—no model, login, or quota required:

```bash
bash docs/assets/agent-bus-demo.sh
```

To open real Claude Code and Codex sessions, first follow the one-time
[checkout setup](docs/agent-bus.md#start-here), then run `lucia claude` and
`lucia codex`. See the [Agent Bus guide](docs/agent-bus.md) for worktree
ownership, `--no-nudge`, security boundaries, and cleanup.

Inside the Bus workflow, the skill stops before risky work: delete, deploy,
production access, spending, force-push, public-contract changes, and scope
expansion need a single-use nonce you mint in your own terminal. No bus tool
can create one, and a nonce put into a bus message, task, or artifact is
scrubbed or refused ([approvals](docs/agent-bus.md#approvals)). This records
approval provenance; it is not a host sandbox against another process running
as you. The project trust boundary is in
[SECURITY.md](https://github.com/ohm41321/luciazero/blob/main/SECURITY.md).

## Install

Luciazero supports Claude Code, Codex CLI, and compatible agents. Each path
carries a different part of the pack:

| Path | Doctrine | 13 skills | `lucia-reviewer` | Hooks + statusline |
|---|:---:|:---:|:---:|:---:|
| Claude Code plugin | ✓ | ✓ | ✓ | hooks only |
| Classic, Claude Code | ✓ | ✓ | ✓ | with `--with-hooks` |
| Classic, Codex CLI | ✓ | ✓ | ✓ (as a skill) | — |
| Codex CLI plugin | ✓ | ✓ | — | hooks only |
| Skills only | — | ✓ | — | — |

<details>
<summary><strong>Recommended · Claude Code plugin</strong></summary>

Carries the doctrine, all skills, `lucia-reviewer`, and verify-tracking hooks:

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

This installs the 13 skills: no doctrine, `lucia-reviewer`, or hooks.

</details>

<details>
<summary><strong>Codex CLI plugin · doctrine, skills and hooks</strong></summary>

```bash
codex plugin marketplace add ohm41321/luciazero
codex plugin add luciazero@luciazero
```

This carries the doctrine, the 13 skills and the verify-tracking hooks, but not
`lucia-reviewer` or a statusline. Codex tells a hook what a command printed but
not whether it passed, so under Codex a verify run counts as run, never as
green, there is no red nudge, and a strict gate runs its command at stop
instead of trusting an earlier run. Pick either this plugin or
`npx luciazero codex`: both load every skill twice. Update with
`codex plugin marketplace upgrade luciazero`, remove with
`codex plugin remove luciazero@luciazero`. Codex also refreshes a Git
marketplace on its own, so restart a long-running Codex session after an
update.

</details>

<details>
<summary><strong>Classic install · Claude Code or Codex CLI</strong></summary>

Install the command globally once, without `sudo`:

```bash
npx luciazero@latest global-install
```

This installs the CLI under `~/.local/npm` and, after confirmation, adds its
bin directory to your zsh or bash PATH. Start a new shell, then use the global
command from any directory:

```bash
luciazero                 # Claude Code
luciazero --with-hooks    # Claude Code + hooks/statusline; needs Node 18+
luciazero codex           # Codex CLI

luciazero uninstall             # remove the Claude classic files
luciazero uninstall-codex       # remove the Codex classic files
luciazero global-status         # check the global command and PATH
luciazero global-uninstall      # remove the command and its exact PATH block
```

For a one-off install without keeping the command, `npx luciazero@latest`
continues to work. Automation may pass `global-install --yes`; interactive use
asks before installing the package and changing a shell startup file.
On Windows, `global-install` uses npm's own global prefix
(`%APPDATA%\npm` unless you moved it) and edits no startup file or Path;
it and `global-status` say so if that prefix is not on your Path.

Pick either plugin or classic for Claude Code: installing both loads every
skill and `lucia-reviewer` twice, even though hooks and doctrine deduplicate.
Classic installs support `--status`; the classic Codex install carries the
doctrine and skills but no hooks (the Codex plugin carries them). Installers back up name collisions and remove
only exact Luciazero-managed copies on uninstall.

</details>

## Update safely

Luciazero never changes classic or Codex files in the background. Each install
channel has its own updater:

| Installed with | Update with |
|---|---|
| Classic or Codex | `luciazero update` (`luciazero check-update` only reads) |
| Claude Code plugin | `claude plugin update luciazero@luciazero`, then `/reload-plugins` |
| Codex CLI plugin | `codex plugin marketplace upgrade luciazero`, then a new session |
| Skills only | `npx skills update`, or `npx skills update done -g` for one skill |

```bash
luciazero check-update   # read-only; contacts npm only now
luciazero update         # updates every detected classic/Codex install
```

If you chose the one-off path, use the same commands through
`npx luciazero@latest` instead.

`update` preserves whether the Claude classic install uses hooks, repairs stale
managed files, starts no fresh install when it cannot find one, and stops on a
known newer version or malformed version metadata. Start a new agent session
afterward.

The skills command updates every installed skill in the selected scope, not
only Luciazero; review its prompt before confirming. Use the targeted form when
you only want to refresh one skill.

Claude Code can auto-update the plugin at startup: open `/plugin` →
**Marketplaces** → **luciazero** → **Enable auto-update**. Third-party
marketplaces leave this off by default. For release-only notifications, use
GitHub **Watch → Custom → Releases**.

## Evidence & limitations

The measurements below are early and model/task-specific. The linked raw rows
and methodology are the source of truth; they are not a promise of uplift on
every repository or model.

<!-- BEGIN GENERATED: benchmark-evidence -->

### Claude results

Snapshots: 2026-08-11 for Haiku and the Sonnet pilot, 2026-09-02 for Sonnet.
All-criteria pass rate generated from checked-in raw rows:

| Claude model | Tasks | Luciazero | Bare | Difference | Cost per run | Time per run |
|---|---:|---:|---:|---:|---:|---:|
| Haiku†, 10 valid/task | 6 | 36/60 (60%) | 27/60 (45%) | +15pp | $0.08 vs $0.07 | 54 s vs 48 s |
| Sonnet (2026-08-11 pilot), 4–5 valid/task* | 6 | 25/27 (93%) | 16/26 (62%) | +31pp | $0.21 vs $0.18 | 38 s vs 33 s |
| Sonnet, 5 valid/task | 10 | 39/50 (78%) | 23/50 (46%) | +32pp | $0.39 vs $0.22 | 93 s vs 47 s |

The `Luciazero` arm installs the classic pack without hooks; it is not a clean
doctrine-only ablation. Rows are not like-for-like: the 2026-09-02 Sonnet
campaign adds four harder tasks that the 2026-08-11 campaigns never ran, so
compare each row against its own bare arm rather than across models.
*The Sonnet pilot stays preliminary because eight invalid rows leave several
arms at four valid runs; the 2026-09-02 campaign supersedes it with five valid
runs in every cell and no invalid rows. The previously stated `+37pp` top-up
remains retired because its replacement raw rows could not be recovered.

Two tasks carry most of the Sonnet difference: `merge-conflict` and `pipeline`
give 10 of its 16 extra passing runs. No uncertainty interval is computed, so
read the difference as a direction more than a size. Most of the difference is a
regression test left behind: counting every criterion except the three that ask
for a test that fails without the fix (`regression-red`, `regression-test`,
`tests-bite`), the arms pass 40/50 vs 36/50. Doctrine rule 4 asks for that test,
so the measured gain is mostly in leaving one, not in fixing more bugs.
`relay-transfer` grades Luciazero's own relay format (`LUCIA_RELAY.json`), which
its prompt never names, so it favors the Luciazero arm; without it the Sonnet
difference is +31pp. Cost per run is the mean API price the CLI reported; time
per run is the mean wall-clock time (medians for Sonnet: 45 s vs 40 s).

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

| You need | For |
|---|---|
| Node.js 18+ | The CLI, the discipline report, the hooks and status line, and the helpers `/ready`, `/done` and `/bisect` run (`node <skill-dir>/scripts/*.cjs`; the old `.sh` names are wrappers that need Node too) |
| Bash | The classic installers on macOS and Linux |
| Claude Code 2.1.139+ | The hooks, which are wired in exec form (`install.sh --with-hooks` refuses a Node older than 18) |
| Python 3.9+ | Lucia Relay: `python3 <skill-dir>/scripts/relay.py`, or `python` / `py -3` on Windows |
| Python 3.10+ and a checkout | The Agent Bus daemon (beta, opt-in) |

The Agent Bus daemon is not in the npm payload and `npx luciazero` never
starts it. From a checkout, `./install.sh` (on Windows, `node bin\luciazero.js`)
adds the `luciazero-agentd` and `lucia` launchers to `~/.claude/bin`
(`LUCIAZERO_BIN_DIR` chooses another directory, which later runs remember),
and `luciazero-agentd service install` runs the daemon under launchd, systemd
`--user`, or Task Scheduler on Windows. See [docs/agent-bus.md](docs/agent-bus.md).

- Core installers, hooks, helpers, and graders are offline. Real behavioral
  evals invoke a model CLI and consume API credit or subscription quota.
- Hooks run commands on your machine. Read them before enabling them.
- Hook telemetry stays local in private per-session state and records aggregate
  turn/Bash/verify wall time, redundant-green counts, and Bash, verify, and
  model/user skill counts. Each stats row names the project by a hash and by
  its folder's name, for the report—never raw commands, skill names, or
  paths. Older rows
  without verify timing are reported as not measured, not zero.
- Put `LUCIAZERO_STRICT_VERIFY_CMD` only in personal settings, never in a
  committed repository config. Strict mode fails open on internal errors. It
  runs at stop unless that same command is already green since the last edit,
  for at most `LUCIAZERO_STRICT_TIMEOUT` seconds (default 120); a run that
  times out decides nothing, and the nudge says it timed out.
- A repository's committed `.claude/settings.json` cannot configure Luciazero
  at all: every `LUCIAZERO_*` key (and `CLAUDE_CONFIG_DIR`) declared there — in
  the session directory or any ancestor up to the repository root — is refused
  and named once at `SessionStart`. A `.claude/settings.local.json` that git
  tracks is refused the same way. Your own settings still configure it: the
  search stops at the repo root and at `$HOME`, and never reads your global
  `~/.claude/settings.json` or an untracked `.claude/settings.local.json`.
- Windows runs natively, without WSL (CI-tested only; see the top of this
  page): `npx luciazero` installs through a Node port of the installers,
  `global-install` uses npm's own global prefix, and the hooks, status line
  and skill helpers are Node. There, the programs
  Luciazero starts by name — git, node, npm, Python, a provider CLI,
  PowerShell, schtasks — are looked up on PATH alone, never in the working
  directory, where Windows would look first.

<details>
<summary><strong>What the hook counts as a verify run</strong></summary>

- By default the hook counts a command as a verify run by the program it
  runs. That covers test runners (`pytest`, `npm test`, `node --test`,
  `go test`, `./test.sh`), type checkers (`tsc`, `mypy`), linters (`eslint`,
  `ruff check`, `shellcheck`) and a project's own check scripts
  (`npm run check`, `python scripts/check-site.py`). Reading a test file does
  not count, and neither does running a program with only `--help` or
  `--version`. Editing a file in a temporary directory outside your project
  and outside any git work tree, such as an agent's scratchpad, does not
  re-arm the nudge.
- A file a shell command changes (`sed -i`, a heredoc, a formatter, a commit
  hook) counts as an edit too. Before each verify run and at stop the hook
  asks git which files changed while one of the session's own shell commands
  ran, after its last verify ended; documentation, ignored files and what the
  verify itself wrote do not count, and neither does another session's edit
  made between two of its commands. A command that tests and then edits
  (`npm test && sed -i ...`) leaves that edit unverified. Outside a git work
  tree, shell writes are not tracked.
- A stop whose last verify of the session's edits failed, or could not find
  its command, is nudged once too, until a run passes. Claude Code only:
  Codex gives hooks a command's output but not whether it passed.
- To count only the repo's own verify commands, set `LUCIAZERO_VERIFY_CMD` in
  personal settings, one command per line (`./test.sh --fast` and
  `./test.sh`). A command counts when it runs one of them, after a `cd`, a
  wrapper such as `timeout`, or a variable assignment too. List the full tier
  as well, or the closeout run `/done` asks for is nudged.
- Other knobs, all read from personal settings only: `LUCIAZERO_VERIFY_REGEX`
  replaces the default detection with an extended regex tried on each line of
  the command; `LUCIAZERO_DOC_REGEX` (default `\.(md|markdown|rst)$`) names the
  edited files that are documentation and never need a verify;
  `LUCIAZERO_RELAY_STALE_DAYS` (default 7) is when a `LUCIA_RELAY.json` is
  called stale at session start.
- `LUCIAZERO_EDIT_DIAG=1` in your own shell makes the hook keep one line per
  edit event in its state directory (tool name, opaque key, whether
  `file_path` was missing, empty or present, its suffix, under cwd or not,
  counted or not — never the path or the content), for finding out what
  re-armed the nudge when no visible edit did.

</details>

See [SECURITY.md](https://github.com/ohm41321/luciazero/blob/main/SECURITY.md) for the complete trust boundary.

## Developing Luciazero

```bash
./test.sh --discipline  # editing a hook, the report or a skill prompt: ~30 s
./test.sh --fast        # intermediate loop: adds Relay, bisect, evidence
./test.sh --bus         # editing agentd/ or the Bus scripts: daemon suite and fake-provider gates
./test.sh               # closeout/CI: full eval, packaging, and install coverage
LZ_TEST_TIMINGS=1 ./test.sh --fast   # plus one `TIMING gate=<name> seconds=<n>` per gate on stderr
scripts/test-timings.sh --fast       # same run, and keeps stdout/stderr/meta under .test-timings/
scripts/test-timings.sh --report     # median and p95 per gate over the green samples kept so far,
                                     # and the commits they came from (a warning when they span more than one)
```

The discipline tier is the loop command for the enforcement pack, the
discipline report and the prompts: syntax and ShellCheck over every shipped
script (plus a bash 3.2 parse when `LZ_BASH32` names one; CI always runs it),
the prompt and doctrine contracts, and the hook state machine, nothing else. The fast tier is the default intermediate check for everything
else; use a more targeted command when changing a component it does not cover. The default
full tier (also `./test.sh --full`) covers scripts, hook state, Relay, bisect,
plugin/npm manifests, self-proving eval graders, and sandboxed install →
reinstall → uninstall for Claude Code and Codex. CI and `/done` use the full
tier. `test.sh` is the dispatcher; the checks live in `tests/gates/*.sh`, one
file per subsystem, sourced in order — read the gate a change touches. In the
full tier the tiers, eval, packaging, install, codex-install and parity gates
run at once, each in its own subshell, with their output replayed in order so it
reads as the serial run; `LZ_TEST_PARALLEL=0` runs them one at a time.

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

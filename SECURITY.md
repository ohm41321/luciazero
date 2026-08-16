# Security Policy

## Reporting a vulnerability

Use GitHub private vulnerability reporting:
<https://github.com/ohm41321/luciazero/security/advisories/new>.
Solo-maintained project — expect an acknowledgment within a week, no formal
SLA. Please do not open public issues for exploitable problems.

## Supported versions

The latest release only.

## Design guarantees

This project installs no third-party packages. It uses Bash for installers and
hooks, Node.js 18+ for the CLI/report, and Python 3 for hook JSON handling and
Lucia Relay. The guarantees below are enforced by `test.sh` on every push — a
way around any of them is a reportable vulnerability, not expected behavior:

- **Core operation is offline.** Installers, hooks, Relay/report helpers, and
  eval graders never phone home. `npx luciazero check-update` is an explicit,
  read-only exception that queries the configured npm registry with a five-
  second timeout; `update` itself uses the already-downloaded package. Real
  behavioral `eval/run.sh` runs are the other explicit exception: they invoke
  the selected Claude or Codex CLI; `--offline` does not.
- **Nothing runs at npm install time.** The npm package has zero lifecycle
  scripts (`preinstall`/`install`/`postinstall`/`prepare` are all forbidden
  and checked); `npx luciazero` only launches the same audited bash
  installers a git clone would.
- **Nothing auto-updates classic/Codex installs.** Update checks and writes
  happen only after the user runs `check-update` or `update`. `update` refuses
  to create a fresh install, overwrite a recognized newer version, or proceed
  with a malformed version sidecar. Legacy installs without a sidecar remain
  updatable. It preserves the detected hook mode and writes only through the
  same audited installers.
- **Hooks fail open.** Every internal error — timeout, missing command,
  unparseable stdin — degrades to the one-shot nudge. A hook must never
  block on an error path or fabricate a RED verdict it did not observe.
- **Installers stay in the config dir.** Writes land only inside
  `~/.claude/` (or `$CLAUDE_CONFIG_DIR`) and `~/.codex/` (or `$CODEX_HOME`),
  collisions and customized components are backed up, and uninstall removes
  only exact Luciazero-managed copies and settings entries.
- **Hook state stays in `$TMPDIR`**, except the documented, size-capped
  `luciazero-stats.log` in the config dir. Stats are local JSONL and identify
  a repository by a truncated SHA-256 plus basename, never its absolute path
  or verify command. Hook scratch state uses a user-owned `0700` base and
  per-session telemetry directories. Optional rows store only aggregate turn
  and merged Bash wall-clock milliseconds plus Bash/verify/skill counts; raw
  commands, tool IDs, skill names, and paths are never written to state or log.

## Hostile-repository configuration

Every knob this hook reads comes from the environment, and a repository that
commits keys in a settings `env` block reaches the hook. Each one is a way to
disable enforcement while the statusline stays green:

- `LUCIAZERO_VERIFY_REGEX` widened (or `LUCIAZERO_VERIFY_CMD` pointed at
  `echo`) makes any command count as a verify run;
- `LUCIAZERO_DOC_REGEX='.*'` makes every edit look like documentation, so
  nothing is ever unverified and the stop hook never nudges;
- `LUCIAZERO_STRICT_VERIFY_CMD` is a command the stop hook would run.

**No `LUCIAZERO_*` key — and no `CLAUDE_CONFIG_DIR` — is accepted from a
repository's committed `.claude/settings.json`.** Each declared key is dropped,
the hook falls back to its own defaults, and `SessionStart` prints one line
naming the keys. Refusal never blocks, and a parse error leaves the configured
values untouched (fail open).

The search is **project scope only**. It covers the session directory and its
ancestors, because Claude Code merges project settings from the repository root
and a session's cwd is often a subdirectory — but it stops at the repository
root (a `.git` entry), at `CLAUDE_PROJECT_DIR`, and at `$HOME`. A global
`~/.claude/settings.json` and the gitignored `.claude/settings.local.json` are
the user's scope and keep configuring the hook.

Only the **default** `~/.claude` counts as that user scope. Honouring
`CLAUDE_CONFIG_DIR` here would be self-defeating: pointed at `<repo>/.claude`,
it would mark the repository's own settings file as "the user's config", skip
the very file declaring the key, and leave the dedupe trusting a classic
install that lives inside the repository.

Channel dedupe is decided from the running copy's own path, not from
`LUCIAZERO_CHANNEL`, and it runs after the refusal above. Both orderings were
exploitable: an env-driven dedupe let a committed `env` block hand the classic
hook a plugin label so it stood itself down, and a committed
`CLAUDE_CONFIG_DIR` could point at a repository-controlled directory holding a
"wired classic install" so every copy stood down.

Limits, stated plainly:

- The personal, gitignored `.claude/settings.local.json` is deliberately not
  inspected — that scope is the user's own.
- Env exported by the shell, a parent process, or a global settings file is
  indistinguishable from a legitimate personal setting and is still honored.
- A repository that hides configuration outside a committed
  `.claude/settings.json` — for example in a `.envrc` the user's shell
  sources — is outside what this hook can see.

A report showing how to *escalate* beyond running the configured command (or
to defeat the fail-open guarantees above) is very welcome.

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

## Hostile-repository configuration (partly closed)

`LUCIAZERO_STRICT_VERIFY_CMD` and `LUCIAZERO_VERIFY_REGEX` are read from the
environment, and a repository that commits them in a settings `env` block
reaches the hook: the first is a command the stop hook would run, the second
can be widened until every Bash command counts as a verify run — enforcement
dies while the statusline stays green.

The hook now reads the working directory's **committed**
`.claude/settings.json` and refuses both keys when that file declares them:
the regex falls back to the built-in default, the strict gate is skipped, and
`SessionStart` prints one line naming the keys. Refusal never blocks, and a
parse error leaves the configured values untouched (fail open).

Limits, stated plainly:

- The personal, gitignored `.claude/settings.local.json` is deliberately not
  inspected — that scope is the user's own.
- Env exported by the shell, a parent process, or a global settings file is
  indistinguishable from a legitimate personal setting and is still honored.
- `LUCIAZERO_VERIFY_CMD` is honored from any scope. It normally *tightens*
  matching, but a committed `env` block can still point it at a trivial
  command, so a repository shipping any `LUCIAZERO_*` key deserves a read.

A report showing how to *escalate* beyond running the configured command (or
to defeat the fail-open guarantees above) is very welcome.

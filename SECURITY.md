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
  eval graders never phone home. Real behavioral `eval/run.sh` runs are the
  explicit exception: they invoke the selected Claude or Codex CLI;
  `--offline` does not.
- **Nothing runs at npm install time.** The npm package has zero lifecycle
  scripts (`preinstall`/`install`/`postinstall`/`prepare` are all forbidden
  and checked); `npx luciazero` only launches the same audited bash
  installers a git clone would.
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
  or verify command.

## Known sharp edge (documented, by design)

`LUCIAZERO_STRICT_VERIFY_CMD` is read from the environment, and the hook
cannot tell which settings scope set it — a repository that commits it in a
settings `env` block reaches the hook. The README says to treat such a
repository as hostile and remove the variable before working there. A report
showing how to *escalate* beyond running the configured command (or to defeat
the fail-open guarantees above) is very welcome.

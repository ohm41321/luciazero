# Contributing

## Verify

```bash
./test.sh
```

Must pass before any PR. It covers:

- shell syntax, shellcheck, frontmatter, settings JSON, and doctrine size;
- hook state transitions, Lucia Relay, safe bisect, and regression-test honesty;
- every eval grader plus the synthetic `eval/run.sh --offline` path; and
- install → reinstall → uninstall for Claude Code and Codex in sandbox config
  directories, including the opt-in enforcement pack.

CI runs the same command. Real behavioral eval runs are separate and manual:
they invoke the selected Claude or Codex CLI and consume API credit or
subscription quota.

## Rules of the repo

These mirror the doctrine the repo ships — changes that break them will be
declined:

- **The doctrine stays short — and `test.sh` enforces it.** Every line of
  `claude/luciazero.md` is loaded into context on every turn of
  every session for every user. A word-count ceiling in `test.sh` turns
  growth into a red build: cut a word to add a word. The doctrine's text
  also stays platform-neutral (no Claude-only vocabulary) because it ships
  verbatim to Codex.
- **The skill stays language-agnostic.** `/ready` detects; it
  never assumes an ecosystem. No "run pytest" without first checking the
  repo is Python.
- **Component catalogs are authoritative.** When adding or removing a skill,
  compatibility alias, or Claude agent, update `skills/catalog.txt`,
  `skills/aliases.txt`, or
  `claude/agents/catalog.txt`. Install, status, uninstall, and `test.sh` read
  them; the test rejects inventory drift across both harnesses.
- **Scripts stay idempotent and contained.** `install.sh`/`uninstall.sh`
  must be safe to run twice, must back up before editing, and must never
  write outside the Claude config dir.
- **Example hooks ship inert.** Nothing in `examples/` may execute
  anything as shipped.
- **The hooks must parse under bash 3.2** — the `/bin/bash` on stock macOS.
  Never put a here-document inside a command substitution there: 3.2 rejects
  the whole file at load time and blames an unrelated later line, so the pack
  fails silently instead of loudly. `test.sh` blocks the construct in the
  hooks, and `LZ_BASH32=/path/to/bash-3.2 ./test.sh` parses every script with
  the real interpreter.
- **Real hooks are opt-in and fail open.** The enforcement pack installs
  only via an explicit `--with-hooks`, must never block work when broken,
  and its settings.json edits must be additive, idempotent, and fully
  reversed by `uninstall.sh`. The strict gate is a second, separate opt-in
  (an env var the user sets personally) and even it fails open on every
  internal error — only a genuinely red verify may block, once.
- **Eval tasks prove their own graders.** `test.sh` auto-discovers
  `eval/tasks/*/`; a task ships with `PROMPT.md`, `project/`, `reference/`
  (grader passes), and a `gamed/` cheat tree (grader rejects), and its
  grader speaks the `CRIT <id> pass|fail` + `SCORE n/m` contract. A new
  grading criterion without a fixture that proves it can fail will be
  declined — an untested grader manufactures fake eval deltas.

## Releasing

1. Update `CHANGELOG.md` (move entries from Unreleased, set the date) AND
   bump `.claude-plugin/plugin.json` + `package.json` to the same version —
   `./test.sh` fails on any mismatch, and the release workflow runs it.
2. `git tag vX.Y.Z && git push --tags` — the release workflow verifies,
   builds the zip, and publishes a GitHub Release.

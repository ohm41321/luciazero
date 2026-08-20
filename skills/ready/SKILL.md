---
name: ready
description: Make an unfamiliar repository agent-ready with a verify command, smoke tests, guardrails, and project notes. Use for repository setup, agentic engineering, verify commands, hooks, or allowlists; skip when verification and scope are already clear.
---

# Ready

Leave the repository with one unattended command that returns a meaningful exit
code, plus only the guardrails needed for future agents to self-verify. Detect
the stack; do not assume it. Run every artifact you add.

## 1. Detect

Run the bundled scan first:

```
<this-skill-dir>/scripts/detect.sh <repo-root>
```

It finds candidates, not truth; open flagged files and interpret CI matrices or
unusual build systems yourself. Inspect in this order:

1. CI config: use what CI runs.
2. Manifests and runners: package scripts, pyproject/tox/nox, Make/just,
   Cargo/go/Gradle/composer.
3. README, CONTRIBUTING, CLAUDE.md, AGENTS.md, and docs; record docs/CI drift.
4. Existing test directories and naming conventions.

Report run/test/lint/typecheck/build/git as command or `MISSING`. If this is not
a Git repository, propose `git init` but ask first.

## 2. Establish verification

Reuse the existing verify path. If none exists, create the smallest entrypoint
in the repository's native convention.

The command must:

- exit non-zero on failure and run unattended;
- work offline without credentials, GPU, network, or secrets;
- use installed project tooling and avoid watch mode;
- stay quiet on success and be documented for humans.

Time it once. Use one tier when the suite is already quick. When slow checks
would cripple the edit loop, define:

- `verify`: lint/typecheck/unit or smoke coverage, normally under ~60 seconds;
- `verify-full`: integration/build/slow coverage, required at closeout and PR.

Run `verify` on every edit loop; run `verify-full` at closeout and before a PR.

For monorepos, prefer a repo-owned `verify-changed` backed by the workspace
dependency graph, with the root full suite as fallback. Read
[references/smart-verification.md](references/smart-verification.md) before
creating it and document its base revision and fallback.

For Claude Code enforcement-pack users, ask first before offering exact-match
tracking in the personal, gitignored `.claude/settings.local.json`:

```json
{"env":{"LUCIAZERO_VERIFY_CMD":"<fast command derived from CI>"}}
```

Show the JSON before writing it. Never commit this variable in
`.claude/settings.json`; repository-controlled hook configuration is hostile.
This setting caches CI truth; update it whenever CI's verify command changes.
Skip hook setup on harnesses without hooks.

## 3. Add smoke tests only when absent

Add 3–6 small tests for catastrophic failures, not pretend coverage. Choose the
most relevant:

- core input/output shape and impossible null/NaN values;
- serialize/deserialize or save/load round trip;
- import, CLI `--help`, or one request through a framework test client;
- model/config/migration load plus one operation;
- the reported bug as a red-before-fix regression.

Use commit-sized fixtures, never the user's real data paths. Avoid real ports;
if a process is unavoidable, enforce a hard timeout and cleanup. Label these as
smoke tests.

## 4. Add only paying guardrails

Claude hooks/settings are not portable; on Codex or another harness, put
necessary constraints in AGENTS.md instead.

Prefer existing deterministic tools:

1. formatter/linter after writes;
2. source-to-derived regeneration;
3. denial for secrets, production config, and live deploy/model pointers;
4. allowlisting read-only and verify commands.

Keep shared settings project-scoped and personal settings gitignored. Show the
exact hook command before installation. Never add a hook that deploys, pushes,
deletes, or writes outside the repository.

## 5. Record project knowledge

Extend the notes file already used; if neither exists, create the current
harness's file and point the other name to it. Record only facts code search
cannot reveal:

- verify commands and coverage;
- non-obvious source-of-truth or architecture constraints;
- footguns, measured null results, and required regeneration;
- the location of deeper documentation.

Do not duplicate the tree, history, or grep-able facts. Every line becomes
future context cost.

## 6. Prove the loop

- **Flake check:** run the fast tier twice. If only one slow tier exists, run it
  once and state that limitation. A non-repeatable green is not trusted.
- **Red check:** record a covered file, line, and original text; make one
  deliberate break, prove verify fails, then restore exactly that edit. Do not
  use `git checkout` on a file with user changes, and never use broad
  `git stash`. New untracked tests require explicit restoration too.
- Run the final full tier after restoration.

Report the command(s), what each covers and does not cover, files added, and
anything deliberately left out.

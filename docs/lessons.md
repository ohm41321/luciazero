# Debugging lessons

## a bound session lost its own credential fifteen hours into its work

cause: `BINDING_TTL_SECONDS = 12 * 3600` was enforced on age alone -- `resolve_credential` proved the terminal was still alive on every request and then expired the binding anyway, because nothing renewed one that was being used. Every bus call in that session answered `requires re-authorization (token expired)`, and no tool in the session could win the credential back | proven-by: `python3 -m unittest tests.test_identity` in `agentd/` -- red first, as `ImportError: cannot import name 'BINDING_MAX_LIFETIME_SECONDS' from 'luciazero_agentd.store'` and then the three renewal cases; green after (`Ran 42 tests`, `OK`) | fix: migration 9 stores each binding's own window, and `resolve_credential` pushes expiry back once the terminal is proved alive, never past `BINDING_MAX_LIFETIME_SECONDS` from when the binding was created | date: 2026-09-06

## a test asserted whichever launcher form the machine happened to have

cause: `conversation_plan` called `launcher()` and `launcher_in()` without forwarding the `which` lookup those helpers take, so the test that went through it read the developer's own PATH. It asserted the `python3 -m luciazero_agentd` form only, which meant it was red for everyone who had run the documented `./install.sh` and green only where the launcher was missing -- the suite blamed the daemon for what was an untestable expectation | proven-by: `python3 -m unittest tests.test_watch.ChatTests` run twice, with the launcher on PATH and with PATH cut to python3 plus `/usr/bin:/bin`: red then green before the fix, `Ran 6 tests`, `OK` both ways after | fix: ad8d7ae | date: 2026-09-06

## the whole agentd suite broke inside a sandbox that denies /bin/ps

cause: `procinfo` shells out to `ps` for the two facts every binding rests on, and it converted only a missing `ps` and a hung one into `ProcessError`; a sandbox that finds the file and refuses to execute it raised `PermissionError`, which escaped every handler and surfaced as a raw traceback from each call site — 90 errors and 6 failures, all one denial. The near-miss trap: shadowing `/bin/ps` with a non-executable file earlier in `PATH` denies nothing, because exec search steps over a file it cannot execute and keeps looking; the deny has to cover the whole `PATH` | proven-by: `python3 -m unittest tests.test_no_process_table` in `agentd/` — red with the `procinfo.py` and `__main__.py` hunks of 718ecce reversed (`PermissionError: [Errno 13] Permission denied: 'ps'`), green at HEAD | fix: 718ecce converts the denial in `_run`, named apart from "not found" because one installs a tool and the other loosens a policy | date: 2026-09-05

## ./test.sh does not touch the real launcher, and the entry that said so was wrong

cause: recorded on 2026-09-05 as "the suite installs and uninstalls the real `~/.claude/bin/luciazero-agentd`", which made two concurrent runs look impossible and a bound session look unsafe. It does neither: `install.sh` writes to `${LUCIAZERO_BIN_DIR:-${CLAUDE_DIR}/bin}` over `CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"`, and every install and uninstall in the suite points both at a `mktemp -d`. The entry was written from reading the step's name instead of running it | proven-by: a full `./test.sh` ending `PASS  all checks green`, with the real path sampled every 0.4s for the whole run including `ok  luciazero-agentd launcher installs, runs from anywhere, and stays ownership-safe`: 422 samples, none missing, sha256 `6d93ec51...` identical before and after | fix: withdrawn; a lesson whose proven-by names a step nobody ran is a guess with a command next to it | date: 2026-09-06

## artifact_publish refuses refs that look publishable

cause: a `commit` artifact takes only a full object id the bound worktree can actually reach — the id is its own digest, so no `sha256` may be passed, and a loose blob no ref points at is not reachable; every other kind is a path relative to the bound worktree whose sha256 the daemon computes itself, and a URL is refused outright. Switching branch invalidates the binding too, so a publish after `git checkout -b` fails until the worktree is bound again | proven-by: `artifact_publish kind=commit ref=da0c4eb8d9a48d171a33574b380752e183286751` → `ConflictError: commit da0c4eb8d9a48d171a33574b380752e183286751 is not in the bound worktree /Users/athitfkm/Code/Personal/wt-docs`; `kind=report ref=https://example.com/report.md` → `UnsafeReference: artifact refs are commit ids or worktree-relative paths, never URLs`; the same publish before rebinding → `WorktreeMismatch: branch is now 'docs/lessons-wf3', recorded 'docs/three-modes'` | fix: cite a commit that exists on the bound branch or a worktree-relative path, and re-run `worktree_bind` after every branch switch | date: 2026-09-05

## skills update failed with YAML parse error

cause: `skills/done/SKILL.md` used an unquoted `: ` inside a plain YAML description, so the `skills` CLI skipped it and reported only a generic update failure | proven-by: `npx skills@1.5.23 add https://github.com/ohm41321/luciazero.git --skill done -g -y` (red); local CLI install after the fix (green) | fix: keep frontmatter descriptions free of `: ` or quote the YAML scalar; the prompt checker now rejects unquoted colon-space | date: 2026-08-21

## forged repo-local verification receipt was accepted

cause: a persistent cross-invocation signing key lets sender-controlled evidence or surviving descendants forge, merge, or replay verification state | proven-by: `./test.sh --fast` | fix: Relay never executes artifact commands or trusts receipts; the receiver reruns evidence in its own harness and explicitly passes trusted envelope fields with `consume --verified` | date: 2026-08-20

## npm staging test failed with EPERM on the default cache

cause: the test invoked npm through the machine's ambient cache, whose ownership and writability are not repository state | proven-by: `NPM_CONFIG_CACHE="$(mktemp -d)" scripts/stage-npm-package.sh "$(mktemp -d)"` | fix: give npm staging and pack checks a disposable per-test cache | date: 2026-08-20

## update helper unit checks failed after a release version bump

cause: the mocked registry `latest` version equaled the newly bumped package version, so `cliUpdateAvailable` correctly became false | proven-by: `./test.sh --full` | fix: derive a synthetic future major from `package.json` instead of hard-coding the next release | date: 2026-08-15

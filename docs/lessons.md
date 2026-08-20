# Debugging lessons

## forged repo-local verification receipt was accepted

cause: a persistent cross-invocation signing key lets sender-controlled evidence or surviving descendants forge, merge, or replay verification state | proven-by: `./test.sh --fast` | fix: Relay never executes artifact commands or trusts receipts; the receiver reruns evidence in its own harness and explicitly passes trusted envelope fields with `consume --verified` | date: 2026-08-20

## npm staging test failed with EPERM on the default cache

cause: the test invoked npm through the machine's ambient cache, whose ownership and writability are not repository state | proven-by: `NPM_CONFIG_CACHE="$(mktemp -d)" scripts/stage-npm-package.sh "$(mktemp -d)"` | fix: give npm staging and pack checks a disposable per-test cache | date: 2026-08-20

## update helper unit checks failed after a release version bump

cause: the mocked registry `latest` version equaled the newly bumped package version, so `cliUpdateAvailable` correctly became false | proven-by: `./test.sh --full` | fix: derive a synthetic future major from `package.json` instead of hard-coding the next release | date: 2026-08-15

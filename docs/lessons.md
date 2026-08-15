# Debugging lessons

## update helper unit checks failed after a release version bump

cause: the mocked registry `latest` version equaled the newly bumped package version, so `cliUpdateAvailable` correctly became false | proven-by: `./test.sh --full` | fix: derive a synthetic future major from `package.json` instead of hard-coding the next release | date: 2026-08-15

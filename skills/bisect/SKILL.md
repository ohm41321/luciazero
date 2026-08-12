---
name: bisect
description: Pinpoint the first bad commit for a reproducible regression without disturbing the caller's working tree. Use when HEAD is bad, a known revision is good, and one unattended command distinguishes them; supports flaky-endpoint detection and git-bisect skip exit 125.
---

# Bisect — isolate the first bad commit safely

## 1. Freeze the criterion

Confirm the bad endpoint fails and identify a good commit or tag. Use one unattended command whose exit `0` means good, `1–124` means bad, and `125` means the revision cannot be tested. A missing executable is an infrastructure error, not evidence that a revision is bad.

## 2. Run in a throwaway worktree

Locate this skill's installed directory, stay in the repository under investigation, and invoke the bundled script by its absolute path:

```bash
<this-skill-dir>/scripts/safe-bisect.sh --good <good-rev> --bad <bad-rev> -- <verify-command> [args...]
```

The script resolves both endpoints, repeats each endpoint twice to catch instability, creates a detached temporary worktree, cleans generated state between revisions, runs `git bisect`, resets it, and removes the worktree on every exit path. Use `--retries N` only when the reproduction needs more endpoint samples.

Do not run it for a nondeterministic symptom. Make the reproduction deterministic first through `/debug`.

## 3. Interpret narrowly

Report the result as the **first bad commit**, not automatically the root cause. Read its diff and relevant callers, then feed that evidence into `/debug` as a hypothesis. Keep the reproduction as a regression test and run the full verification tier after the fix.

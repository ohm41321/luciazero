---
name: bisect
description: Pinpoint the first bad commit for a reproducible regression in a safe temporary worktree. Use when HEAD is bad, a known revision is good, and one unattended command distinguishes them; handles flaky endpoints and git-bisect skip exit 125.
---

# Bisect

## 1. Freeze the criterion

Confirm the bad endpoint fails and name a good commit or tag. One unattended
command decides: exit `0` means good, `1–124` means bad, and `125` means
untestable. A missing executable is an infrastructure error.

## 2. Run in a throwaway worktree

```bash
<this-skill-dir>/scripts/safe-bisect.sh --good <good-rev> --bad <bad-rev> -- <verify-command> [args...]
```

The helper repeats each endpoint twice, uses a detached temporary worktree,
cleans state, resets bisect, and removes the worktree on every exit path. Use
`--retries N` only for endpoint samples. Make the reproduction deterministic
first through `/debug`.

## 3. Interpret narrowly

Report the first bad commit, not automatically the root cause. Read its diff and
relevant callers; feed `/debug`, keep the regression test, and run the full
verification tier after fixing.

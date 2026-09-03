"""Git worktree identity for the M3 isolation rules.

The daemon, not the agent, reads a worktree's identity: repository (root
commit), toplevel path, branch, HEAD, base, and dirty state. The agent only
names the path. Everything runs through the ``git`` binary with prompts and
optional locks disabled, so a probe never blocks on credentials or touches
the index.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Optional

GIT_TIMEOUT_SECONDS = 15
OID_LENGTHS = (40, 64)


class GitError(Exception):
    """git failed, is missing, or the path is not a usable worktree."""


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    return env


def git(path: str, *args: str, timeout: float = GIT_TIMEOUT_SECONDS) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", path, *args],
            capture_output=True, text=True, timeout=timeout, env=_env(), check=False, stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout:g}s") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise GitError(f"git {' '.join(args)} failed: {detail[0] if detail else f'exit {result.returncode}'}")
    return result.stdout.strip()


def is_oid(value: Any) -> bool:
    return isinstance(value, str) and len(value) in OID_LENGTHS and all(c in "0123456789abcdef" for c in value)


def inspect_worktree(path: str, base: Optional[str] = None) -> dict[str, Any]:
    """Identity of the worktree at ``path``. Raises ``GitError`` when the path
    is not a git worktree, has no commits, or is on a detached HEAD."""
    if not os.path.isdir(path):
        raise GitError(f"{path} is not a directory")
    toplevel = os.path.realpath(git(path, "rev-parse", "--show-toplevel"))
    head = git(toplevel, "rev-parse", "--verify", "HEAD^{commit}")
    try:
        branch = git(toplevel, "symbolic-ref", "--short", "-q", "HEAD")
    except GitError as exc:
        raise GitError("detached HEAD; a writing worker must be on a branch") from exc
    if not branch:
        raise GitError("detached HEAD; a writing worker must be on a branch")
    roots = sorted(git(toplevel, "rev-list", "--max-parents=0", "HEAD").split())
    if not roots:
        raise GitError("repository has no root commit")
    base_oid = head if base in (None, "", "HEAD") else git(toplevel, "rev-parse", "--verify", f"{base}^{{commit}}")
    dirty = bool(git(toplevel, "status", "--porcelain", "--untracked-files=normal"))
    # Git metadata directories: the worktree's own git dir and, for a linked
    # worktree, the shared common dir. Artifact paths may never resolve into
    # either, whatever the spelling of the path.
    git_dirs = sorted({
        os.path.realpath(os.path.join(toplevel, git(toplevel, "rev-parse", "--git-dir"))),
        os.path.realpath(os.path.join(toplevel, git(toplevel, "rev-parse", "--git-common-dir"))),
    })
    return {
        "repo_id": ",".join(roots),
        "path": toplevel,
        "branch": branch,
        "head_oid": head,
        "base_oid": base_oid,
        "dirty": dirty,
        "git_dirs": git_dirs,
    }


def commit_exists(toplevel: str, oid: str) -> bool:
    if not is_oid(oid):
        return False
    try:
        git(toplevel, "cat-file", "-e", f"{oid}^{{commit}}")
    except GitError:
        return False
    return True

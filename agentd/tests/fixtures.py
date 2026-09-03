"""Shared test fixtures: disposable git repositories for the M3 worktree
rules. Every repository lives under a temporary directory the test owns and
git runs with the fixture's own identity, never the developer's config."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

GIT_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="fixture",
    GIT_AUTHOR_EMAIL="fixture@example.invalid",
    GIT_COMMITTER_NAME="fixture",
    GIT_COMMITTER_EMAIL="fixture@example.invalid",
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_TERMINAL_PROMPT="0",
)


def git(path: str | Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=GIT_ENV)
    return result.stdout.strip()


def make_repo(path: str | Path, *, branch: str = "main") -> str:
    """Create a repository with one commit holding README.md and
    reports/x.md; returns the real toplevel path."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True, capture_output=True, env=GIT_ENV)
    # Unique content: two fixtures made in the same second with identical
    # trees, identity, and message would otherwise share commit ids.
    (path / "README.md").write_text(f"fixture {path.name} {uuid.uuid4().hex}\n", encoding="utf-8")
    (path / "reports").mkdir(exist_ok=True)
    (path / "reports" / "x.md").write_text("# report\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fixture")
    return os.path.realpath(str(path))


def commit_file(repo: str | Path, name: str, content: str) -> str:
    """Write ``name`` in ``repo``, commit it, and return the new HEAD oid."""
    target = Path(repo) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")

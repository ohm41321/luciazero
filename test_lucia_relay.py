#!/usr/bin/env python3
"""Focused regressions for cross-machine Lucia Relay trust boundaries."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
RELAY_PATH = ROOT / "skills/lucia-relay/scripts/relay.py"
SPEC = importlib.util.spec_from_file_location("relay_under_test", RELAY_PATH)
assert SPEC and SPEC.loader
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


def run(*argv: str, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def test_receiver_remote_matches_trusted_url() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        run("git", "init", "-q", cwd=root)
        trusted = "https://example.invalid/org/repo.git"
        run("git", "remote", "add", "origin", trusted, cwd=root)
        assert relay.receiver_repository_url_error(root, trusted) is None
        run("git", "config", "url.https://attacker.invalid/.insteadOf", trusted, cwd=root)
        assert relay.receiver_repository_url_error(root, trusted)
        run("git", "config", "--unset-all", "url.https://attacker.invalid/.insteadOf", cwd=root)
        run("git", "config", "--add", "remote.origin.url", trusted, cwd=root)
        assert relay.receiver_repository_url_error(root, trusted)
        run("git", "config", "--unset-all", "remote.origin.url", cwd=root)
        run("git", "config", "remote.origin.url", trusted, cwd=root)
        run("git", "config", "core.sshCommand", "/tmp/fake-ssh", cwd=root)
        assert relay.receiver_repository_url_error(root, trusted)
        run("git", "config", "--unset-all", "core.sshCommand", cwd=root)
        run("git", "config", "remote.origin.pushurl", "https://wrong.invalid/repo.git", cwd=root)
        assert relay.receiver_repository_url_error(root, trusted)
        run("git", "config", "--unset-all", "remote.origin.pushurl", cwd=root)
        run("git", "remote", "set-url", "origin", "https://wrong.invalid/repo.git", cwd=root)
        assert relay.receiver_repository_url_error(root, trusted)


def test_git_config_errors_fail_closed() -> None:
    original = relay.git
    try:
        relay.git = lambda root, *args: (124, "")
        assert relay.git_url_rewrite_error(Path("."), "https://example.invalid/repo.git")
        assert relay.git_transport_override_error(
            Path("."), "origin", "https://example.invalid/repo.git"
        )
    finally:
        relay.git = original


if __name__ == "__main__":
    test_receiver_remote_matches_trusted_url()
    test_git_config_errors_fail_closed()
    print("PASS focused lucia-relay trust regressions")

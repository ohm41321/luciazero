#!/usr/bin/env python3
"""Focused regressions for cross-machine Lucia Relay trust boundaries, and a
same-machine lifecycle run the way an installed skill runs the helper: by an
interpreter, with no shell. Windows CI runs this file natively; the Bash gate
(tests/gates/relay.sh) covers the rest on macOS and Linux."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
RELAY_PATH = ROOT / "skills/lucia-relay/scripts/relay.py"
SPEC = importlib.util.spec_from_file_location("relay_under_test", RELAY_PATH)
assert SPEC and SPEC.loader
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


def run(*argv: str, cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def relay_cli(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RELAY_PATH), *argv], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", check=False)


def committed_repo(root: Path) -> str:
    run("git", "init", "-q", cwd=root)
    run("git", "config", "user.name", "test", cwd=root)
    run("git", "config", "user.email", "test@example.invalid", cwd=root)
    (root / "work.txt").write_text("base\n", encoding="utf-8")
    run("git", "add", "work.txt", cwd=root)
    run("git", "commit", "-qm", "base", cwd=root)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_same_machine_lifecycle_through_the_interpreter() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        head = committed_repo(root)
        drafted = relay_cli("draft", "--root", ".", "--recipient", "same-machine", "--write", cwd=root)
        assert drafted.returncode == 0, drafted.stderr
        manifest = root / relay.MANIFEST
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["route"]["recipient"] == "same-machine" and data["repository"]["head"] == head, data
        data["goal"] = "Finish the parser change"
        data["state"]["next_step"] = {"kind": "command", "value": "./verify.sh"}
        data["verification"] = [{"command": "./verify.sh", "exit_code": 0, "decisive_line": "PASS",
                                 "run_at": "2026-08-12T12:00:00+00:00"}]
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        finalized = relay_cli("finalize", "--root", ".", cwd=root)
        assert finalized.returncode == 0 and finalized.stdout.startswith("WROTE "), finalized
        assert (root / relay.HUMAN).is_file()
        inspected = relay_cli("inspect", "--root", ".", "--json", cwd=root)
        report = json.loads(inspected.stdout)
        assert report["valid"] and not report["repository_drift"], report
        node = shutil.which("node")
        if node:
            wrapped = subprocess.run([node, str(ROOT / "bin" / "luciazero.js"), "relay", "validate", "--root", "."],
                                     cwd=root, capture_output=True, text=True, encoding="utf-8", check=False)
            assert wrapped.stdout.startswith("VALID luciazero-relay"), wrapped
        refused = relay_cli("consume", "--root", ".", cwd=root)
        assert refused.returncode == 2 and manifest.is_file(), refused
        consumed = relay_cli("consume", "--root", ".", "--verified", cwd=root)
        assert consumed.returncode == 0, consumed
        assert not manifest.exists() and not (root / relay.HUMAN).exists()


def test_windows_git_and_python_never_come_from_the_repository() -> None:
    """Windows looks for a bare command name in the working directory before
    PATH. A git.exe and python.exe in the relayed repository -- copies of
    node, which can do neither job -- must not be the ones that run."""
    node = shutil.which("node")
    if sys.platform != "win32" or node is None:
        return
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        head = committed_repo(root)
        for name in ("git.exe", "python.exe"):
            shutil.copyfile(node, root / name)
        drafted = relay_cli("draft", "--root", ".", "--recipient", "same-machine", cwd=root)
        assert drafted.returncode == 0, drafted.stderr
        assert json.loads(drafted.stdout)["repository"]["head"] == head, drafted.stdout
        written = relay_cli("draft", "--root", ".", "--recipient", "same-machine", "--write", cwd=root)
        assert written.returncode == 0, written.stderr
        wrapped = subprocess.run([node, str(ROOT / "bin" / "luciazero.js"), "relay", "validate", "--root", "."],
                                 cwd=root, capture_output=True, text=True, encoding="utf-8", check=False)
        # relay.py itself judged the unfinished draft, on stderr: Python ran it,
        # not node. (The node copies are untracked, so the budget error joins.)
        assert wrapped.returncode == 1 and "ERROR goal is required" in wrapped.stderr, wrapped


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
    test_same_machine_lifecycle_through_the_interpreter()
    test_windows_git_and_python_never_come_from_the_repository()
    print("PASS focused lucia-relay trust regressions and same-machine lifecycle")

#!/usr/bin/env python3
"""Offline contract tests for the Slice 3 canary reservation wrapper."""

from __future__ import annotations

import json
import hashlib
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/astra_luna_canary_budget.py"
ACK_SCRIPT = ROOT / "scripts/astra_luna_role_ack.py"
sys.path.insert(0, str(ROOT / "scripts"))


class CanaryBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "budget.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def init(self) -> None:
        result = self.run_cli("init", "--ledger", str(self.ledger))
        self.assertEqual(result.returncode, 0, result.stderr)

    def read(self) -> dict:
        return json.loads(self.ledger.read_text(encoding="utf-8"))

    def fake_codex(self, marker: Path) -> Path:
        """Create a Codex-shaped executable without starting a provider."""
        command = self.ledger.parent / "codex"
        return self.fake_provider(command, marker)

    def fake_provider(self, command: Path, marker: Path | None = None) -> Path:
        """Create a direct provider-shaped executable for offline tests."""
        marker_line = (
            f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
            if marker is not None
            else ""
        )
        command.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            + marker_line,
            encoding="utf-8",
        )
        command.chmod(0o755)
        return command

    def role_file(self, role: str, *, declared_role: str | None = None) -> Path:
        role_dir = Path(self.tmp.name) / "agents"
        role_dir.mkdir(exist_ok=True)
        path = role_dir / f"{role}.toml"
        name = declared_role if declared_role is not None else role
        path.write_text(
            f'name = "{name}"\n'
            'description = "offline role binding fixture"\n'
            'sandbox_mode = "workspace-write"\n'
            'developer_instructions = "Read this exact role profile before acting."\n',
            encoding="utf-8",
        )
        return path

    def role_arg(self, role: str) -> list[str]:
        return ["--role-file", str(self.role_file(role))]

    def fake_role_provider(
        self, command: Path, *, acknowledge: bool = True, via_shell: bool = False
    ) -> Path:
        """Create a provider that must attest to the role file it received."""
        ack = ""
        if acknowledge:
            ack_prefix = (
                "role_file = Path(os.environ['LUCIAZERO_ROLE_FILE'])\n"
                "content_sha256 = hashlib.sha256(role_file.read_bytes()).hexdigest()\n"
            )
            if via_shell:
                ack = ack_prefix + (
                    "subprocess.run(['/bin/sh', '-c', "
                    "'true; python3 \\\"$LUCIAZERO_ROLE_ACK_TOOL\\\" --ack-file "
                    "\\\"$LUCIAZERO_ROLE_ACK_FILE\\\" --content-sha256 \\\"$1\\\"', "
                    "'role-ack', content_sha256], check=True)\n"
                )
            else:
                ack = ack_prefix + (
                    "subprocess.run([sys.executable, os.environ['LUCIAZERO_ROLE_ACK_TOOL'], "
                    "'--ack-file', os.environ['LUCIAZERO_ROLE_ACK_FILE'], "
                    "'--content-sha256', content_sha256], check=True)\n"
                )
        command.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib, os, subprocess, sys\n"
            "from pathlib import Path\n"
            + ack,
            encoding="utf-8",
        )
        command.chmod(0o755)
        return command

    def test_duplicate_reservation_is_refused_and_does_not_start(self) -> None:
        self.init()
        first = self.run_cli(
            "reserve", "--ledger", str(self.ledger),
            "--cell", "C2-adapter", "--role", "lucia-explorer",
            *self.role_arg("lucia-explorer"),
        )
        second = self.run_cli(
            "reserve", "--ledger", str(self.ledger),
            "--cell", "C2-adapter", "--role", "lucia-explorer",
            *self.role_arg("lucia-explorer"),
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("duplicate", second.stderr.lower())
        state = self.read()
        self.assertEqual(len(state["reservations"]), 1)
        self.assertEqual(state["observed_usage"]["role_started"], 0)

    def test_concurrent_reservations_are_serialized(self) -> None:
        self.init()
        requests = [(cell, role) for cell, role in [
            ("C1-root", None),
            ("C1-adapter", None),
            ("C2-root", None),
            ("C2-adapter", "lucia-explorer"),
            ("C2-adapter", "lucia-worker"),
            ("C2-adapter", "lucia-tester"),
            ("C3-root", None),
            ("C3-adapter", "lucia-explorer"),
            ("C3-adapter", "lucia-worker"),
            ("C3-adapter", "lucia-tester"),
            ("C3-adapter", "lucia-reviewer"),
            ("C4-root", None),
            ("C4-adapter", "lucia-researcher"),
            ("C4-adapter", "lucia-reviewer"),
            ("C4-root", "lucia-reviewer"),  # invalid request, must not win
            ("C1-root", "lucia-worker"),   # invalid request, must not win
            ("C4-adapter", "lucia-worker"),  # outside that cell's matrix
            ("C2-adapter", "lucia-reviewer"),  # outside that cell's matrix
        ]]
        processes = []
        for cell, role in requests:
            command = [
                sys.executable, str(SCRIPT), "reserve",
                "--ledger", str(self.ledger), "--cell", cell,
            ]
            if role is not None:
                command.extend(["--role", role])
                command.extend(self.role_arg(role))
            processes.append(subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        results = [process.communicate() for process in processes]
        success_count = sum(process.returncode == 0 for process in processes)
        self.assertEqual(success_count, 14)
        state = self.read()
        self.assertEqual(len(state["reservations"]), 14)
        self.assertEqual(state["observed_usage"]["role_started"], 0)
        self.assertEqual(state["observed_usage"]["refused_invalid"], 4)
        self.assertEqual(len({(item["cell"], item.get("role")) for item in state["reservations"]}), 14)
        self.assertEqual(len(results), len(processes))

    def test_concurrent_duplicate_has_one_winner(self) -> None:
        self.init()
        command = [
            sys.executable, str(SCRIPT), "reserve",
            "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", "lucia-worker",
            *self.role_arg("lucia-worker"),
        ]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(2)
        ]
        results = [process.communicate() for process in processes]
        self.assertEqual(sum(process.returncode == 0 for process in processes), 1)
        self.assertEqual(sum(process.returncode != 0 for process in processes), 1)
        self.assertTrue(any("duplicate" in stderr.lower() for _, stderr in results))
        state = self.read()
        self.assertEqual(len(state["reservations"]), 1)
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_failed_start_consumes_slot_and_is_not_retried(self) -> None:
        self.init()
        result = self.run_cli(
            "root", "--ledger", str(self.ledger), "--cell", "C1-root",
            "--", "/definitely/missing/codex", "--disable", "multi_agent",
            "--disable", "multi_agent_v2",
        )
        self.assertEqual(result.returncode, 127)
        self.assertIn("failed_start", result.stderr.lower())
        retry = self.run_cli(
            "reserve", "--ledger", str(self.ledger), "--cell", "C1-root",
        )
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn("duplicate", retry.stderr.lower())
        state = self.read()
        self.assertEqual(state["observed_usage"]["failed_start"], 1)
        self.assertEqual(state["observed_usage"]["root_started"], 0)
        self.assertEqual(state["reservations"][0]["state"], "failed_start")

    def test_root_runs_command_only_after_reservation_and_records_usage(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "provider-ran"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "root", "--ledger", str(self.ledger), "--cell", "C1-root", "--",
            str(codex), "--disable", "multi_agent", "--disable", "multi_agent_v2",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROOT_NATIVE_MULTI_AGENT=disabled", result.stdout)
        self.assertIn("ROOT_NATIVE_MULTI_AGENT_V2=disabled", result.stdout)
        self.assertEqual(marker.read_text(encoding="utf-8"), "ran")
        state = self.read()
        self.assertEqual(state["observed_usage"]["root_started"], 1)
        self.assertEqual(state["observed_usage"]["completed"], 1)
        self.assertEqual(state["reservations"][0]["state"], "completed")

    def test_root_requires_native_multi_agent_disabled_before_popen(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "must-not-run"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "root", "--ledger", str(self.ledger), "--cell", "C1-root", "--",
            str(codex),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multi_agent", result.stderr)
        self.assertFalse(marker.exists())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["root_started"], 0)
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_root_requires_both_native_collaboration_features_disabled(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "must-not-run"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "root", "--ledger", str(self.ledger), "--cell", "C1-root", "--",
            str(codex), "--disable", "multi_agent",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multi_agent_v2", result.stderr)
        self.assertFalse(marker.exists())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_root_rejects_conflicting_native_enable_flag(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "must-not-run"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "root", "--ledger", str(self.ledger), "--cell", "C1-root", "--",
            str(codex), "--disable", "multi_agent", "--disable", "multi_agent_v2",
            "--enable", "multi_agent",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("enable", result.stderr.lower())
        self.assertFalse(marker.exists())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_unlabelled_spawn_cannot_bypass_root_policy(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "must-not-run"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C1-root", "--",
            str(codex), "--disable", "multi_agent",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("root", result.stderr.lower())
        self.assertFalse(marker.exists())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_codex_role_also_requires_native_multi_agent_disabled(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "must-not-run"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", "lucia-worker", *self.role_arg("lucia-worker"),
            "--", str(codex),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multi_agent", result.stderr)
        self.assertFalse(marker.exists())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["role_started"], 0)
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_role_reservation_requires_instruction_binding_file(self) -> None:
        self.init()
        result = self.run_cli(
            "reserve", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", "lucia-worker",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instruction", result.stderr.lower())
        state = self.read()
        self.assertEqual(state["reservations"], [])

    def test_role_start_requires_instruction_binding_file(self) -> None:
        self.init()
        provider = self.fake_provider(self.ledger.parent / "claude")
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", "lucia-worker", "--", str(provider),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instruction", result.stderr.lower())
        state = self.read()
        self.assertEqual(state["reservations"], [])

    def test_role_binding_records_hash_and_provider_attestation(self) -> None:
        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.fake_role_provider(self.ledger.parent / "claude")
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(role_path), "--", str(provider),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROLE_BINDING_VERIFIED role=lucia-worker sha256=", result.stdout)
        state = self.read()
        item = state["reservations"][0]
        expected_hash = hashlib.sha256(role_path.read_bytes()).hexdigest()
        self.assertEqual(
            item["instruction_binding"],
            {"role": role, "sha256": expected_hash, "ack": "verified"},
        )
        self.assertEqual(state["observed_usage"]["completed"], 1)

    def test_role_without_provider_attestation_is_not_completed(self) -> None:
        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.fake_role_provider(self.ledger.parent / "claude", acknowledge=False)
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(role_path), "--", str(provider),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ack", result.stderr.lower())
        state = self.read()
        item = state["reservations"][0]
        self.assertEqual(item["state"], "failed_binding")
        self.assertEqual(item["instruction_binding"]["ack"], "failed")
        self.assertEqual(state["observed_usage"]["completed"], 0)
        self.assertEqual(state["observed_usage"]["failed_binding"], 1)

    def test_role_file_name_and_declared_role_must_match(self) -> None:
        self.init()
        role = "lucia-worker"
        wrong_name = self.role_file(role, declared_role="lucia-tester")
        wrong_name.rename(wrong_name.with_name("wrong-name.toml"))
        provider = self.fake_provider(self.ledger.parent / "claude")
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(wrong_name.with_name("wrong-name.toml")),
            "--", str(provider),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("role", result.stderr.lower())
        state = self.read()
        self.assertEqual(state["reservations"], [])

    def test_role_profile_requires_nonempty_developer_instructions(self) -> None:
        self.init()
        role = "lucia-worker"
        role_path = Path(self.tmp.name) / "agents" / f"{role}.toml"
        role_path.parent.mkdir()
        role_path.write_text(
            'name = "lucia-worker"\n'
            'description = "label only"\n'
            'sandbox_mode = "workspace-write"\n',
            encoding="utf-8",
        )
        result = self.run_cli(
            "reserve", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(role_path),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("developer_instructions", result.stderr)
        self.assertEqual(self.read()["reservations"], [])

    def test_role_ack_through_a_shell_intermediary_still_binds_provider(self) -> None:
        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.fake_role_provider(
            self.ledger.parent / "claude", via_shell=True
        )
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(role_path), "--", str(provider),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROLE_BINDING_VERIFIED", result.stdout)
        self.assertEqual(self.read()["reservations"][0]["state"], "completed")
        self.assertEqual(list(Path(self.tmp.name).glob(".role-*")), [])

    def test_nonzero_exit_with_missing_ack_records_both_failures(self) -> None:
        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.ledger.parent / "claude"
        provider.write_text(
            "#!/usr/bin/env python3\nimport sys\nsys.exit(7)\n",
            encoding="utf-8",
        )
        provider.chmod(0o755)
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(role_path), "--", str(provider),
        )
        self.assertEqual(result.returncode, 7)
        state = self.read()
        self.assertEqual(state["reservations"][0]["state"], "failed_exit")
        self.assertEqual(state["observed_usage"]["failed_binding"], 1)
        self.assertEqual(state["observed_usage"]["failed_exit"], 1)

    def test_role_ack_waits_through_a_partial_provider_marker(self) -> None:
        role = "lucia-worker"
        role_path = self.role_file(role)
        ack_path = Path(self.tmp.name) / "ack.json"
        marker_path = Path(self.tmp.name) / "provider-marker.json"
        marker_path.write_text("{", encoding="utf-8")
        nonce = "marker-race-nonce"
        digest = hashlib.sha256(role_path.read_bytes()).hexdigest()
        env = os.environ.copy()
        env.update(
            {
                "LUCIAZERO_ROLE_NAME": role,
                "LUCIAZERO_ROLE_FILE": str(role_path),
                "LUCIAZERO_ROLE_SHA256": digest,
                "LUCIAZERO_ROLE_ACK_FILE": str(ack_path),
                "LUCIAZERO_ROLE_ACK_NONCE": nonce,
                "LUCIAZERO_ROLE_PROVIDER_MARKER": str(marker_path),
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(ACK_SCRIPT),
                "--ack-file",
                str(ack_path),
                "--content-sha256",
                digest,
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.05)
        marker_path.write_text(
            json.dumps({"nonce": nonce, "provider_pid": process.pid}) + "\n",
            encoding="utf-8",
        )
        stdout, stderr = process.communicate(timeout=3)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(ack_path.read_text())["provider_pid"], process.pid)

    def test_marker_allocation_failure_keeps_started_provider_lifecycle(self) -> None:
        import astra_luna_canary_budget as budget

        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.ledger.parent / "claude"
        provider.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        provider.chmod(0o755)
        real_mkstemp = tempfile.mkstemp
        marker_allocation_failed = False

        def mkstemp(*args, **kwargs):
            nonlocal marker_allocation_failed
            prefix = kwargs.get("prefix", args[0] if args else "")
            if isinstance(prefix, str) and prefix.startswith("..role-provider."):
                marker_allocation_failed = True
                raise OSError("injected marker allocation failure")
            return real_mkstemp(*args, **kwargs)

        class FakeProcess:
            pid = 4242

            def __init__(self) -> None:
                self.wait_called = False

            def wait(self) -> int:
                self.wait_called = True
                return 7

        process = FakeProcess()
        with mock.patch.object(budget.tempfile, "mkstemp", side_effect=mkstemp):
            with mock.patch.object(budget.subprocess, "Popen", return_value=process):
                result = budget.spawn_cli(
                    self.ledger,
                    "C2-adapter",
                    role,
                    [str(provider)],
                    role_file=role_path,
                )
        self.assertTrue(marker_allocation_failed)
        self.assertTrue(process.wait_called)
        self.assertEqual(result, 7)
        state = self.read()
        item = state["reservations"][0]
        self.assertEqual(item["state"], "failed_exit")
        self.assertEqual(state["observed_usage"]["role_started"], 1)
        self.assertEqual(state["observed_usage"]["failed_start"], 0)
        self.assertEqual(state["observed_usage"]["failed_binding"], 1)
        self.assertEqual(state["observed_usage"]["failed_exit"], 1)

    def test_started_state_write_failure_waits_and_cleans_provider(self) -> None:
        import astra_luna_canary_budget as budget

        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.ledger.parent / "claude"
        process = mock.Mock()
        process.pid = 4343
        process.wait.return_value = 7
        original_write_state = budget._write_state

        def write_state(path, state):
            if state["observed_usage"]["role_started"]:
                raise OSError("injected started-state write failure")
            return original_write_state(path, state)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with mock.patch.object(budget.subprocess, "Popen", return_value=process):
                with mock.patch.object(budget, "_write_state", side_effect=write_state):
                    result = budget.spawn_cli(
                        self.ledger,
                        "C2-adapter",
                        role,
                        [str(provider)],
                        role_file=role_path,
                    )
        self.assertEqual(result, 7)
        process.wait.assert_called_once_with()
        self.assertIn("ACCOUNTING_FAILED", stderr.getvalue())
        self.assertEqual(list(Path(self.tmp.name).glob(".role-*")), [])
        state = self.read()
        self.assertEqual(len(state["reservations"]), 1)
        self.assertEqual(state["reservations"][0]["state"], "reserved")
        self.assertEqual(state["observed_usage"]["role_started"], 0)

    def test_role_file_drift_after_reservation_cannot_be_attested(self) -> None:
        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.ledger.parent / "claude"
        provider.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib, os, subprocess, sys\n"
            "from pathlib import Path\n"
            "role_file = Path(os.environ['LUCIAZERO_ROLE_FILE'])\n"
            "role_file.write_text('name = \\\"lucia-worker\\\"\\ndrift = true\\n', encoding='utf-8')\n"
            "digest = hashlib.sha256(role_file.read_bytes()).hexdigest()\n"
            "subprocess.run([sys.executable, os.environ['LUCIAZERO_ROLE_ACK_TOOL'], "
            "'--ack-file', os.environ['LUCIAZERO_ROLE_ACK_FILE'], "
            "'--content-sha256', digest], check=True)\n",
            encoding="utf-8",
        )
        provider.chmod(0o755)
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(role_path), "--", str(provider),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ROLE_BINDING_FAILED", result.stderr)
        state = self.read()
        item = state["reservations"][0]
        self.assertEqual(item["instruction_binding"]["ack"], "failed")
        self.assertEqual(item["state"], "failed_exit")
        self.assertEqual(state["observed_usage"]["completed"], 0)

    def test_role_ack_must_be_bound_to_the_provider_pid(self) -> None:
        self.init()
        role = "lucia-worker"
        role_path = self.role_file(role)
        provider = self.ledger.parent / "claude"
        provider.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib, json, os\n"
            "from pathlib import Path\n"
            "role_file = Path(os.environ['LUCIAZERO_ROLE_FILE'])\n"
            "digest = hashlib.sha256(role_file.read_bytes()).hexdigest()\n"
            "Path(os.environ['LUCIAZERO_ROLE_ACK_FILE']).write_text(json.dumps({"
            "'method': 'luciazero-role-ack-v1', 'role': os.environ['LUCIAZERO_ROLE_NAME'],"
            "'sha256': digest, 'content_sha256': digest, 'nonce': os.environ['LUCIAZERO_ROLE_ACK_NONCE'],"
            "'provider_pid': 0}) + '\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        provider.chmod(0o755)
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", role, "--role-file", str(role_path), "--", str(provider),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ROLE_BINDING_FAILED", result.stderr)
        self.assertIn("provider process", result.stderr)
        state = self.read()
        self.assertEqual(state["reservations"][0]["state"], "failed_binding")
        self.assertEqual(state["observed_usage"]["completed"], 0)

    def test_codex_role_must_be_a_direct_executable(self) -> None:
        self.init()
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", "lucia-worker", *self.role_arg("lucia-worker"),
            "--", "/usr/bin/env", "codex",
            "--disable", "multi_agent", "--disable", "multi_agent_v2",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("direct", result.stderr.lower())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_shell_wrapped_codex_role_is_refused_before_popen(self) -> None:
        self.init()
        result = self.run_cli(
            "spawn", "--ledger", str(self.ledger), "--cell", "C2-adapter",
            "--role", "lucia-worker", *self.role_arg("lucia-worker"),
            "--", "/bin/sh", "-c",
            "codex --disable multi_agent --disable multi_agent_v2",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("direct", result.stderr.lower())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_root_rejects_uninspected_config_overrides(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "must-not-run"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "root", "--ledger", str(self.ledger), "--cell", "C1-root", "--",
            str(codex), "--disable", "multi_agent", "--disable", "multi_agent_v2",
            "--config", str(Path(self.tmp.name) / "enabled.toml"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("config", result.stderr.lower())
        self.assertFalse(marker.exists())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_root_rejects_compact_native_config_enable(self) -> None:
        self.init()
        marker = Path(self.tmp.name) / "must-not-run"
        codex = self.fake_codex(marker)
        result = self.run_cli(
            "root", "--ledger", str(self.ledger), "--cell", "C1-root", "--",
            str(codex), "--disable", "multi_agent", "--disable", "multi_agent_v2",
            "-cfeatures.multi_agent=true",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("enable", result.stderr.lower())
        self.assertFalse(marker.exists())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_all_canary_role_starts_are_explicit_wrapper_reservations(self) -> None:
        self.init()
        role_cells = [
            ("C2-adapter", "lucia-explorer"),
            ("C2-adapter", "lucia-worker"),
            ("C2-adapter", "lucia-tester"),
            ("C3-adapter", "lucia-reviewer"),
            ("C4-adapter", "lucia-researcher"),
        ]
        for cell, role in role_cells:
            role_path = self.role_file(role)
            provider = self.fake_role_provider(self.ledger.parent / "claude")
            result = self.run_cli(
                "spawn", "--ledger", str(self.ledger), "--cell", cell,
                "--role", role, "--role-file", str(role_path), "--", str(provider),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        state = self.read()
        self.assertEqual(state["observed_usage"]["role_started"], len(role_cells))
        self.assertEqual(state["observed_usage"]["completed"], len(role_cells))
        self.assertEqual(
            {(item["cell"], item.get("role")) for item in state["reservations"]},
            set(role_cells),
        )

    def test_full_canary_matrix_starts_all_eight_roots_and_nine_roles(self) -> None:
        self.init()
        root_cells = [
            "C1-root", "C1-adapter", "C2-root", "C3-root",
            "C4-root", "C2-adapter", "C3-adapter", "C4-adapter",
        ]
        codex = self.fake_codex(Path(self.tmp.name) / "root-ran")
        provider = self.fake_role_provider(self.ledger.parent / "claude")
        for cell in root_cells:
            result = self.run_cli(
                "root", "--ledger", str(self.ledger), "--cell", cell, "--",
                str(codex), "--disable", "multi_agent", "--disable", "multi_agent_v2",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        role_cells = [
            ("C2-adapter", "lucia-explorer"),
            ("C2-adapter", "lucia-worker"),
            ("C2-adapter", "lucia-tester"),
            ("C3-adapter", "lucia-explorer"),
            ("C3-adapter", "lucia-worker"),
            ("C3-adapter", "lucia-tester"),
            ("C3-adapter", "lucia-reviewer"),
            ("C4-adapter", "lucia-researcher"),
            ("C4-adapter", "lucia-reviewer"),
        ]
        for cell, role in role_cells:
            role_path = self.role_file(role)
            result = self.run_cli(
                "spawn", "--ledger", str(self.ledger), "--cell", cell,
                "--role", role, "--role-file", str(role_path), "--", str(provider),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        state = self.read()
        self.assertEqual(len(state["reservations"]), 17)
        self.assertEqual(state["observed_usage"]["root_started"], 8)
        self.assertEqual(state["observed_usage"]["role_started"], 9)
        self.assertEqual(state["observed_usage"]["completed"], 17)

    def test_orchestrator_skill_declares_the_same_spawn_boundary(self) -> None:
        skill = (
            ROOT
            / "adapters/astra-luna/skills/lucia-orchestrator/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("do not use provider-native subagent tools", skill)
        self.assertIn("codex --disable multi_agent --disable multi_agent_v2", skill)
        self.assertIn("spawn --role <selected-role>", skill)
        self.assertIn("role-less `spawn`", skill)

    def test_role_outside_matrix_is_refused_without_reservation(self) -> None:
        self.init()
        result = self.run_cli(
            "reserve", "--ledger", str(self.ledger), "--cell", "C1-root",
            "--role", "lucia-worker", *self.role_arg("lucia-worker"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed", result.stderr.lower())
        state = self.read()
        self.assertEqual(state["reservations"], [])
        self.assertEqual(state["observed_usage"]["refused_invalid"], 1)

    def test_global_cap_rejects_the_eighteenth_slot(self) -> None:
        from astra_luna_canary_budget import new_ledger, reserve_slot, QuotaExceeded

        # Use the same reservation seam with a deliberately wider offline plan
        # so this test exercises the aggregate cap independently of per-cell
        # duplicate and role-matrix checks.
        plan = {
            "total_starts": 17,
            "cells": {
                f"synthetic-{index}": {"root_limit": 1, "roles": []}
                for index in range(18)
            },
        }
        state = new_ledger(plan)
        for index in range(17):
            reserve_slot(state, f"synthetic-{index}", None, plan=plan)
        with self.assertRaises(QuotaExceeded):
            reserve_slot(state, "synthetic-17", None, plan=plan)
        self.assertEqual(len(state["reservations"]), 17)


if __name__ == "__main__":
    unittest.main()

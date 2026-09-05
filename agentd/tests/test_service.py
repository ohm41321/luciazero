"""The daemon as a background service (M7e).

Two things are being defended here, and neither is about convenience.

The first is that this suite never installs anything. A test that ran
`launchctl bootstrap` or `systemctl --user enable` would leave a daemon
running on whoever's machine ran it, so every service file goes under a
temporary root and every service-manager command goes to a fake runner that
only records what it was asked to do. There is a test for that too: the plan's
paths must be inside the temporary root.

The second is ownership. A service file is a standing instruction to run a
command, and replacing somebody else's is worse than replacing an ordinary
file -- so the marker check is tested from both directions, and the refusal
must leave the foreign file byte-for-byte intact.
"""
from __future__ import annotations

import io
import json
import plistlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from luciazero_agentd import service
from luciazero_agentd.__main__ import main


class FakeRunner:
    """Records the commands a real install would have run."""

    #: What a healthy `launchctl print` says. The exit code is 0 whether the
    #: job is running or merely loaded, so the state lives in stdout.
    LAUNCHD_RUNNING = "\tstate = running\n\tpid = 4242\n\truns = 1\n"

    def __init__(self, codes: Optional[dict[str, int]] = None, raises: Optional[str] = None,
                 outputs: Optional[dict[str, str]] = None) -> None:
        self.calls: list[list[str]] = []
        self.codes = codes or {}
        self.raises = raises
        self.outputs = {"launchctl print": self.LAUNCHD_RUNNING} if outputs is None else outputs

    def __call__(self, argv: list[str]) -> Any:
        self.calls.append(list(argv))
        joined = " ".join(argv)
        if self.raises is not None and self.raises in joined:
            raise OSError(2, "No such file or directory")
        code = next((c for key, c in self.codes.items() if key in joined), 0)
        out = next((text for key, text in self.outputs.items() if key in joined), "")
        return mock.Mock(returncode=code, stdout=out, stderr="boom" if code else "")

    @property
    def commands(self) -> list[str]:
        return [" ".join(call) for call in self.calls]


class ServiceCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agentd-service-")
        self.root = Path(self._tmp.name) / "home with space"
        self.state = Path(self._tmp.name) / "state"
        self.root.mkdir(parents=True)
        self.state.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def plan(self, platform: str = "darwin", **kwargs: Any) -> service.Plan:
        kwargs.setdefault("environ", {})
        kwargs.setdefault("which", lambda name: None)
        return service.plan(state_dir=str(self.state), root=self.root,
                            platform=platform, uid=501, **kwargs)


class PlanTests(ServiceCase):
    def test_windows_is_refused_by_name_not_by_a_broken_file(self) -> None:
        """ADR 0002 scopes v1 to macOS, Linux and WSL2. The identity layer
        underneath reads ttys through ps and lsof, so a Windows service file
        would install a daemon that cannot do its job."""
        for platform in ("win32", "cygwin"):
            with self.assertRaises(service.ServiceError) as caught:
                self.plan(platform=platform)
            self.assertIn("Windows", str(caught.exception))
            self.assertIn("WSL2", str(caught.exception))

    def test_every_path_stays_under_the_root_it_was_given(self) -> None:
        """The property that keeps this suite off the developer's machine."""
        for platform in ("darwin", "linux"):
            for path in self.plan(platform=platform).paths():
                self.assertTrue(str(path).startswith(str(self.root)),
                                f"{path} escaped the temporary root")

    def test_the_service_never_serves_unattributed(self) -> None:
        """A background daemon is exactly where nobody would notice sessions
        being trusted without a credential (ADR 0004)."""
        for platform in ("darwin", "linux"):
            command = self.plan(platform=platform).command
            self.assertNotIn("--allow-unattributed", command)
            self.assertIn("--approve-with", command)
            self.assertEqual("auto", command[command.index("--approve-with") + 1])

    def test_the_unattributed_guard_is_not_only_a_convention(self) -> None:
        """Defence in depth: if anything ever built the argv with that flag,
        planning must fail rather than write the file."""
        with mock.patch.object(service, "_serve_args",
                               return_value=["serve", "--allow-unattributed"]):
            with self.assertRaises(service.ServiceError) as caught:
                self.plan()
        self.assertIn("--allow-unattributed", str(caught.exception))

    def test_an_unknown_approval_channel_is_refused(self) -> None:
        with self.assertRaises(service.ServiceError):
            self.plan(approve_with="whatever")

    def test_the_interpreter_is_named_outright_even_when_the_launcher_exists(self) -> None:
        """The launcher searches PATH for a Python at 3.10+, and a service
        manager hands it its own PATH: a macOS LaunchAgent gets
        /usr/bin:/bin:/usr/sbin:/sbin, where python3 is the system 3.9. The
        launcher would exit 127 on every restart while `launchctl bootstrap`
        returned 0 and `service status` reported the service active."""
        argv, env = service.serve_command(which=lambda name: "/opt/bin/luciazero-agentd")
        self.assertNotIn("/opt/bin/luciazero-agentd", argv)
        self.assertTrue(Path(argv[0]).is_absolute())
        self.assertEqual(["-m", "luciazero_agentd"], argv[1:])
        self.assertTrue(Path(env["PYTHONPATH"], "luciazero_agentd").is_dir())

    def test_the_planned_command_never_depends_on_a_search_path(self) -> None:
        for platform in ("darwin", "linux"):
            command = self.plan(platform=platform, which=lambda name: "/opt/bin/" + name).command
            self.assertTrue(Path(command[0]).is_absolute(), command)
            self.assertNotIn("luciazero-agentd", Path(command[0]).name)

    def test_the_users_path_is_carried_in_so_providers_can_be_found(self) -> None:
        """The daemon's own interpreter is absolute, but the dispatcher starts
        providers by name and `codex` lives in the user's PATH, which a
        service manager does not hand to what it starts."""
        for platform in ("darwin", "linux"):
            plan = self.plan(platform=platform, environ={"PATH": "/opt/homebrew/bin:/usr/bin"})
            self.assertIn("/opt/homebrew/bin:/usr/bin", plan.files[0][1])

    def test_a_path_with_a_newline_is_refused_before_a_file_exists(self) -> None:
        """A newline ends a systemd directive, so the path would add a line of
        its own -- an ExecStartPre=, say -- to a unit the user believes
        describes one command."""
        bad = Path(self._tmp.name) / "state\nExecStartPre=/bin/sh -c touch\n#"
        with self.assertRaises(service.ServiceError) as caught:
            service.plan(state_dir=str(bad), root=self.root, platform="linux",
                         uid=501, environ={}, which=lambda name: None)
        self.assertIn("newline", str(caught.exception))


class LaunchdTests(ServiceCase):
    def test_the_plist_is_a_plist_and_says_who_owns_it(self) -> None:
        plan = self.plan(platform="darwin")
        (path, content), = plan.files
        self.assertEqual(self.root / "Library" / "LaunchAgents" / "com.luciazero.agentd.plist", path)
        parsed = plistlib.loads(content.encode("utf-8"))
        self.assertEqual(service.LABEL, parsed["Label"])
        self.assertEqual(service.MARKER, parsed["LuciazeroManaged"])
        self.assertTrue(parsed["RunAtLoad"])
        # Background gets the daemon jetsam priority 40 and background QoS; the
        # bus answers a person waiting at a prompt, which is what Adaptive is for.
        self.assertEqual("Adaptive", parsed["ProcessType"])
        self.assertEqual(plan.command, parsed["ProgramArguments"])
        self.assertEqual(str(self.state), parsed["EnvironmentVariables"]["LUCIAZERO_AGENT_BUS_HOME"])
        self.assertEqual(str(self.state / "daemon.log"), parsed["StandardOutPath"])

    def test_xml_metacharacters_in_a_path_do_not_break_the_file(self) -> None:
        """The state directory is a path the user chose; `&` in it must not
        end up as malformed XML that launchd refuses to load."""
        awkward = Path(self._tmp.name) / "a & b <dir>"
        awkward.mkdir()
        plan = service.plan(state_dir=str(awkward), root=self.root, platform="darwin",
                            uid=501, environ={}, which=lambda name: None)
        parsed = plistlib.loads(plan.files[0][1].encode("utf-8"))
        self.assertEqual(str(awkward), parsed["EnvironmentVariables"]["LUCIAZERO_AGENT_BUS_HOME"])

    def test_it_replaces_itself_before_loading(self) -> None:
        """bootstrap on an already-loaded label fails, so a reinstall unloads
        first -- and that unload is allowed to fail, because the usual case is
        that nothing was loaded."""
        plan = self.plan(platform="darwin")
        self.assertEqual(["launchctl", "bootout", "gui/501/com.luciazero.agentd"],
                         plan.install_steps[0].argv)
        self.assertTrue(plan.install_steps[0].optional)
        self.assertEqual("bootstrap", plan.install_steps[1].argv[1])
        self.assertFalse(plan.install_steps[1].optional)

    def test_install_starts_the_job_instead_of_trusting_bootstrap(self) -> None:
        """`launchctl bootstrap` into a GUI domain that is already up leaves
        RunAtLoad pended -- `pended nondemand spawn = speculative`, `runs = 0`
        -- so the label loads, nothing ever listens, and bootstrap still exits
        0. kickstart is what starts it, and it exits 0 on a job already
        running, so the step stays idempotent."""
        plan = self.plan(platform="darwin")
        self.assertEqual(["launchctl", "kickstart", "gui/501/com.luciazero.agentd"],
                         plan.install_steps[-1].argv)
        self.assertFalse(plan.install_steps[-1].optional)


class SystemdTests(ServiceCase):
    def test_the_unit_carries_the_marker_and_the_command(self) -> None:
        plan = self.plan(platform="linux")
        (path, content), = plan.files
        self.assertEqual(self.root / ".config" / "systemd" / "user" / "luciazero-agentd.service", path)
        self.assertIn(service.MARKER, content)
        self.assertIn("WantedBy=default.target", content)
        self.assertIn("Restart=on-failure", content)
        self.assertIn(f'Environment="LUCIAZERO_AGENT_BUS_HOME={self.state}"', content)

    def test_a_path_with_a_space_stays_one_argument(self) -> None:
        """systemd splits ExecStart on whitespace unless the argument is
        quoted its way, so an unquoted home would become two arguments and the
        service would start with the wrong state directory."""
        spaced = Path(self._tmp.name) / "state dir"
        spaced.mkdir()
        plan = service.plan(state_dir=str(spaced), root=self.root, platform="linux",
                            uid=501, environ={}, which=lambda name: "/opt/bin/luciazero-agentd")
        exec_line = next(line for line in plan.files[0][1].splitlines()
                         if line.startswith("ExecStart="))
        self.assertIn(f'"{spaced}"', exec_line)

    def test_a_quote_in_a_path_is_escaped_rather_than_closing_the_string(self) -> None:
        self.assertEqual('"say \\"hi\\""', service._systemd_quote('say "hi"'))
        self.assertEqual('"back\\\\slash"', service._systemd_quote("back\\slash"))

    def test_a_percent_in_a_path_cannot_become_a_systemd_specifier(self) -> None:
        """`/tmp/100%done` reaches systemd as the `%d` specifier, which
        silently points the daemon at a different directory."""
        spec = Path(self._tmp.name) / "100%done"
        spec.mkdir()
        plan = service.plan(state_dir=str(spec), root=self.root, platform="linux",
                            uid=501, environ={}, which=lambda name: None)
        content = plan.files[0][1]
        self.assertIn("100%%done", content)
        self.assertNotIn("100%d", content)
        for line in content.splitlines():
            if line.startswith(("StandardOutput=", "StandardError=")):
                self.assertIn("100%%done", line, line)

    def test_the_display_is_captured_so_the_dialog_still_works(self) -> None:
        plan = self.plan(platform="linux", environ={"DISPLAY": ":0", "XAUTHORITY": "/tmp/xa"})
        content = plan.files[0][1]
        self.assertIn('Environment="DISPLAY=:0"', content)
        self.assertIn('Environment="XAUTHORITY=/tmp/xa"', content)
        self.assertTrue(any("dialog" in note for note in plan.notes))

    def test_without_a_display_the_plan_says_claims_will_fail_closed(self) -> None:
        """The user must learn this at install time, not the first time a
        session asks to be an agent and is refused."""
        plan = self.plan(platform="linux", environ={})
        self.assertNotIn("DISPLAY", plan.files[0][1])
        note = " ".join(plan.notes)
        self.assertIn("fail closed", note)
        self.assertIn("run", note)


class InstallTests(ServiceCase):
    def test_it_writes_the_file_then_starts_the_service(self) -> None:
        plan = self.plan()
        runner = FakeRunner()
        result = service.install(plan, runner=runner)
        path = plan.paths()[0]
        self.assertTrue(path.is_file())
        self.assertEqual([(str(path), "created")], result["files"])
        self.assertEqual(["launchctl bootout gui/501/com.luciazero.agentd",
                          f"launchctl bootstrap gui/501 {path}",
                          "launchctl kickstart gui/501/com.luciazero.agentd"], runner.commands)

    def test_installing_twice_changes_nothing_the_second_time(self) -> None:
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        again = service.install(plan, runner=FakeRunner())
        self.assertEqual([(str(plan.paths()[0]), "unchanged")], again["files"])

    def test_an_edited_file_of_ours_is_refreshed(self) -> None:
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        path = plan.paths()[0]
        path.write_text(f"<!-- {service.MARKER} -->\nstale\n", encoding="utf-8")
        again = service.install(plan, runner=FakeRunner())
        self.assertEqual([(str(path), "updated")], again["files"])
        self.assertIn("ProgramArguments", path.read_text(encoding="utf-8"))

    def test_a_file_that_is_not_ours_is_never_replaced(self) -> None:
        """Somebody else's LaunchAgent under our label is somebody else's
        program, still being started by launchd. Refuse, do not back up."""
        plan = self.plan()
        path = plan.paths()[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<plist>not ours</plist>\n", encoding="utf-8")
        runner = FakeRunner()
        with self.assertRaises(service.ServiceError) as caught:
            service.install(plan, runner=runner)
        self.assertIn("not a Luciazero service file", str(caught.exception))
        self.assertEqual("<plist>not ours</plist>\n", path.read_text(encoding="utf-8"))
        self.assertEqual([], runner.commands, "nothing may be started after a refusal")

    def test_a_symlink_is_refused_rather_than_written_through(self) -> None:
        """Writing through a symlink writes to its target, which is a file
        this never looked at."""
        plan = self.plan()
        path = plan.paths()[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        elsewhere = self.root / "elsewhere.plist"
        elsewhere.write_text(f"<!-- {service.MARKER} -->\n", encoding="utf-8")
        path.symlink_to(elsewhere)
        with self.assertRaises(service.ServiceError):
            service.install(plan, runner=FakeRunner())
        self.assertEqual(f"<!-- {service.MARKER} -->\n", elsewhere.read_text(encoding="utf-8"))

    def test_a_dry_run_writes_nothing_and_starts_nothing(self) -> None:
        plan = self.plan()
        runner = FakeRunner()
        result = service.install(plan, runner=runner, dry_run=True)
        self.assertEqual([(str(plan.paths()[0]), "created")], result["files"])
        self.assertFalse(plan.paths()[0].exists())
        self.assertEqual([], runner.commands)

    def test_a_failing_required_step_is_an_error_not_a_success(self) -> None:
        plan = self.plan()
        with self.assertRaises(service.ServiceError) as caught:
            service.install(plan, runner=FakeRunner(codes={"bootstrap": 5}))
        self.assertIn("bootstrap", str(caught.exception))
        self.assertIn("boom", str(caught.exception))

    def test_a_missing_service_manager_says_what_to_do_instead(self) -> None:
        """systemctl is absent in plenty of containers and in WSL without
        systemd. That is a message, not a traceback."""
        plan = self.plan(platform="linux")
        with self.assertRaises(service.ServiceError) as caught:
            service.install(plan, runner=FakeRunner(raises="systemctl"))
        self.assertIn("luciazero-agentd serve", str(caught.exception))


class UninstallTests(ServiceCase):
    def test_it_stops_the_service_before_deleting_its_file(self) -> None:
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        runner = FakeRunner()
        result = service.uninstall(plan, runner=runner)
        self.assertFalse(plan.paths()[0].exists())
        self.assertEqual([(str(plan.paths()[0]), "removed")], result["files"])
        self.assertEqual(["launchctl bootout gui/501/com.luciazero.agentd"], runner.commands)

    def test_an_unload_that_fails_still_removes_the_file(self) -> None:
        """The ordinary case: the service was already stopped."""
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        result = service.uninstall(plan, runner=FakeRunner(codes={"bootout": 3}))
        self.assertEqual([(str(plan.paths()[0]), "removed")], result["files"])

    def test_it_deletes_only_what_it_wrote(self) -> None:
        plan = self.plan()
        path = plan.paths()[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("someone else's service\n", encoding="utf-8")
        result = service.uninstall(plan, runner=FakeRunner())
        self.assertTrue(path.exists())
        self.assertEqual([(str(path), "left untouched (not ours)")], result["files"])

    def test_uninstalling_what_was_never_installed_is_not_an_error(self) -> None:
        result = service.uninstall(self.plan(), runner=FakeRunner())
        self.assertEqual([(str(self.plan().paths()[0]), "absent")], result["files"])

    def test_a_dry_run_removes_nothing(self) -> None:
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        runner = FakeRunner()
        service.uninstall(plan, runner=runner, dry_run=True)
        self.assertTrue(plan.paths()[0].exists())
        self.assertEqual([], runner.commands)


class StatusTests(ServiceCase):
    def test_it_reports_installed_and_running(self) -> None:
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        report = service.status(plan, runner=FakeRunner())
        self.assertTrue(report["installed"])
        self.assertTrue(report["active"])
        self.assertEqual([(str(plan.paths()[0]), "ours")], report["files"])

    def test_a_file_that_is_not_ours_is_not_reported_as_installed(self) -> None:
        plan = self.plan()
        path = plan.paths()[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("someone else\n", encoding="utf-8")
        report = service.status(plan, runner=FakeRunner())
        self.assertFalse(report["installed"])
        self.assertEqual([(str(path), "foreign")], report["files"])

    def test_a_loaded_but_unstarted_launchd_job_is_not_running(self) -> None:
        """`launchctl print` exits 0 for a job that is loaded and has never
        run, so believing the exit code reported a dead bus as running."""
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        idle = "\tstate = not running\n\truns = 0\n\tpended nondemand spawn = speculative\n"
        report = service.status(plan, runner=FakeRunner(outputs={"print": idle}))
        self.assertTrue(report["installed"])
        self.assertFalse(report["active"])

    def test_systemd_is_answered_by_its_exit_code(self) -> None:
        """`systemctl --user is-active` does tell the truth in its exit code,
        so the launchd text check must not be applied to it."""
        plan = self.plan(platform="linux")
        service.install(plan, runner=FakeRunner())
        self.assertTrue(service.status(plan, runner=FakeRunner(outputs={}))["active"])
        self.assertFalse(service.status(plan, runner=FakeRunner(codes={"is-active": 3}))["active"])

    def test_a_manager_that_says_no_means_not_running(self) -> None:
        plan = self.plan()
        service.install(plan, runner=FakeRunner())
        report = service.status(plan, runner=FakeRunner(codes={"print": 113}))
        self.assertTrue(report["installed"])
        self.assertFalse(report["active"])


if __name__ == "__main__":
    unittest.main()


class CommandLineTests(ServiceCase):
    """`luciazero-agentd service ...`. The runner is replaced for the whole
    class: a CLI test that reached the real launchctl would install a daemon
    on whoever ran the suite."""

    def setUp(self) -> None:
        super().setUp()
        self.runner = FakeRunner()
        patch = mock.patch.object(service, "run_command", self.runner)
        patch.start()
        self.addCleanup(patch.stop)

    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = main(["service", *args, "--root", str(self.root),
                         "--state-dir", str(self.state)])
        return code, out.getvalue()

    def paths(self) -> list[Path]:
        return service.plan(state_dir=str(self.state), root=self.root,
                            environ={}, which=lambda name: None).paths()

    def test_a_dry_run_shows_every_file_and_command_and_does_none_of_it(self) -> None:
        code, out = self.run_cli("install", "--dry-run")
        self.assertEqual(0, code)
        for path in self.paths():
            self.assertIn(str(path), out)
        self.assertIn("dry run", out)
        self.assertFalse(any(path.exists() for path in self.paths()))
        self.assertEqual([], self.runner.commands)

    def test_install_then_status_then_uninstall(self) -> None:
        self.assertEqual(1, self.run_cli("status")[0], "not installed yet")
        code, out = self.run_cli("install")
        self.assertEqual(0, code, out)
        self.assertTrue(all(path.is_file() for path in self.paths()))
        self.assertNotEqual([], self.runner.commands)
        code, out = self.run_cli("status")
        self.assertEqual(0, code, out)
        self.assertIn(str(self.state), out)
        self.assertEqual(0, self.run_cli("uninstall")[0])
        self.assertFalse(any(path.exists() for path in self.paths()))

    def test_a_foreign_service_file_is_reported_not_replaced(self) -> None:
        for path in self.paths():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("someone else\n", encoding="utf-8")
        code, out = self.run_cli("install")
        self.assertEqual(2, code)
        self.assertIn("not a Luciazero service file", out)
        for path in self.paths():
            self.assertEqual("someone else\n", path.read_text(encoding="utf-8"))

    def test_status_as_json_is_machine_readable(self) -> None:
        self.run_cli("install")
        code, out = self.run_cli("status", "--json")
        self.assertEqual(0, code)
        report = json.loads(out)
        self.assertTrue(report["installed"])
        self.assertNotIn("--allow-unattributed", report["command"])

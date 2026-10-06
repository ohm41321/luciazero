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

import codecs
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Optional
from unittest import mock
from xml.etree import ElementTree

from luciazero_agentd import service
from luciazero_agentd.__main__ import main
from tests.fixtures import private_problem

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


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
        # Keys match by substring, first one wins: the absence check also
        # names Get-ScheduledTask, so it comes before the status probe.
        self.outputs = ({"launchctl print": self.LAUNCHD_RUNNING, "ObjectNotFound": "absent\n",
                         "Get-ScheduledTask": "Running\n"}
                        if outputs is None else outputs)

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
        # A task is registered for a named user; nothing else reads it.
        kwargs.setdefault("environ", {"USERNAME": "fixture"} if platform == "win32" else {})
        kwargs.setdefault("which", lambda name: None)
        return service.plan(state_dir=str(self.state), root=self.root,
                            platform=platform, uid=501, **kwargs)


class PlanTests(ServiceCase):
    def test_cygwin_is_refused_by_name_not_by_a_broken_file(self) -> None:
        """Cygwin's Python is neither the Windows one, which a task runs, nor
        WSL2's, which systemd runs; a service file for it would start
        something else."""
        with self.assertRaises(service.ServiceError) as caught:
            self.plan(platform="cygwin")
        self.assertIn("Task Scheduler", str(caught.exception))
        self.assertIn("WSL2", str(caught.exception))

    def test_every_path_stays_under_the_root_it_was_given(self) -> None:
        """The property that keeps this suite off the developer's machine."""
        for platform in ("darwin", "linux", "win32"):
            for path in self.plan(platform=platform).paths():
                self.assertTrue(str(path).startswith(str(self.root)),
                                f"{path} escaped the temporary root")

    def test_the_service_never_serves_unattributed(self) -> None:
        """A background daemon is exactly where nobody would notice sessions
        being trusted without a credential (ADR 0004)."""
        for platform in ("darwin", "linux", "win32"):
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
        for platform in ("darwin", "linux", "win32"):
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
        # Not created: planning needs no directory, and Windows refuses `<`
        # in a name.
        awkward = Path(self._tmp.name) / "a & b <dir>"
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
        # Quoted the systemd way, which doubles the backslashes of a Windows
        # temporary directory when this runs there.
        self.assertIn("Environment=" + service._systemd_quote(f"LUCIAZERO_AGENT_BUS_HOME={self.state}"), content)

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
        self.assertIn(service._systemd_quote(str(spaced)), exec_line)
        self.assertNotIn(f" {spaced} ", exec_line)

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


class WindowsTaskTests(ServiceCase):
    """A Task Scheduler task, planned on any platform; the parts only Windows
    can run are in WindowsTaskRunTests below."""

    NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

    def task(self, **kwargs: Any) -> tuple[service.Plan, Any]:
        kwargs.setdefault("environ", {"USERNAME": "ada", "USERDOMAIN": "DESK"})
        plan = self.plan(platform="win32", **kwargs)
        (path, content), = plan.files
        return plan, ElementTree.fromstring(content.split("?>", 1)[1])

    def test_it_runs_as_this_user_while_they_are_logged_on_and_says_who_owns_it(self) -> None:
        plan, task = self.task()
        self.assertEqual(self.root / "AppData" / "Local" / "Luciazero" / "agentd-task.xml", plan.paths()[0])
        self.assertEqual(("schtasks", service.TASK, "utf-16"), (plan.kind, plan.label, plan.encoding))
        self.assertEqual("DESK\\ada", task.find("t:Triggers/t:LogonTrigger/t:UserId", self.NS).text)
        principal = task.find("t:Principals/t:Principal", self.NS)
        self.assertEqual("DESK\\ada", principal.find("t:UserId", self.NS).text)
        # Not S4U or Password: only a logged-on user's own token, on their own
        # desktop, where the claim dialog can be seen.
        self.assertEqual("InteractiveToken", principal.find("t:LogonType", self.NS).text)
        self.assertEqual("LeastPrivilege", principal.find("t:RunLevel", self.NS).text)
        self.assertEqual("PT0S", task.find("t:Settings/t:ExecutionTimeLimit", self.NS).text)
        # Task Scheduler keeps the description and drops comments, so the
        # marker that survives registration is the one in the description.
        self.assertIn(service.MARKER, task.find("t:RegistrationInfo/t:Description", self.NS).text)

    def test_the_action_is_the_bootstrap_then_the_daemon_with_nothing_found_on_a_path(self) -> None:
        plan, task = self.task()
        action = task.find("t:Actions/t:Exec", self.NS)
        # pythonw.exe beside python.exe, so no console window opens at logon.
        self.assertEqual(service._windowless(plan.command[0]), action.find("t:Command", self.NS).text)
        self.assertEqual(["-m", "luciazero_agentd"], plan.command[1:3])
        expected = ["-c", service.WINDOWS_BOOT, service.serve_command()[1]["PYTHONPATH"], str(plan.log),
                    *plan.command[3:]]
        self.assertEqual(subprocess.list2cmdline(expected), action.find("t:Arguments", self.NS).text)
        self.assertNotIn("--allow-unattributed", expected)
        self.assertEqual(str(self.root), action.find("t:WorkingDirectory", self.NS).text)

    def test_the_bootstrap_sets_the_home_and_the_log_before_the_daemon_runs(self) -> None:
        """What a task cannot do for itself: set an environment, and send
        output somewhere. Run for real, on whatever runs this suite, with the
        package off the import path so the bootstrap has to put it there."""
        log = self.state / "daemon.log"
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", service.ROOT_ENV)}
        env.pop("LUCIAZERO_AGENT_BUS_HOME", None)
        done = subprocess.run([sys.executable, "-c", service.WINDOWS_BOOT, str(PACKAGE_ROOT), str(log), "next"],
                              cwd=str(self.root), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(2, done.returncode, done.stdout + done.stderr)
        self.assertEqual("", done.stdout + done.stderr, "everything goes to the log")
        self.assertIn(f"no bus database at {self.state / 'bus.sqlite3'}", log.read_text(encoding="utf-8"))

    def test_a_task_without_a_user_is_refused(self) -> None:
        with self.assertRaises(service.ServiceError) as caught:
            self.plan(platform="win32", environ={})
        self.assertIn("USERNAME", str(caught.exception))

    def test_install_registers_the_file_then_starts_the_task(self) -> None:
        plan, _ = self.task()
        runner = FakeRunner(codes={"schtasks /Query": 1})
        service.install(plan, runner=runner)
        path = plan.paths()[0]
        self.assertTrue(path.read_bytes().startswith(codecs.BOM_UTF16_LE), "Task Scheduler reads UTF-16")
        self.assertEqual([f"schtasks /Query /TN {service.TASK} /XML ONE",
                          " ".join(plan.absent.argv),
                          f"schtasks /End /TN {service.TASK}",
                          f"schtasks /Create /TN {service.TASK} /XML {path} /F",
                          f"schtasks /Run /TN {service.TASK}"], runner.commands)
        again = service.install(plan, runner=FakeRunner(codes={"schtasks /Query": 1}))
        self.assertEqual([(str(path), "unchanged")], again["files"], "the file is compared byte for byte")

    def test_a_task_of_the_same_name_that_is_not_ours_is_neither_replaced_nor_deleted(self) -> None:
        """The task's definition lives in Task Scheduler, not in the file, so
        the file being absent or ours proves nothing about the name."""
        plan, _ = self.task()
        theirs = FakeRunner(outputs={"schtasks /Query": "<Task><RegistrationInfo/></Task>"})
        with self.assertRaises(service.ServiceError) as caught:
            service.install(plan, runner=theirs)
        self.assertIn("not a Luciazero service", str(caught.exception))
        self.assertFalse(plan.paths()[0].exists())
        result = service.uninstall(plan, runner=theirs)
        self.assertEqual([], result["steps"])
        self.assertEqual(["schtasks /Query"] * 2, [" ".join(c[:2]) for c in theirs.calls])

    def test_a_name_whose_owner_cannot_be_read_is_neither_replaced_nor_deleted(self) -> None:
        """A failed query is not an absent task: schtasks fails the same way
        for a name nobody holds and for one it timed out or was refused on.
        Only a name known to be free, or known to be ours, may be ended,
        replaced or deleted."""
        plan, _ = self.task()

        class Runner(FakeRunner):
            def __init__(self, fail: str, how: object) -> None:
                super().__init__(codes={"schtasks /Query": 1})
                self.fail, self.how = fail, how

            def __call__(self, argv: list[str]) -> object:
                if self.fail in " ".join(argv):
                    self.calls.append(list(argv))
                    if isinstance(self.how, BaseException):
                        raise self.how
                    return mock.Mock(returncode=self.how[0], stdout=self.how[1], stderr="")
                return super().__call__(argv)

        cases = {
            "the definition query timed out": Runner("schtasks /Query", subprocess.TimeoutExpired("schtasks", 30)),
            "schtasks could not be started": Runner("schtasks /Query", PermissionError(13, "denied")),
            "the absence check timed out": Runner("ObjectNotFound", subprocess.TimeoutExpired("powershell", 30)),
            "the absence check failed": Runner("ObjectNotFound", (1, "Access is denied.\n")),
            "the task is there but unreadable": Runner("ObjectNotFound", (0, "present\n")),
        }
        for case, runner in cases.items():
            with self.subTest(case):
                for action in (service.install, service.uninstall):
                    with self.assertRaises(service.ServiceError) as caught:
                        action(plan, runner=runner)
                    self.assertIn("Nothing was changed", str(caught.exception))
                self.assertEqual([], [c for c in runner.commands if c.split()[:2] != ["schtasks", "/Query"]
                                      and "ObjectNotFound" not in c],
                                 "only questions were asked")
                self.assertFalse(plan.paths()[0].exists(), "no task file was written")

    def test_our_own_task_is_recognised_even_when_schtasks_answers_in_utf16(self) -> None:
        plan, _ = self.task()
        registered = f"<Task><Description>{service.MARKER}</Description></Task>"
        ours = FakeRunner(outputs={"schtasks /Query": "\x00".join(registered)})
        service.install(plan, runner=ours)
        self.assertIn(f"schtasks /Run /TN {service.TASK}", ours.commands)
        service.uninstall(plan, runner=ours)
        self.assertIn(f"schtasks /Delete /TN {service.TASK} /F", ours.commands)
        self.assertFalse(plan.paths()[0].exists())

    def test_status_is_the_state_task_scheduler_reports(self) -> None:
        plan, _ = self.task()
        service.install(plan, runner=FakeRunner(codes={"schtasks /Query": 1}))
        self.assertTrue(service.status(plan, runner=FakeRunner())["active"])
        ready = FakeRunner(outputs={"Get-ScheduledTask": "Ready\n"})
        self.assertFalse(service.status(plan, runner=ready)["active"])


@unittest.skipUnless(sys.platform == "win32", "Windows only; the windows-agentd CI job runs it")
class WindowsTaskRunTests(ServiceCase):
    """What Task Scheduler would start, started for real."""

    def test_the_tasks_command_line_starts_the_daemon_as_written(self) -> None:
        """Task Scheduler hands CreateProcess the command and the arguments
        exactly as they are in the file; so does this."""
        plan = service.plan(state_dir=str(self.state), root=self.root, port=0, environ=dict(os.environ))
        task = ElementTree.fromstring(plan.files[0][1].split("?>", 1)[1])
        action = task.find("t:Actions/t:Exec", WindowsTaskTests.NS)
        command = action.find("t:Command", WindowsTaskTests.NS).text
        self.assertTrue(command.lower().endswith("pythonw.exe"), command)
        line = subprocess.list2cmdline([command]) + " " + action.find("t:Arguments", WindowsTaskTests.NS).text
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "LUCIAZERO_AGENT_BUS_HOME")}
        daemon = subprocess.Popen(line, cwd=action.find("t:WorkingDirectory", WindowsTaskTests.NS).text, env=env)
        self.addCleanup(self.stop, daemon)
        endpoint = self.wait_for_endpoint()
        self.assertEqual(daemon.pid, endpoint["pid"])
        self.assertIn("listening on", plan.log.read_text(encoding="utf-8"))
        self.assertIsNone(private_problem(self.state / "token"))

    def wait_for_endpoint(self, seconds: float = 30.0) -> dict:
        from luciazero_agentd.statedir import read_endpoint

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            endpoint = read_endpoint(self.state)
            if endpoint:
                return endpoint
            time.sleep(0.1)
        log = plan_log.read_text(encoding="utf-8") if (plan_log := self.state / "daemon.log").exists() else ""
        self.fail(f"the daemon never wrote endpoint.json; log:\n{log}")

    @staticmethod
    def stop(process: "subprocess.Popen[bytes]") -> None:
        process.kill()
        process.wait(timeout=30)

    @unittest.skipUnless(os.environ.get("LUCIAZERO_TEST_TASK_SCHEDULER") == "1",
                         "registers a real scheduled task; set LUCIAZERO_TEST_TASK_SCHEDULER=1 (CI does)")
    def test_a_registered_task_starts_reports_and_goes_away(self) -> None:
        name = f"\\LuciazeroTest\\agentd-{uuid.uuid4().hex[:8]}"
        self.addCleanup(subprocess.run, ["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
        plan = service.plan(state_dir=str(self.state), root=self.root, port=0, environ=dict(os.environ), task=name)
        result = service.install(plan)
        self.assertEqual("created", result["files"][0][1])
        endpoint = self.wait_for_endpoint(60.0)
        self.addCleanup(self.end, endpoint["pid"])
        self.assertTrue(service.status(plan)["active"], service.status(plan)["probe"])
        service.uninstall(plan)
        self.assertTrue(self.wait_gone(endpoint["pid"]), "uninstall left the daemon running")
        self.assertNotEqual(0, subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True).returncode)
        self.assertFalse(plan.paths()[0].exists())

    @unittest.skipUnless(os.environ.get("LUCIAZERO_TEST_TASK_SCHEDULER") == "1",
                         "registers a real scheduled task; set LUCIAZERO_TEST_TASK_SCHEDULER=1 (CI does)")
    def test_a_registered_task_that_is_not_ours_survives_install_and_uninstall(self) -> None:
        name = f"\\LuciazeroTest\\foreign-{uuid.uuid4().hex[:8]}"
        made = subprocess.run(["schtasks", "/Create", "/TN", name, "/TR", "cmd /c exit 0", "/SC", "ONCE",
                               "/ST", "23:59", "/F"], capture_output=True, text=True)
        self.assertEqual(0, made.returncode, made.stdout + made.stderr)
        self.addCleanup(subprocess.run, ["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
        plan = service.plan(state_dir=str(self.state), root=self.root, port=0, environ=dict(os.environ), task=name)
        with self.assertRaises(service.ServiceError):
            service.install(plan)
        service.uninstall(plan)
        self.assertEqual(0, subprocess.run(["schtasks", "/Query", "/TN", name], capture_output=True).returncode)

    @staticmethod
    def wait_gone(pid: int) -> bool:
        from luciazero_agentd import winproc

        for _ in range(300):
            if not winproc.exists(pid):
                return True
            time.sleep(0.1)
        return False

    @classmethod
    def end(cls, pid: int) -> None:
        """However the test went, the daemon goes before its directory does."""
        from luciazero_agentd import winproc

        winproc.kill(pid)
        cls.wait_gone(pid)


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
        # On Windows the task name is asked about first; nothing is there yet.
        self.runner = FakeRunner(codes={"schtasks /Query": 1})
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
                            environ={"USERNAME": "fixture"}, which=lambda name: None).paths()

    def test_a_dry_run_shows_every_file_and_command_and_does_none_of_it(self) -> None:
        code, out = self.run_cli("install", "--dry-run")
        self.assertEqual(0, code)
        for path in self.paths():
            self.assertIn(str(path), out)
        self.assertIn("dry run", out)
        self.assertFalse(any(path.exists() for path in self.paths()))
        # Asking Task Scheduler whose the name is changes nothing.
        self.assertEqual([], [c for c in self.runner.commands if "schtasks /Query" not in c])

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

"""Native Windows: process facts, private state, process trees and the
pseudo console, against the real Win32 API.

Most of this runs only on Windows, where CI runs it (the windows-agentd job).
Two parts run everywhere: provider discovery against a mocked Windows process
table, because what decides it is plain string logic, and the daemon's port,
because no platform may let a second socket take it. When `run` on a console
takes Ctrl+Break over is checked off Windows only, with SIGUSR1 standing in.
"""
from __future__ import annotations

import ctypes
import json
import ntpath
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from luciazero_agentd import Store, approval, gitinfo, procinfo, proctree
from luciazero_agentd import store as store_module
from luciazero_agentd.server import BusServer
from luciazero_agentd.statedir import ensure_state_dir, load_or_create_token
from tests.fixtures import (ANSI, OnConsole, dacl_entries, dacl_sddl, fake_cli, make_repo, private_problem,
                            set_dacl)
from tests.test_mcp import TOKEN

WINDOWS = sys.platform == "win32"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_NPM = r"C:\Users\First Last\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\cli.js"
CODEX_NPM = r"C:\Users\u\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js"
only_windows = unittest.skipUnless(WINDOWS, "Windows only; the windows-agentd CI job runs it")
if WINDOWS:
    from luciazero_agentd import winproc


def row(pid: int, ppid: int, image: str, script: str | None = None) -> dict:
    return {"pid": pid, "ppid": ppid, "tty": None, "command": image, "script": script}


class WindowsProviderRows(unittest.TestCase):
    """What the Windows process table calls a provider. An npm-installed CLI
    is node.exe, so its script names it; no other node process is one."""

    def setUp(self) -> None:
        for name, value in (("WINDOWS", True), ("started_at", lambda pid, cache=False: f"t{pid}")):
            patcher = mock.patch.object(procinfo, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_images_and_npm_scripts_name_the_provider_and_nothing_else_does(self) -> None:
        cases = [
            ("claude.exe", None, "claude"),
            ("Claude.EXE", None, "claude"),
            ("codex.exe", None, "codex"),
            ("codex-x86_64-pc-windows-msvc.exe", None, "codex"),
            ("codex-aarch64-pc-windows-msvc.exe", None, "codex"),
            ("node.exe", CLAUDE_NPM, "claude"),
            ("node.exe", CLAUDE_NPM.replace("\\", "/"), "claude"),
            ("NODE.EXE", CLAUDE_NPM.upper(), "claude"),
            ("node.exe", CLAUDE_NPM[:-3] + ".mjs", "claude"),
            ("node.exe", CODEX_NPM, "codex"),
            ("node.exe", r"C:\work\server.js", None),
            ("node.exe", CLAUDE_NPM + ".bak", None),
            ("node.exe", CLAUDE_NPM.replace("@anthropic-ai", "anthropic-ai"), None),
            ("node.exe", CLAUDE_NPM.replace("claude-code", "claude-code-proxy"), None),
            ("node.exe", None, None),
            ("python.exe", CLAUDE_NPM, None),
            ("claudex.exe", None, None),
            ("cmd.exe", None, None),
        ]
        for image, script, expected in cases:
            with self.subTest(image=image, script=script):
                self.assertEqual(procinfo._provider_of(row(1, 0, image, script)), expected)

    def table(self, provider: tuple[str, str | None]) -> list[dict]:
        image, script = provider
        return [row(10, 1, "powershell.exe"), row(20, 10, image, script), row(30, 20, "cmd.exe"),
                row(40, 30, "python.exe")]

    def test_an_npm_hosted_claude_is_found_above_a_shell_and_as_a_session(self) -> None:
        for provider in (("claude.exe", None), ("node.exe", CLAUDE_NPM)):
            with self.subTest(provider=provider), mock.patch.object(procinfo, "_table", lambda: self.table(provider)):
                above = procinfo.provider_above(40)
                self.assertEqual((above["pid"], above["provider"]), (20, "claude"))
                self.assertEqual([s["pid"] for s in procinfo.sessions(with_cwd=False)], [20])

    def test_a_node_process_running_anything_else_is_no_session(self) -> None:
        with mock.patch.object(procinfo, "_table", lambda: self.table(("node.exe", r"C:\work\server.js"))):
            self.assertIsNone(procinfo.provider_above(40))
            self.assertEqual(procinfo.sessions(with_cwd=False), [])

    def test_the_npm_codex_launcher_is_the_session_and_its_native_binary_is_not(self) -> None:
        table = [row(10, 1, "powershell.exe"), row(20, 10, "node.exe", CODEX_NPM),
                 row(25, 20, "codex-x86_64-pc-windows-msvc.exe"), row(30, 25, "cmd.exe"), row(40, 30, "python.exe")]
        with mock.patch.object(procinfo, "_table", lambda: table):
            self.assertEqual(procinfo.provider_above(40)["pid"], 25)
            self.assertEqual([s["pid"] for s in procinfo.sessions(with_cwd=False)], [20])


class PosixProviderRows(unittest.TestCase):
    """The same question on macOS and Linux, where `comm` is the command:
    a full path on macOS, a bare name on Linux."""

    def setUp(self) -> None:
        patcher = mock.patch.object(procinfo, "WINDOWS", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_provider_installed_under_a_path_with_a_space_is_still_found(self) -> None:
        """Review finding: the command was cut at its first space, so a
        provider under `my tools/` was no provider at all, and the check that
        stops a session approving its own claim did not see it."""
        cases = [
            ("claude", "claude"),
            ("/usr/local/bin/codex", "codex"),
            ("/Users/someone/my tools/claude", "claude"),
            ("/Users/someone/my tools/claudex", None),
            ("/opt/claude tools/node", None),
            ("python3", None),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(procinfo._provider_of(row(1, 0, command)), expected)


class DaemonPort(unittest.TestCase):
    def test_a_second_socket_cannot_take_the_daemon_port_even_asking_for_reuse(self) -> None:
        """On Windows SO_REUSEADDR lets a second socket bind a port in use and
        take its connections, bearer tokens and all, unless the daemon holds
        the port exclusively."""
        tmp = tempfile.TemporaryDirectory(prefix="agentd-port-")
        self.addCleanup(tmp.cleanup)
        db = str(Path(tmp.name) / "bus.sqlite3")
        with Store.open(db) as store:
            store.migrate()
        server = BusServer(db, TOKEN, port=0).start()
        self.addCleanup(server.stop)
        host, port = server._httpd.server_address[:2]
        intruder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(intruder.close)
        intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with self.assertRaises(OSError):
            intruder.bind((host, port))


@only_windows
class NoConsoleWindows(unittest.TestCase):
    def test_git_taskkill_and_the_claim_dialog_open_no_console_window(self) -> None:
        """The service runs under pythonw.exe, which has no console, so every
        console program it starts without CREATE_NO_WINDOW opens a window of
        its own on the user's desktop."""
        seen: list[dict] = []
        real = subprocess.run

        def spy(*args: object, **kwargs: object) -> object:
            seen.append(dict(kwargs))
            return real(*args, **kwargs)

        with mock.patch.object(subprocess, "run", spy):
            gitinfo.git(str(Path(__file__).resolve().parents[2]), "rev-parse", "--git-dir")
            proctree.end_tree(2 ** 30, lambda seconds: True)
            approval._run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "exit 0"], 60)
        self.assertEqual(len(seen), 3)
        for kwargs in seen:
            self.assertTrue(int(kwargs.get("creationflags", 0)) & subprocess.CREATE_NO_WINDOW, kwargs)


@only_windows
class ProcessFacts(unittest.TestCase):
    def test_the_table_knows_this_process_and_its_parent(self) -> None:
        rows = {r["pid"]: r for r in winproc.table()}
        me = rows[os.getpid()]
        self.assertEqual(me["ppid"], os.getppid())
        self.assertEqual(me["command"].lower(), os.path.basename(sys.executable).lower())
        self.assertIsNone(me["tty"])

    def test_start_time_ownership_and_liveness_of_this_process(self) -> None:
        first = winproc.started_at(os.getpid())
        self.assertTrue(first and first.isdigit())
        self.assertEqual(winproc.started_at(os.getpid()), first)
        self.assertTrue(winproc.owned(os.getpid()))
        self.assertTrue(winproc.exists(os.getpid()))
        self.assertTrue(procinfo.alive(os.getpid(), procinfo.started_at(os.getpid())))
        self.assertFalse(procinfo.alive(os.getpid(), str(int(first) + 1)))

    def test_a_process_that_exited_is_neither_alive_nor_owned(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(winproc.exists(child.pid))
        self.assertFalse(winproc.owned(child.pid))

    def test_the_system_process_is_alive_and_not_this_user_s(self) -> None:
        self.assertTrue(winproc.exists(4))
        self.assertFalse(winproc.owned(4))
        for pid in (0, -1, 2 ** 40, "4"):
            self.assertFalse(winproc.exists(pid))
            self.assertFalse(winproc.owned(pid))

    def test_a_command_line_is_read_back_as_its_arguments(self) -> None:
        argv = ["a b", 'quote " inside', "ไทย ünï", "trailing\\"]
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *argv])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and winproc.command_line(child.pid) is None:
            time.sleep(0.05)
        self.assertEqual(winproc.command_line(child.pid)[-4:], argv)

    def test_a_table_that_cannot_be_read_is_a_process_error(self) -> None:
        # What `ps` denied by a sandbox is on POSIX (test_no_process_table):
        # the commands report a ProcessError, so nothing else may escape.
        with mock.patch.object(winproc, "table", side_effect=OSError(5, "Access is denied")):
            with self.assertRaises(procinfo.ProcessError):
                procinfo.sessions()
            with self.assertRaises(procinfo.ProcessError):
                procinfo.provider_above(os.getpid())


@only_windows
class NodeHostedProviders(unittest.TestCase):
    """A real node.exe running a provider's npm script, then cmd.exe, then
    Python asking procinfo who is above it -- beside a native claude.exe."""

    ASK = (
        "import json, os, sys\n"
        "sys.path.insert(0, os.environ['LZ_AGENTD'])\n"
        "from luciazero_agentd import procinfo\n"
        "above = procinfo.provider_above(os.getpid())\n"
        "print(json.dumps({'above': above, 'sessions': [s['pid'] for s in procinfo.sessions(with_cwd=False)]}))\n"
    )
    START = (
        "const { spawnSync } = require('child_process');\n"
        "const done = spawnSync('\"%LZ_PY%\" \"%LZ_ASK%\"', { shell: true, stdio: 'inherit' });\n"
        "process.exit(done.status === null ? 1 : done.status);\n"
    )

    def setUp(self) -> None:
        self.node = shutil.which("node")
        if self.node is None:
            self.skipTest("node is not installed here")
        tmp = tempfile.TemporaryDirectory(prefix="agentd-npm-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "npm prefix ไทย"
        self.root.mkdir()
        (self.root / "ask.py").write_text(self.ASK, encoding="utf-8")
        self.env = dict(os.environ, LZ_PY=sys.executable, LZ_ASK=str(self.root / "ask.py"), LZ_AGENTD=str(PACKAGE_ROOT))

    def script(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.START, encoding="utf-8")
        return path

    def ask(self, image: str, script: Path) -> tuple[int, dict]:
        child = subprocess.Popen([image, str(script)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8")
        out, err = child.communicate(timeout=120)
        self.assertEqual(child.returncode, 0, err)
        return child.pid, json.loads(out.strip().splitlines()[-1])

    def test_an_npm_installed_claude_is_the_provider_above_its_shell(self) -> None:
        pid, seen = self.ask(self.node, self.script("node_modules", "@anthropic-ai", "claude-code", "cli.js"))
        self.assertEqual((seen["above"]["pid"], seen["above"]["provider"]), (pid, "claude"))
        self.assertIn(pid, seen["sessions"])

    def test_an_npm_installed_codex_is_the_provider_above_its_shell(self) -> None:
        pid, seen = self.ask(self.node, self.script("node_modules", "@openai", "codex", "bin", "codex.js"))
        self.assertEqual((seen["above"]["pid"], seen["above"]["provider"]), (pid, "codex"))

    def test_a_native_claude_exe_is_the_provider_above_its_shell(self) -> None:
        native = self.root / "claude.exe"
        shutil.copyfile(self.node, native)
        pid, seen = self.ask(str(native), self.script("start.js"))
        self.assertEqual((seen["above"]["pid"], seen["above"]["provider"]), (pid, "claude"))
        self.assertIn(pid, seen["sessions"])

    def test_node_running_any_other_script_is_not_a_provider(self) -> None:
        pid, seen = self.ask(self.node, self.script("start.js"))
        self.assertTrue(seen["above"] is None or seen["above"]["pid"] != pid, seen)
        self.assertNotIn(pid, seen["sessions"])


class WindowsLookup(unittest.TestCase):
    """`proctree.find` on a mocked Windows filesystem, so the rule runs
    everywhere; Commands below runs it against the real one. CreateProcess and
    `shutil.which` both look in the working directory first, where a
    repository can hold a `claude.exe` or `node.exe` of its own."""

    FILES = {r"C:\repo\claude.EXE", r"C:\repo\node.exe", r"C:\trusted\claude.EXE", r"C:\node\node.exe",
             r"C:\repo\only.exe", r"C:\npm\claude.cmd"}
    ENV = {"Path": r'.;relative\bin;"C:\trusted";C:\node', "PATHEXT": ".COM;.EXE;.BAT;.CMD"}

    def find(self, name: str, env: dict, **options: object) -> object:
        """The lookup's answer, lower-cased: like Windows' own, this mocked
        filesystem ignores case, so `claude.EXE` and `claude.exe` are one file,
        and a relative path is relative to the working directory, C:\\repo."""
        files = {f.lower() for f in self.FILES}

        def isfile(path: str) -> bool:
            return ntpath.normpath(ntpath.join("C:\\repo", path)).lower() in files

        with mock.patch.object(proctree, "WINDOWS", True), mock.patch.object(proctree.os.path, "isfile", isfile):
            found = proctree.find(name, env, **options)
        return None if found is None else found.lower()

    def test_a_bare_name_comes_only_from_an_absolute_path_entry(self) -> None:
        self.assertEqual(self.find("claude", self.ENV), r"c:\trusted\claude.exe")
        self.assertEqual(self.find("node", self.ENV), r"c:\node\node.exe")
        self.assertIsNone(self.find("only", self.ENV))

    def test_a_caller_can_refuse_batch_files(self) -> None:
        env = {"Path": r"C:\npm;C:\trusted", "PATHEXT": ".COM;.EXE;.BAT;.CMD"}
        self.assertEqual(self.find("claude", env), r"c:\npm\claude.cmd")
        self.assertEqual(self.find("claude", env, only=proctree.PROGRAMS), r"c:\trusted\claude.exe")
        self.assertIsNone(self.find(r"C:\npm\claude.cmd", env, only=proctree.PROGRAMS))

    def test_a_path_is_the_callers_own_choice(self) -> None:
        self.assertEqual(self.find(r"C:\repo\only", self.ENV), r"c:\repo\only.exe")
        self.assertEqual(self.find(r"C:\npm\claude.cmd", self.ENV), r"c:\npm\claude.cmd")
        self.assertIsNone(self.find(r"C:\nowhere\claude", self.ENV))


class VanishedEntry(unittest.TestCase):
    """What the Windows state walk may pass over: an entry lstat cannot
    find, and nothing else. Plain os logic, so it runs everywhere."""

    def test_only_a_missing_entry_counts_as_gone(self) -> None:
        from luciazero_agentd.statedir import _vanished

        with tempfile.TemporaryDirectory(prefix="agentd-vanished-") as tmp:
            here = Path(tmp) / "token"
            here.write_bytes(b"x")
            self.assertFalse(_vanished(here))
            self.assertTrue(_vanished(Path(tmp) / "bus.sqlite3-wal"))
            denied = PermissionError(13, "Access is denied", str(here))
            with mock.patch("luciazero_agentd.statedir.os.lstat", side_effect=denied):
                with self.assertRaises(PermissionError):
                    _vanished(here)


@only_windows
class PrivateState(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="agentd-acl-")
        self.addCleanup(tmp.cleanup)
        self.parent = Path(tmp.name)
        # Everything made below this inherits read access for Everyone, so
        # what ensure_state_dir leaves is its own doing.
        self.icacls(self.parent, "/grant", "*S-1-1-0:(OI)(CI)(RX)")

    def icacls(self, path: Path, *args: str) -> list[str]:
        done = subprocess.run(["icacls", str(path), *args], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return [line.strip() for line in done.stdout.splitlines() if ":(" in line]

    def assertPrivate(self, path: Path) -> None:
        # Read as SDDL, by SID: icacls prints localized names, and its first
        # line starts with the path, which on a runner contains "Users".
        self.assertIsNone(private_problem(path))

    @staticmethod
    def everyone(path: Path, *, inherited: bool = True) -> list[str]:
        """The entries that admit Everyone (SID WD), from the SDDL."""
        return [ace for ace in re.findall(r"\(([^)]*)\)", dacl_sddl(path))
                if ace.split(";")[5] == "WD" and (inherited or "ID" not in ace.split(";")[1])]

    def test_the_check_admits_this_user_and_system_by_sid_and_no_one_else(self) -> None:
        """The check reads SIDs, not SDDL spellings: SDDL may write this user
        as LA, the machine's built-in Administrator, when that is who runs --
        and LA in a DACL is a grant to another account when it is not."""
        path = self.parent / "file"
        path.write_bytes(b"x")
        mine = str(winproc._my_sid())
        self.addCleanup(set_dacl, path, f"D:P(A;;FA;;;{mine})(A;;FA;;;SY)")  # so the directory can go
        set_dacl(path, f"D:P(A;;FA;;;{mine})(A;;FA;;;SY)")
        self.assertIsNone(private_problem(path))
        for other in ("BA", "WD", "BU"):
            set_dacl(path, f"D:P(A;;FA;;;{mine})(A;;FA;;;SY)(A;;FR;;;{other})")
            self.assertIsNotNone(private_problem(path), other)
            set_dacl(path, f"D:P(A;;FA;;;{other})(A;;FA;;;SY)")
            self.assertIsNotNone(private_problem(path), f"{other} in this user's place")
        set_dacl(path, f"D:P(A;;FA;;;{mine})")
        self.assertIsNotNone(private_problem(path), "without SYSTEM")
        set_dacl(path, f"D:P(D;;FA;;;WD)(A;;FA;;;{mine})(A;;FA;;;SY)")
        self.assertIsNotNone(private_problem(path), "a deny entry")
        set_dacl(path, "D:P(A;;FA;;;LA)(A;;FA;;;SY)")
        administrator = dacl_entries(path)[0][2]
        self.assertRegex(administrator or "", r"^S-1-5-21-.*-500$")
        if administrator == mine:
            self.assertIsNone(private_problem(path), "LA is this user here")
        else:
            self.assertIsNotNone(private_problem(path), "LA is another account here")

    def test_the_state_directory_and_token_admit_this_user_and_system_only(self) -> None:
        state = self.parent / "agent-bus"
        state.mkdir()
        self.assertTrue(self.everyone(state), "the fixture did not inherit Everyone")
        self.assertIn("WD", private_problem(state) or "", "the check must refuse the grant it exists to catch")
        ensure_state_dir(state)
        self.assertPrivate(state)
        load_or_create_token(state)
        self.assertPrivate(state / "token")
        (state / "later").write_text("x", encoding="utf-8")
        self.assertFalse(self.everyone(state / "later"))

    def test_a_token_and_database_left_with_grants_of_their_own_are_made_private(self) -> None:
        """A private directory does not protect a file on Windows: the file's
        own DACL decides. One left protected with Everyone in it, or with an
        explicit grant under an inheriting DACL, must lose it before reuse."""
        state = self.parent / "agent-bus"
        state.mkdir()
        token, db = state / "token", state / "bus.sqlite3"
        token.write_bytes(b"left-behind-token\n")
        with Store.open(str(db)) as store:
            store.migrate()
        mine = winproc._my_sid()
        self.icacls(token, "/inheritance:r", "/grant", "*S-1-1-0:(R)", "/grant", f"*{mine}:(F)")
        self.icacls(db, "/grant", "*S-1-1-0:(R)")
        for path in (token, db):
            self.assertTrue(self.everyone(path, inherited=False), path)
            self.assertIn("WD", private_problem(path) or "", path)
        ensure_state_dir(state)
        for path in (state, token, db):
            self.assertPrivate(path)
        self.assertEqual(load_or_create_token(state), "left-behind-token")
        self.assertEqual(token.read_bytes(), b"left-behind-token\n")

    def test_an_entry_that_goes_away_mid_walk_is_skipped_not_refused(self) -> None:
        """The last connection to a WAL database deletes its -wal and -shm
        when it closes, so any bus client can remove one while the state
        directory is being secured. An owner that can no longer be read must
        not pass for another account's: that refused `run` its own store, and
        the provider it had started never got its pid on the binding."""
        state = self.parent / "agent-bus"
        state.mkdir()
        token = state / "token"
        token.write_bytes(b"left-behind-token\n")
        early, late = state / "bus.sqlite3-wal", state / "bus.sqlite3-shm"
        for path in (early, late):
            path.write_bytes(b"x")
        real_owned, real_private = winproc.owned_path, winproc.make_private

        def owned_path(path: str) -> bool:
            if Path(path) == early:
                early.unlink()  # gone between the listing and the owner check
            return real_owned(path)

        def make_private(path: str, directory: bool) -> None:
            if Path(path) == late:
                late.unlink()  # gone between the owner check and its DACL
            real_private(path, directory)

        with mock.patch.object(winproc, "owned_path", owned_path), \
                mock.patch.object(winproc, "make_private", make_private):
            ensure_state_dir(state)
        self.assertFalse(early.exists() or late.exists())
        for path in (state, token):
            self.assertPrivate(path)

    def _denied_after(self, phase: str) -> None:
        """The token's owner, then the token itself, cannot be read: once
        `phase` ("owner" or "dacl") has started on it, lstat says access is
        denied. Only a missing entry may be skipped, so the walk must refuse."""
        state = self.parent / "agent-bus"
        state.mkdir()
        token = state / "token"
        token.write_bytes(b"left-behind-token\n")
        started = threading.Event()
        real_owned, real_private, real_lstat = winproc.owned_path, winproc.make_private, os.lstat

        def owned_path(path: str) -> bool:
            if Path(path) == token and phase == "owner":
                started.set()
                return False  # as when GetNamedSecurityInfoW is refused
            return real_owned(path)

        def make_private(path: str, directory: bool) -> None:
            if Path(path) == token and phase == "dacl":
                started.set()
                raise PermissionError(13, "Access is denied", path)
            real_private(path, directory)

        def lstat(path, *args, **kwargs):
            if started.is_set() and Path(path) == token:
                raise PermissionError(13, "Access is denied", str(path))
            return real_lstat(path, *args, **kwargs)

        with mock.patch.object(winproc, "owned_path", owned_path), \
                mock.patch.object(winproc, "make_private", make_private), \
                mock.patch("luciazero_agentd.statedir.os.lstat", lstat):
            with self.assertRaises(PermissionError):
                ensure_state_dir(state)
        self.assertTrue(started.is_set(), f"the {phase} phase never reached the token")
        self.assertIsNotNone(private_problem(token), "a token that could not be inspected was passed over")

    def test_an_entry_whose_owner_cannot_be_read_and_is_still_there_is_refused(self) -> None:
        self._denied_after("owner")

    def test_an_entry_whose_dacl_cannot_be_set_and_is_still_there_is_refused(self) -> None:
        self._denied_after("dacl")

    def test_a_link_or_a_file_another_account_owns_inside_is_refused(self) -> None:
        state = self.parent / "agent-bus"
        (state / "runs").mkdir(parents=True)
        outside = self.parent / "outside"
        outside.mkdir()
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(state / "runs" / "jump"), str(outside)],
                              capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        with self.assertRaisesRegex(PermissionError, "is a link"):
            ensure_state_dir(state)
        self.assertTrue(self.everyone(outside), "the link's target was changed")
        os.rmdir(state / "runs" / "jump")
        theirs = state / "token"
        theirs.write_text("x", encoding="utf-8")
        given = subprocess.run(["icacls", str(theirs), "/setowner", "*S-1-5-18"], capture_output=True, text=True)
        if given.returncode != 0:
            self.skipTest(f"this account may not give a file away: {given.stdout.strip()}")
        with self.assertRaisesRegex(PermissionError, "owned by another account"):
            ensure_state_dir(state)

    def test_a_state_directory_another_account_owns_is_refused(self) -> None:
        theirs = self.parent / "theirs"
        theirs.mkdir()
        given = subprocess.run(["icacls", str(theirs), "/setowner", "*S-1-5-18"], capture_output=True, text=True)
        if given.returncode != 0:
            self.skipTest(f"this account may not give a directory away: {given.stdout.strip()}")
        with self.assertRaises(PermissionError):
            ensure_state_dir(theirs)
        self.assertTrue(self.everyone(theirs), "a refused directory was changed")


@only_windows
class Commands(unittest.TestCase):
    SHIM = (
        "@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n\r\n"
        "IF EXIST \"%dp0%\\node.exe\" (\r\n  SET \"_prog=%dp0%\\node.exe\"\r\n) ELSE (\r\n  SET \"_prog=node\"\r\n"
        "  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\nendLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "
        "\"%_prog%\"  \"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\cli.js\" %*\r\n"
    )
    ARGS = ["plain", "two words", 'quote " inside', "amp & pipe | lt < gt >", "%PATH%", "!x!", "caret ^",
            "ไทย ünï", "trailing backslash\\", "line1\nline2", ""]

    def setUp(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not installed here")
        tmp = tempfile.TemporaryDirectory(prefix="agentd-cmd-")
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name) / "bin ไทย"
        script = self.bin / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        script.parent.mkdir(parents=True)
        script.write_text("process.stdout.write(JSON.stringify(process.argv.slice(2)));\n", encoding="utf-8")
        (self.bin / "claude.cmd").write_text(self.SHIM, encoding="utf-8", newline="")
        (self.bin / "tool.bat").write_text("@echo %*\r\n", encoding="utf-8", newline="")
        self.env = dict(os.environ)
        key = next((k for k in self.env if k.upper() == "PATH"), "PATH")
        self.env[key] = f"{self.bin};{self.env.get(key, '')}"

    def test_an_npm_shim_runs_its_script_with_every_argument_intact(self) -> None:
        argv = proctree.argv_for(["claude", *self.ARGS], self.env)
        self.assertEqual(Path(argv[1]).name, "cli.js")
        self.assertTrue(argv[0].lower().endswith("node.exe"), argv[0])
        done = subprocess.run(argv, env=self.env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), self.ARGS)

    def test_another_batch_file_is_refused_an_argument_cmd_would_act_on(self) -> None:
        for unsafe in ("a & b", "%PATH%", 'say "x"', "line1\nline2", "!x!", "^"):
            with self.subTest(arg=unsafe), self.assertRaises(proctree.CommandError):
                proctree.argv_for(["tool", unsafe], self.env)
        argv = proctree.argv_for(["tool", "plain"], self.env)
        self.assertEqual((Path(argv[0]).name.lower(), argv[1:]), ("tool.bat", ["plain"]))

    def test_an_executable_is_found_with_its_extension(self) -> None:
        argv = proctree.argv_for(["python", "-V"], dict(os.environ))
        self.assertTrue(argv[0].lower().endswith(".exe"), argv)

    def in_a_poisoned_directory(self) -> Path:
        """The working directory, as a repository a peer writes to: copies of
        node there named `lzprovider.exe`, `node.exe`, `lzonlyhere.exe`,
        `git.exe` and `powershell.exe`, none of which can do what the real
        program would. The trusted `lzprovider.exe` is a copy of node in the
        PATH directory."""
        node = shutil.which("node")
        poison = Path(tempfile.mkdtemp(prefix="agentd-poison-"))
        self.addCleanup(shutil.rmtree, poison, True)
        for name in ("lzprovider.exe", "node.exe", "lzonlyhere.exe", "git.exe", "powershell.exe"):
            shutil.copyfile(node, poison / name)
        shutil.copyfile(node, self.bin / "lzprovider.exe")
        here = os.getcwd()
        os.chdir(poison)
        self.addCleanup(os.chdir, here)
        return poison

    PRINT_SELF = ["-e", "process.stdout.write(process.execPath)"]

    def ran(self, argv: list[str]) -> str:
        """The program that ran argv, by the path it reports for itself."""
        done = subprocess.run(argv, env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_a_bare_name_is_never_taken_from_the_working_directory(self) -> None:
        poison = self.in_a_poisoned_directory()
        # The fixture bites: CreateProcess, given the bare name, runs the copy here.
        self.assertTrue(os.path.samefile(self.ran(["lzprovider", *self.PRINT_SELF]), poison / "lzprovider.exe"))
        argv = proctree.argv_for(["lzprovider", *self.PRINT_SELF], self.env)
        self.assertTrue(os.path.samefile(argv[0], self.bin / "lzprovider.exe"), argv)
        self.assertTrue(os.path.samefile(self.ran(argv), self.bin / "lzprovider.exe"))

    def test_an_npm_shim_never_takes_node_from_the_working_directory(self) -> None:
        poison = self.in_a_poisoned_directory()
        argv = proctree.argv_for(["claude", *self.ARGS], self.env)
        self.assertTrue(os.path.isabs(argv[0]), argv)
        self.assertFalse(os.path.samefile(argv[0], poison / "node.exe"), argv)
        self.assertEqual(json.loads(self.ran(argv)), self.ARGS)
        # Without node on PATH the shim is refused, not handed to cmd.exe, which
        # would look for node in the working directory.
        system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        bare = {**self.env, next(k for k in self.env if k.upper() == "PATH"): f"{self.bin};{system}"}
        with self.assertRaises(proctree.CommandError):
            proctree.argv_for(["claude", "x"], bare)

    def test_a_name_only_the_working_directory_has_is_refused_but_a_path_to_it_is_honoured(self) -> None:
        poison = self.in_a_poisoned_directory()
        with self.assertRaises(proctree.CommandError):
            proctree.argv_for(["lzonlyhere", *self.PRINT_SELF], self.env)
        for named in (".\\lzonlyhere", ".\\lzonlyhere.exe", str(poison / "lzonlyhere")):
            with self.subTest(named=named):
                argv = proctree.argv_for([named, *self.PRINT_SELF], self.env)
                self.assertTrue(os.path.samefile(self.ran(argv), poison / "lzonlyhere.exe"))

    def test_git_powershell_and_schtasks_come_from_path_too(self) -> None:
        from luciazero_agentd import approval, service
        repo = make_repo(Path(tempfile.mkdtemp(prefix="agentd-git-")))
        self.addCleanup(shutil.rmtree, repo, True)
        self.in_a_poisoned_directory()
        self.assertRegex(gitinfo.git(str(repo), "rev-parse", "HEAD"), r"^[0-9a-f]{40}$")
        said = ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Write-Output real"]
        self.assertEqual(approval._run(said, 60).stdout.strip(), "real")
        self.assertEqual(service.run_command(said).stdout.strip(), "real")

    def test_git_powershell_and_schtasks_are_never_a_batch_file(self) -> None:
        """cmd.exe reads a batch file's arguments a second time, and git is
        given a worktree path and a ref an agent named: a git.bat, a
        powershell.bat or a schtasks.cmd earlier on PATH must not run."""
        from luciazero_agentd import approval, service
        repo = make_repo(Path(tempfile.mkdtemp(prefix="agentd-git-")))
        self.addCleanup(shutil.rmtree, repo, True)
        early = Path(tempfile.mkdtemp(prefix="agentd-early-"))
        self.addCleanup(shutil.rmtree, early, True)
        marker = early / "ran.txt"
        for name in ("git.bat", "powershell.bat", "schtasks.cmd"):
            (early / name).write_text(f'@echo %~nx0>>"{marker}"\r\n@exit /b 0\r\n', encoding="utf-8", newline="")
        key = next((k for k in os.environ if k.upper() == "PATH"), "PATH")
        with mock.patch.dict(os.environ, {key: f"{early};{os.environ.get(key, '')}"}):
            # The fixture bites: a lookup that takes batch files finds these.
            self.assertEqual(Path(proctree.find("git") or "").parent, early)
            self.assertRegex(gitinfo.git(str(repo), "rev-parse", "HEAD"), r"^[0-9a-f]{40}$")
            said = ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Write-Output real"]
            self.assertEqual(approval._run(said, 60).stdout.strip(), "real")
            self.assertEqual(service.run_command(said).stdout.strip(), "real")
            service.run_command(["schtasks", "/?"])
        self.assertFalse(marker.exists(), marker.read_text() if marker.exists() else "")

    def test_a_plain_batch_file_starts_directly_and_on_a_pseudo_console(self) -> None:
        (self.bin / "lzplain.bat").write_text("@echo got %1\r\n@exit /b 7\r\n", encoding="utf-8", newline="")
        argv = proctree.argv_for(["lzplain", "word"], self.env)
        self.assertEqual(Path(argv[0]).name.lower(), "lzplain.bat")
        child = proctree.start(argv, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace")
        out, _ = child.communicate(timeout=60)
        proctree.release(child.pid)
        self.assertEqual((child.returncode, out.strip()), (7, "got word"))

        from luciazero_agentd import conpty
        if not conpty.HAVE_CONPTY:
            self.skipTest("this Windows has no pseudo console")
        session = conpty.Session(argv, self.env)
        chunks: list[bytes] = []
        reader = threading.Thread(target=lambda: chunks.extend(iter(session.read, b"")), daemon=True)
        reader.start()
        code = session.wait(60)
        session.close_console()
        reader.join(timeout=10)
        session.close()
        self.assertEqual(code, 7)
        self.assertIn("got word", ANSI.sub("", b"".join(chunks).decode("utf-8", "replace")))


@only_windows
class Trees(unittest.TestCase):
    """A provider is in a Job Object from its first instruction, so its whole
    tree ends with it -- including a grandchild whose parent already left."""

    ORPHAN = ("import subprocess, sys\n"
              "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
              "print(kid.pid, flush=True)\n")

    def start_orphaning(self) -> tuple[subprocess.Popen, int, str]:
        child = proctree.start([sys.executable, "-c", self.ORPHAN], stdout=subprocess.PIPE, text=True)
        grandchild = int(child.stdout.readline())
        child.stdout.close()
        child.wait(timeout=30)
        started = winproc.started_at(grandchild)
        self.assertTrue(procinfo.alive(grandchild, started), "the grandchild should outlive its parent")
        self.addCleanup(lambda: winproc.kill(grandchild) if procinfo.alive(grandchild, started) else None)
        return child, grandchild, started

    def gone(self, pid: int, started: str) -> bool:
        return proctree.wait_gone(lambda: procinfo.alive(pid, started))(10.0)

    def test_ending_the_tree_reaches_an_orphaned_grandchild(self) -> None:
        child, grandchild, started = self.start_orphaning()
        proctree.end_tree(child.pid, lambda _: True)
        self.assertTrue(self.gone(grandchild, started))

    def test_releasing_an_exited_provider_ends_what_it_left_running(self) -> None:
        child, grandchild, started = self.start_orphaning()
        proctree.release(child.pid)
        self.assertTrue(self.gone(grandchild, started))

    def test_a_daemon_that_dies_takes_its_providers_with_it(self) -> None:
        daemon = subprocess.Popen(
            [sys.executable, "-c",
             "import subprocess, sys, time\n"
             "from luciazero_agentd import proctree\n"
             "child = proctree.start([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
             "print(child.pid, flush=True)\n"
             "time.sleep(120)\n"],
            cwd=PACKAGE_ROOT, stdout=subprocess.PIPE, text=True)
        provider = int(daemon.stdout.readline())
        daemon.stdout.close()
        started = winproc.started_at(provider)
        self.addCleanup(lambda: winproc.kill(provider) if procinfo.alive(provider, started) else None)
        daemon.kill()
        daemon.wait(timeout=30)
        self.assertTrue(self.gone(provider, started))


@only_windows
class PseudoConsole(unittest.TestCase):
    def setUp(self) -> None:
        from luciazero_agentd import conpty
        if not conpty.HAVE_CONPTY:
            self.skipTest("this Windows has no pseudo console")
        self.conpty = conpty

    def drive(self, code: str, *, keys: bytes = b"", watcher: object = None) -> tuple[int, str]:
        import msvcrt
        session = self.conpty.Session([sys.executable, "-c", code], dict(os.environ))
        in_read, in_write = os.pipe()
        out_read, out_write = os.pipe()
        result: dict = {}
        chunks: list[bytes] = []

        def run() -> None:
            result["code"] = self.conpty.proxy(session, watcher=watcher, stdin=msvcrt.get_osfhandle(in_read),
                                               stdout=msvcrt.get_osfhandle(out_write), poll=0.05)
            os.close(out_write)

        def collect() -> None:
            while True:
                data = os.read(out_read, 65536)
                if not data:
                    return
                chunks.append(data)

        proxy = threading.Thread(target=run, daemon=True)
        reader = threading.Thread(target=collect, daemon=True)
        proxy.start()
        reader.start()
        if keys:
            os.write(in_write, keys)
        proxy.join(timeout=60)
        os.close(in_write)
        reader.join(timeout=10)
        self.assertFalse(proxy.is_alive(), "the proxy did not return")
        return result["code"], ANSI.sub("", b"".join(chunks).decode("utf-8", "replace"))

    def test_keystrokes_go_in_and_the_screen_comes_out(self) -> None:
        code, screen = self.drive("import sys; line = input(); print('got:' + line.upper()); sys.exit(3)",
                                  keys="hello ünï ไทย\r".encode("utf-8"))
        self.assertEqual(code, 3)
        self.assertIn("got:HELLO ÜNÏ ไทย", screen)

    def test_a_knock_is_typed_at_the_prompt(self) -> None:
        class Once:
            def __init__(self) -> None:
                self.sent = False

            def due(self) -> bool:
                sent, self.sent = self.sent, True
                return not sent

            def saw_output(self) -> None:
                pass

            def human_typed(self) -> None:
                pass

        code, screen = self.drive("line = input(); print('got:' + line)", watcher=Once())
        self.assertEqual(code, 0)
        self.assertIn("got:check your bus inbox", screen)

    def test_its_own_console_takes_split_utf8_and_characters_outside_the_bmp(self) -> None:
        # The child writes through _Console on the pseudo console's own screen
        # buffer, so this is WriteConsoleW on a real console, not a pipe.
        code, screen = self.drive(
            "import ctypes, sys\n"
            "from ctypes import wintypes\n"
            f"sys.path.insert(0, {str(PACKAGE_ROOT)!r})\n"
            "from luciazero_agentd import conpty\n"
            "k = ctypes.WinDLL('kernel32', use_last_error=True)\n"
            "k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,\n"
            "                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]\n"
            "k.CreateFileW.restype = wintypes.HANDLE\n"
            "def console(name):\n"
            "    handle = k.CreateFileW(name, 0xC0000000, 3, None, 3, 0, None)\n"
            "    if handle in (None, wintypes.HANDLE(-1).value):\n"
            "        raise ctypes.WinError(ctypes.get_last_error())\n"
            "    return handle\n"
            "with conpty._Console(console('CONIN$'), console('CONOUT$')) as screen:\n"
            "    assert screen.out_mode is not None, 'CONOUT$ is not a console'\n"
            "    for chunk in (b'start\\xf0\\x9f', b'\\x98\\x80zebra|', '\u0e44\u0e17\u0e22\U0001f600'.encode(),\n"
            "                  '\U0001f600'.encode()[:1], '\U0001f600'.encode()[1:], b'end|'):\n"
            "        screen.write(chunk)\n")
        self.assertEqual(code, 0, screen)
        self.assertIn("start\U0001f600zebra|\u0e44\u0e17\u0e22\U0001f600\U0001f600end|", screen)

    def test_ending_the_session_ends_the_provider_tree(self) -> None:
        session = self.conpty.Session(
            [sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', "
                                   "'import time; time.sleep(120)']); time.sleep(120)"], dict(os.environ))
        drained = threading.Thread(target=lambda: [None for _ in iter(session.read, b"")], daemon=True)
        drained.start()
        deadline = time.monotonic() + 30
        kids: list[int] = []
        while time.monotonic() < deadline and not kids:
            kids = [r["pid"] for r in winproc.table() if r["ppid"] == session.pid and r["command"].lower() == "python.exe"]
            time.sleep(0.1)
        self.assertTrue(kids, "the provider never started its child")
        started = winproc.started_at(kids[0])
        session.end()
        self.assertIsNotNone(session.wait(10.0))
        session.close_console()
        drained.join(timeout=5)
        session.close()
        self.assertTrue(proctree.wait_gone(lambda: procinfo.alive(kids[0], started))(10.0))


@only_windows
class RunOnAConsole(unittest.TestCase):
    """`run` end to end on a console, as test_nudge.RunTests does on a pty.

    Three consoles deep: this test's pseudo console stands for the user's
    terminal, `run` holds a second one for the provider, and the delivery
    must cross both as keystrokes. The stand-in prints what it reads, so the
    knock is proved to have arrived as input rather than merely painted.
    """

    def setUp(self) -> None:
        from luciazero_agentd import conpty
        from luciazero_agentd.statedir import write_endpoint
        if not conpty.HAVE_CONPTY:
            self.skipTest("this Windows has no pseudo console")
        tmp = tempfile.TemporaryDirectory(prefix="agentd-run-")
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"
        self.state.mkdir()
        self.db = self.state / "bus.sqlite3"
        with Store.open(str(self.db)) as store:
            store.migrate()
            store.register_agent("codex-architect", provider="codex", role="architect")
            store.register_agent("claude-implementer", provider="claude", role="implementer")
        write_endpoint(self.state, "http://127.0.0.1:1/mcp", os.getpid(), "now")
        self.provider = fake_cli(Path(tmp.name) / "provider",
                                 "import sys\nprint('provider-ready', flush=True)\n"
                                 "for line in sys.stdin:\n    print('typed:' + line.strip(), flush=True)\n")

    def start(self) -> OnConsole:
        console = OnConsole([sys.executable, "-m", "luciazero_agentd", "run", "--agent", "codex-architect",
                             "--provider", "claude", "--state-dir", str(self.state), "--", self.provider],
                            {**os.environ, "PYTHONPATH": str(PACKAGE_ROOT), "PYTHONDONTWRITEBYTECODE": "1"})
        self.addCleanup(console.finish, 0)
        # Waited for on the provider's own output, not on `run`'s "bound as":
        # a pseudo console paints the screen, not the stream, so a line the
        # provider's console clears in the same frame is never painted at all.
        self.assertTrue(console.wait_for("provider-ready"), console.screen())
        return console

    def test_keys_typed_at_the_console_reach_the_provider_as_typed(self) -> None:
        # In through ReadConsoleW on `run`'s own console and out through its
        # WriteConsoleW, with characters outside the BMP both ways.
        console = self.start()
        console.type("\u0e44\u0e17\u0e22 \U0001f600 \u00fc\U0001f680\r")
        self.assertTrue(console.wait_for("typed:\u0e44\u0e17\u0e22 \U0001f600 \u00fc\U0001f680"), console.screen())

    def test_a_delivery_knocks_on_a_session_that_is_doing_nothing(self) -> None:
        from luciazero_agentd import nudge
        console = self.start()
        with Store.open(str(self.db)) as store:
            store.heartbeat("codex-architect")
            store.send_message(sender="claude-implementer", recipient="codex-architect",
                               kind="finding", payload={"message": "while you were idle"})
        self.assertTrue(console.wait_for("typed:" + nudge.TEXT), console.screen())
        self.assertNotIn("while you were idle", console.screen())
        log = self.state / nudge.LOG_NAME
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not log.exists():
            time.sleep(0.05)
        written = log.read_text(encoding="utf-8")
        self.assertIn("claude-implementer [finding]:", written)
        self.assertIn("while you were idle", written)


@unittest.skipIf(WINDOWS, "simulated with SIGUSR1 for SIGBREAK, which Windows does not have")
class ConsoleRunSetup(unittest.TestCase):
    """Review finding: `run` on a console took Ctrl+Break over only after the
    bind and the delivery watcher were set up, so a Ctrl+Break in that moment
    met the default handler, which ends the process without its cleanup and
    leaves the binding live. Here the default is a handler that raises, so
    an escape is seen rather than fatal."""

    def test_a_ctrl_break_during_setup_ends_the_session_and_the_binding(self) -> None:
        import signal
        import types

        import luciazero_agentd
        from luciazero_agentd import __main__ as cli

        class Escaped(Exception):
            pass

        def default(*_: object) -> None:
            raise Escaped

        conpty = types.SimpleNamespace(spawn=lambda argv, env: types.SimpleNamespace(pid=os.getpid()),
                                       proxy=lambda *a, **kw: self.fail("the proxy started"))

        def open_store(*_: object) -> None:
            signal.raise_signal(signal.SIGUSR1)
            return None

        previous = signal.signal(signal.SIGUSR1, default)
        self.addCleanup(signal.signal, signal.SIGUSR1, previous)
        ended: list[str] = []
        with mock.patch.dict(sys.modules, {"luciazero_agentd.conpty": conpty}), \
                mock.patch.object(luciazero_agentd, "conpty", conpty, create=True), \
                mock.patch.object(signal, "SIGBREAK", signal.SIGUSR1, create=True), \
                mock.patch.object(cli, "_open_store", open_store):
            code = cli._run_on_a_console(types.SimpleNamespace(max_nudges=1), ["provider"], {},
                                         {"id": "bind_x", "agent_id": "codex-architect"},
                                         Path(tempfile.gettempdir()), ended.append)
        self.assertEqual(130, code)
        self.assertEqual(["run exited"], ended)
        self.assertIs(default, signal.getsignal(signal.SIGUSR1))


class GitOutput(unittest.TestCase):
    """git prints UTF-8 whatever the console's code page. Read in the
    locale's encoding -- cp1252 on a Windows runner -- a Thai path comes back
    as mojibake or not at all. Runs everywhere; it was wrong only on Windows."""

    def test_a_worktree_and_branch_outside_ascii_are_read_back_exactly(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="agentd-git-")
        self.addCleanup(tmp.cleanup)
        branch = "\u0e07\u0e32\u0e19-\u00fc"
        top = make_repo(Path(tmp.name) / "\u0e07\u0e32\u0e19 \u00fc", branch=branch)
        found = gitinfo.inspect_worktree(top)
        self.assertEqual(found["path"], top)
        self.assertEqual(found["branch"], branch)

@only_windows
class WindowsPaths(unittest.TestCase):
    """What a path means on Windows that it does not mean elsewhere: a
    drive-relative path, an alternate data stream, a second drive."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="agentd-paths-")
        self.addCleanup(tmp.cleanup)
        self.top = make_repo(Path(tmp.name) / "repo")
        self.git_dirs = gitinfo.inspect_worktree(self.top)["git_dirs"]

    def contained(self, ref: str) -> object:
        return store_module._contained_file(self.top, ref, None, git_dirs=self.git_dirs,
                                            redactor=store_module.DEFAULT_REDACTOR)

    def test_a_path_without_a_drive_is_not_absolute_on_any_python(self) -> None:
        with self.assertRaises(store_module.ValidationError):
            store_module._check_path_arg("\\tmp")
        self.assertEqual(store_module._check_path_arg(self.top), self.top)

    def test_a_drive_or_a_stream_is_not_a_file_in_the_worktree(self) -> None:
        self.assertEqual(self.contained("reports/x.md")[0], len("# report\n".encode()))
        drive = os.path.splitdrive(self.top)[0]
        for ref in (f"{drive}reports/x.md", "reports/x.md:hidden", "reports/x.md::$DATA"):
            with self.subTest(ref=ref), self.assertRaises(store_module.UnsafeReference):
                self.contained(ref)

    def test_a_junction_to_somewhere_else_is_refused_not_an_error(self) -> None:
        # The checkout is on another drive from %TEMP% on a hosted runner, so
        # this also proves two drives are an answer, not a ValueError.
        made = subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(self.top, "jump"), str(PACKAGE_ROOT)],
                              capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        self.addCleanup(os.rmdir, os.path.join(self.top, "jump"))
        with self.assertRaises(store_module.UnsafeReference):
            self.contained("jump/README.md")

@only_windows
class ConsoleOutput(unittest.TestCase):
    """WriteConsoleW counts UTF-16 units, and may take fewer than it was
    given. A character outside the BMP is two units, and a partial write can
    stop between them."""

    def setUp(self) -> None:
        from luciazero_agentd import conpty
        self.conpty = conpty

    def console(self, step: int, out: bytearray) -> object:
        class Kernel32:
            def GetConsoleMode(self, handle: int, mode: object) -> int:
                mode._obj.value = 7
                return 1

            def WriteConsoleW(self, handle: int, buffer: object, count: int, written: object, _: object) -> int:
                taken = min(count, step)
                out.extend(buffer.raw[:2 * taken])
                written._obj.value = taken
                return 1

        patcher = mock.patch.object(self.conpty, "_kernel32", Kernel32())
        patcher.start()
        self.addCleanup(patcher.stop)
        return self.conpty._Console(1, 2)

    def test_partial_writes_lose_nothing_before_or_after_an_emoji(self) -> None:
        emoji = "\U0001f600".encode()
        chunks = [b"start\xf0\x9f", b"\x98\x80Z", "\u0e44\u0e17\u0e22".encode() + emoji, emoji[:1], emoji[1:], b"end"]
        for step in (1, 2, 3, 1000):
            with self.subTest(units_per_write=step):
                out = bytearray()
                console = self.console(step, out)
                for chunk in chunks:
                    console.write(chunk)
                self.assertEqual(bytes(out).decode("utf-16-le"),
                                 "start\U0001f600Z\u0e44\u0e17\u0e22\U0001f600\U0001f600end")

    def test_a_console_that_takes_nothing_is_not_retried_forever(self) -> None:
        out = bytearray()
        self.console(0, out).write(b"stuck")
        self.assertEqual(out, b"")


@only_windows
class ConsoleInput(unittest.TestCase):
    """ReadConsoleW counts UTF-16 units as well, so one key outside the BMP
    can arrive as its two halves in two reads -- alone, or after other keys.
    Whatever is typed must reach the provider as valid UTF-8."""

    def keys(self, reads: list[str]) -> bytes:
        from luciazero_agentd import conpty
        pending = [r.encode("utf-16-le", "surrogatepass") for r in reads]

        class Kernel32:
            def GetConsoleMode(self, handle: int, mode: object) -> int:
                mode._obj.value = 7
                return 1

            def WaitForSingleObject(self, handle: int, milliseconds: int) -> int:
                return conpty.WAIT_OBJECT_0

            def ReadConsoleW(self, handle: int, buffer: object, count: int, got: object, _: object) -> int:
                units = pending.pop(0)
                self.asked = count
                ctypes.memmove(buffer, units, len(units))
                got._obj.value = len(units) // 2
                return 1

        with mock.patch.object(conpty, "_kernel32", Kernel32()):
            console = conpty._Console(1, 2)
            console._key_waiting = lambda: True
            out = b""
            while pending:
                out += console.read(threading.Event())
        return out

    def test_a_surrogate_pair_split_across_reads_is_one_character(self) -> None:
        emoji = "\U0001f600"
        for reads in (["A\ud83d", "\ude00"], ["\ud83d", "\ude00Z"], ["A\ud83d", "\ude00\ud83d", "\ude00"]):
            with self.subTest(reads=reads):
                want = "".join(reads).encode("utf-16-le", "surrogatepass").decode("utf-16-le")
                self.assertIn(emoji, want)
                self.assertEqual(self.keys(reads), want.encode("utf-8"))

    def test_a_key_inside_the_bmp_comes_through_as_typed(self) -> None:
        self.assertEqual(self.keys(["\u0e44\u0e17\u0e22 \u00fc", "\r"]), "\u0e44\u0e17\u0e22 \u00fc\r".encode())

    def test_a_half_with_no_other_half_is_never_invalid_utf8(self) -> None:
        for reads in (["\ude00B"], ["\ud83dB"], ["A\ud83d", "B"]):
            with self.subTest(reads=reads):
                self.assertIn("\ufffd", self.keys(reads).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

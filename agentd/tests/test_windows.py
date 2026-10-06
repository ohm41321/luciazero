"""Native Windows: process facts, private state, process trees and the
pseudo console, against the real Win32 API.

Most of this runs only on Windows, where CI runs it (the windows-agentd job).
Two parts run everywhere: provider discovery against a mocked Windows process
table, because what decides it is plain string logic, and the daemon's port,
because no platform may let a second socket take it.
"""
from __future__ import annotations

import json
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

from luciazero_agentd import Store, procinfo, proctree
from luciazero_agentd.server import BusServer
from luciazero_agentd.statedir import ensure_state_dir, load_or_create_token
from tests.test_mcp import TOKEN

WINDOWS = sys.platform == "win32"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_NPM = r"C:\Users\First Last\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\cli.js"
CODEX_NPM = r"C:\Users\u\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[=>()][0-9A-Za-z]?")
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
        entries = self.icacls(path)
        self.assertEqual(len(entries), 2, entries)
        self.assertFalse([e for e in entries if "(I)" in e], f"inherited entries remain: {entries}")
        self.assertTrue([e for e in entries if "SYSTEM" in e], entries)
        self.assertFalse([e for e in entries if "Everyone" in e or "Users" in e], entries)

    def test_the_state_directory_and_token_admit_this_user_and_system_only(self) -> None:
        state = self.parent / "agent-bus"
        state.mkdir()
        self.assertTrue([e for e in self.icacls(state) if "Everyone" in e], "the fixture did not inherit Everyone")
        ensure_state_dir(state)
        self.assertPrivate(state)
        load_or_create_token(state)
        self.assertPrivate(state / "token")
        (state / "later").write_text("x", encoding="utf-8")
        self.assertFalse([e for e in self.icacls(state / "later") if "Everyone" in e])

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
            self.assertTrue([e for e in self.icacls(path) if "Everyone" in e and "(I)" not in e], path)
        ensure_state_dir(state)
        for path in (state, token, db):
            self.assertPrivate(path)
        self.assertEqual(load_or_create_token(state), "left-behind-token")
        self.assertEqual(token.read_bytes(), b"left-behind-token\n")

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
        self.assertTrue([e for e in self.icacls(outside) if "Everyone" in e], "the link's target was changed")
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
        self.assertTrue([e for e in self.icacls(theirs) if "Everyone" in e], "a refused directory was changed")


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


if __name__ == "__main__":
    unittest.main()

"""M7e: the daemon as a background service, so nobody has to keep a terminal.

The bus is only useful while the daemon runs, and the pull beta asked the user
to dedicate a window to it. That window is the first thing that gets closed by
accident and the last thing anybody remembers to reopen, so this turns it into
a per-user service: launchd on macOS, systemd `--user` on Linux and WSL2.

Three rules shape everything here:

* **The user's own session, never the system's.** A LaunchAgent and a systemd
  user unit run as the person who installed them, with their home directory
  and their file permissions. A LaunchDaemon or a system unit would run the
  bus as root, and the state directory is private user data.
* **Nothing is silently replaced.** Every file carries an ownership marker,
  and a service file without it belongs to somebody else and is left exactly
  where it is -- refused loudly, not backed up and overwritten, because
  something else on the machine is relying on it.
* **A service must not weaken identity.** The unit always serves with strict
  binding, and `--allow-unattributed` is refused outright: a background daemon
  is exactly where nobody would notice unverified sessions being trusted.
* **Nothing in the unit may depend on a search path.** A service manager
  starts processes with its own environment, so the interpreter is named
  absolutely rather than found; the user's PATH is carried in separately, for
  the dispatcher's sake.

Windows is not covered. ADR 0002 scopes v1 of the daemon to macOS, Linux and
WSL2, and the identity layer underneath it reads ttys and process groups
through `ps` and `lsof`; a Windows service would be a port of the daemon, not
a service file for it.

## The claim question, when there is no window

A service has no console, so the one-time approval code has nowhere private to
go: a log file is readable by the very session that is asking, which would
turn the two-phase claim into a formality (ADR 0004). Where the daemon can
raise a dialog -- a macOS LaunchAgent runs in the GUI session, and a systemd
unit does when the install captured `DISPLAY` -- the click still works. Where
it cannot, `agent_claim_begin` fails closed and says how to get a channel
back: bind the terminal with `run`, or serve in a terminal and approve with
the printed code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from xml.sax.saxutils import escape as xml_escape

from .statedir import resolve_state_dir
from .watch import LAUNCHER_NAME

#: Present in every file this module writes. Ownership is proven by content,
#: not by a path: a path can be reused by anything.
MARKER = "luciazero-managed: agentd-service"
LABEL = "com.luciazero.agentd"
UNIT = "luciazero-agentd.service"
DESCRIPTION = "Luciazero Agent Bus daemon"
DOCS = "https://github.com/ohm41321/luciazero/blob/main/docs/agent-bus.md"
#: Display variables copied into the unit at install time, so a Linux service
#: can still raise the claim dialog. Captured rather than imported into the
#: whole systemd user environment: the side effect belongs to this unit only.
DISPLAY_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY")
#: Stands in for the home directory when looking for service files. Set by
#: both test suites; `uninstall.sh` reads the same variable, so the two agree
#: on where a service would be.
ROOT_ENV = "LUCIAZERO_SERVICE_ROOT"


class ServiceError(RuntimeError):
    """Refusal: unsupported platform, a foreign file, or an unsafe argument."""


Runner = Callable[[list[str]], Any]


def run_command(argv: list[str]) -> Any:
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)


@dataclass
class Step:
    argv: list[str]
    #: True where a non-zero exit is ordinary: unloading a service that was
    #: never loaded, for instance, which must not fail an uninstall.
    optional: bool = False


@dataclass
class Plan:
    """Everything the install would do, before any of it is done."""

    kind: str  # "launchd" | "systemd"
    label: str
    files: list[tuple[Path, str]]
    install_steps: list[Step]
    uninstall_steps: list[Step]
    status_steps: list[Step]
    state_dir: Path
    log: Path
    command: list[str]
    notes: list[str] = field(default_factory=list)

    def paths(self) -> list[Path]:
        return [path for path, _ in self.files]


def _package_home() -> Path:
    """The directory `luciazero_agentd` lives in, which is what PYTHONPATH
    needs when there is no installed launcher."""
    return Path(__file__).resolve().parents[1]


def serve_command(launcher: Optional[str] = None,
                  which: Optional[Callable[[str], Optional[str]]] = None,
                  executable: Optional[str] = None,
                  ) -> tuple[list[str], dict[str, str]]:
    """The absolute command a service manager can exec, and its environment.

    The interpreter is named outright, and the installed launcher is
    deliberately *not* used even when it exists. A service manager starts
    processes with its own PATH -- a macOS LaunchAgent gets
    `/usr/bin:/bin:/usr/sbin:/sbin`, where `python3` is the system 3.9 -- so
    the launcher would search that PATH, find no interpreter at 3.10, and exit
    127 on every restart while `launchctl bootstrap` and `service status` both
    reported success. The interpreter running this install is one that already
    satisfies the floor, so it is the one recorded.
    """
    interpreter = Path(executable or sys.executable)
    if not str(interpreter):
        raise ServiceError(
            "this Python cannot name its own interpreter (sys.executable is empty), "
            "so there is no absolute command to give the service manager")
    return [str(interpreter.resolve()), "-m", "luciazero_agentd"], \
        {"PYTHONPATH": str(_package_home())}


def _serve_args(state_dir: Path, host: str, port: int, approve_with: str) -> list[str]:
    # Strict binding is the whole point of running unattended: no
    # --allow-unattributed, ever, and the caller cannot add one (see plan()).
    return ["serve", "--state-dir", str(state_dir), "--host", host,
            "--port", str(port), "--approve-with", approve_with]


def launchd_plist(label: str, argv: list[str], env: dict[str, str],
                  log: Path, workdir: Path) -> str:
    def entry(value: str) -> str:
        return f"    <string>{xml_escape(str(value))}</string>"

    arguments = "\n".join(entry(a) for a in argv)
    variables = "\n".join(
        f"    <key>{xml_escape(k)}</key>\n    <string>{xml_escape(v)}</string>"
        for k, v in sorted(env.items()))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- {MARKER} -->
<!-- Written by `luciazero-agentd service install`. Edit it there, not here:
     an install will refuse to touch a file it does not recognise. -->
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{xml_escape(label)}</string>
  <key>ProgramArguments</key>
  <array>
{arguments}
  </array>
  <key>EnvironmentVariables</key>
  <dict>
{variables}
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ProcessType</key>
  <string>Background</string>
  <key>WorkingDirectory</key>
  <string>{xml_escape(str(workdir))}</string>
  <key>StandardOutPath</key>
  <string>{xml_escape(str(log))}</string>
  <key>StandardErrorPath</key>
  <string>{xml_escape(str(log))}</string>
  <key>LuciazeroManaged</key>
  <string>{MARKER}</string>
</dict>
</plist>
"""


def _no_specifier(value: str) -> str:
    """`%` starts a systemd specifier, so `/tmp/100%done` would reach the unit
    as `%d` and silently point the daemon at another directory. Doubling it is
    how systemd spells a literal percent."""
    return str(value).replace("%", "%%")


def _systemd_quote(value: str) -> str:
    """systemd's own quoting, which is not the shell's: a double-quoted string
    with backslash escapes. Applied always, so a path with a space or a quote
    in it cannot split an ExecStart into two arguments, and specifiers are
    neutralised so it cannot mean a different path than it reads as."""
    escaped = _no_specifier(str(value).replace("\\", "\\\\").replace('"', '\\"'))
    return '"' + escaped + '"'


def systemd_unit(argv: list[str], env: dict[str, str], log: Path, workdir: Path) -> str:
    exec_start = " ".join(_systemd_quote(a) for a in argv)
    environment = "".join(
        f"Environment={_systemd_quote(f'{k}={v}')}\n" for k, v in sorted(env.items()))
    return f"""# {MARKER}
# Written by `luciazero-agentd service install`. Edit it there, not here:
# an install will refuse to touch a file it does not recognise.
[Unit]
Description={DESCRIPTION}
Documentation={DOCS}

[Service]
Type=simple
ExecStart={exec_start}
{environment}WorkingDirectory={_systemd_quote(str(workdir))}
Restart=on-failure
RestartSec=5
StandardOutput=append:{_no_specifier(log)}
StandardError=append:{_no_specifier(log)}

[Install]
WantedBy=default.target
"""


def plan(*, state_dir: Optional[str] = None, root: Optional[Path] = None,
         platform: str = sys.platform, host: str = "127.0.0.1", port: int = 8765,
         approve_with: str = "auto", launcher: Optional[str] = None,
         uid: Optional[int] = None, environ: Optional[dict[str, str]] = None,
         which: Callable[[str], Optional[str]] = shutil.which) -> Plan:
    """What installing would write and run. Nothing is written here.

    `root` stands in for the home directory, which is how the tests keep every
    service file inside a temporary directory and off the developer's machine.
    """
    if platform in ("win32", "cygwin"):
        raise ServiceError(
            "no Windows service in v1: the daemon's identity layer reads ttys and "
            "process groups through ps and lsof (ADR 0002 scopes v1 to macOS, Linux "
            "and WSL2). Run `luciazero-agentd serve` in a window, or use WSL2.")
    if approve_with not in ("auto", "dialog", "console"):
        raise ServiceError(f"unknown approval channel {approve_with!r}")

    environ = dict(os.environ if environ is None else environ)
    # ROOT_ENV is what keeps a test suite (this one and the shell one) from
    # ever reading or writing the developer's real LaunchAgents directory.
    home = Path(root) if root is not None else Path(environ.get(ROOT_ENV) or Path.home())
    resolved = resolve_state_dir(state_dir)
    log = resolved / "daemon.log"
    argv_head, env = serve_command(launcher, which=which)
    argv = argv_head + _serve_args(resolved, host, port, approve_with)
    if "--allow-unattributed" in argv:
        raise ServiceError("a service must not run with --allow-unattributed")
    env = dict(env)
    env["LUCIAZERO_AGENT_BUS_HOME"] = str(resolved)
    # A service manager's PATH is not the user's: a LaunchAgent gets
    # /usr/bin:/bin:/usr/sbin:/sbin. The daemon itself no longer needs PATH
    # (its interpreter is absolute), but the dispatcher starts providers by
    # name, and `codex` lives in the user's PATH and nowhere else.
    if environ.get("PATH"):
        env["PATH"] = environ["PATH"]
    # A newline ends a directive in a systemd unit, so a path carrying one
    # would add a line of its own -- an ExecStartPre=, say -- to a file the
    # user believes describes one command. Nothing legitimate needs it, and
    # quoting cannot save it, so it is refused before a file is generated.
    for value in [str(home), str(resolved), str(log), *argv, *env.values()]:
        if any(bad in value for bad in ("\n", "\r", "\x00")):
            raise ServiceError(
                f"refusing to write a service file for a path containing a newline "
                f"or a null byte: {value!r}")

    notes: list[str] = []
    if platform == "darwin":
        path = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        content = launchd_plist(LABEL, argv, env, log, home)
        target = f"gui/{os.getuid() if uid is None else uid}"
        install_steps = [Step(["launchctl", "bootout", f"{target}/{LABEL}"], optional=True),
                         Step(["launchctl", "bootstrap", target, str(path)])]
        uninstall_steps = [Step(["launchctl", "bootout", f"{target}/{LABEL}"], optional=True)]
        status_steps = [Step(["launchctl", "print", f"{target}/{LABEL}"], optional=True)]
        notes.append("A LaunchAgent runs in your GUI session, so the claim dialog still works.")
        kind = "launchd"
    else:
        path = home / ".config" / "systemd" / "user" / UNIT
        for name in DISPLAY_VARS:
            if environ.get(name):
                env[name] = environ[name]
        content = systemd_unit(argv, env, log, home)
        install_steps = [Step(["systemctl", "--user", "daemon-reload"]),
                         Step(["systemctl", "--user", "enable", "--now", UNIT])]
        uninstall_steps = [Step(["systemctl", "--user", "disable", "--now", UNIT], optional=True),
                           Step(["systemctl", "--user", "daemon-reload"], optional=True)]
        status_steps = [Step(["systemctl", "--user", "is-active", UNIT], optional=True)]
        if any(name in env for name in DISPLAY_VARS):
            notes.append("Your current display was captured into the unit, so the claim dialog "
                         "should work; re-run install after switching sessions.")
        else:
            notes.append("No DISPLAY or WAYLAND_DISPLAY here, so the service will have no screen: "
                         "claims fail closed until you serve in a terminal or bind with `run`.")
        kind = "systemd"

    return Plan(kind=kind, label=LABEL if kind == "launchd" else UNIT,
                files=[(path, content)], install_steps=install_steps,
                uninstall_steps=uninstall_steps, status_steps=status_steps,
                state_dir=resolved, log=log, command=argv, notes=notes)


def _owned(path: Path) -> bool:
    """Ours only if it is a regular file that says so. A symlink is somebody's
    deliberate arrangement and is never followed into a write."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def file_state(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if not path.exists():
        return "absent"
    if not path.is_file():
        return "foreign"
    return "ours" if _owned(path) else "foreign"


def write_files(plan_: Plan, *, dry_run: bool = False) -> list[tuple[Path, str]]:
    """Create or refresh the service files. Refuses anything not ours."""
    results: list[tuple[Path, str]] = []
    for path, content in plan_.files:
        state = file_state(path)
        if state in ("foreign", "symlink"):
            raise ServiceError(
                f"{path} exists and is not a Luciazero service file; left untouched. "
                "Remove it yourself if you are sure, or install under a different label.")
        if state == "ours" and path.read_text(encoding="utf-8") == content:
            results.append((path, "unchanged"))
            continue
        action = "updated" if state == "ours" else "created"
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        results.append((path, action))
    return results


def run_steps(steps: list[Step], *, runner: Optional[Runner] = None) -> list[tuple[list[str], int, str]]:
    """Run the service manager's commands, stopping at the first required one
    that fails so a half-installed service is reported rather than claimed."""
    # Resolved here, not in the signature, so a test can replace run_command
    # on the module and be sure nothing reaches the real service manager.
    call = run_command if runner is None else runner
    out: list[tuple[list[str], int, str]] = []
    for step in steps:
        try:
            result = call(step.argv)
        except (OSError, subprocess.SubprocessError) as exc:
            if step.optional:
                out.append((step.argv, 127, str(exc)))
                continue
            raise ServiceError(
                f"could not run {' '.join(step.argv)}: {exc}. "
                "Install the service manager's client, or run `luciazero-agentd serve` yourself."
            ) from exc
        code = int(getattr(result, "returncode", 0) or 0)
        message = (str(getattr(result, "stderr", "") or "")
                   or str(getattr(result, "stdout", "") or "")).strip()
        out.append((step.argv, code, message))
        if code != 0 and not step.optional:
            raise ServiceError(f"{' '.join(step.argv)} failed ({code}): {message or 'no output'}")
    return out


def install(plan_: Plan, *, runner: Optional[Runner] = None, dry_run: bool = False) -> dict[str, Any]:
    written = write_files(plan_, dry_run=dry_run)
    steps = [] if dry_run else run_steps(plan_.install_steps, runner=runner)
    return {"kind": plan_.kind, "label": plan_.label, "dry_run": dry_run,
            "files": [(str(p), a) for p, a in written],
            "steps": [(argv, code, msg) for argv, code, msg in steps],
            "log": str(plan_.log), "notes": list(plan_.notes)}


def uninstall(plan_: Plan, *, runner: Optional[Runner] = None, dry_run: bool = False) -> dict[str, Any]:
    """Stop the service, then delete only the files this module wrote."""
    steps = [] if dry_run else run_steps(plan_.uninstall_steps, runner=runner)
    removed: list[tuple[str, str]] = []
    for path in plan_.paths():
        state = file_state(path)
        if state == "absent":
            removed.append((str(path), "absent"))
        elif state == "ours":
            if not dry_run:
                path.unlink()
            removed.append((str(path), "removed"))
        else:
            removed.append((str(path), "left untouched (not ours)"))
    return {"kind": plan_.kind, "label": plan_.label, "dry_run": dry_run,
            "files": removed, "steps": [(argv, code, msg) for argv, code, msg in steps]}


def status(plan_: Plan, *, runner: Optional[Runner] = None) -> dict[str, Any]:
    files = [(str(path), file_state(path)) for path in plan_.paths()]
    steps = run_steps(plan_.status_steps, runner=runner)
    active = None
    if steps:
        argv, code, message = steps[0]
        active = code == 0
    return {"kind": plan_.kind, "label": plan_.label, "files": files,
            "installed": all(state == "ours" for _, state in files),
            "active": active, "probe": [(argv, code, msg) for argv, code, msg in steps],
            "state_dir": str(plan_.state_dir), "log": str(plan_.log),
            "command": list(plan_.command), "notes": list(plan_.notes)}

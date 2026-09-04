"""M7d: asking the person, without asking them to open a terminal.

The claim needs an answer from somewhere the asking session cannot reach.
`claim approve --code` gets that from the daemon's own console, and it works
everywhere -- but it costs the user a second window and a copied code for
every session they start, which is exactly the kind of toll that ends with the
identity system switched off.

There is a better place: a dialog the *daemon* puts on screen. The session
that asked cannot read it, cannot dismiss it, and cannot press its buttons --
driving another process's UI needs a permission a terminal does not have
unless the user granted it (see the caveat in ADR 0004). The user clicks Allow
and their session is verified; nothing is typed and nothing is copied.

One backend per desktop, first available wins, and every one of them degrades
to the console code rather than failing:

* macOS: `osascript` (always present).
* Linux/BSD: `zenity`, then `kdialog`. Neither is guaranteed to be installed,
  and a headless or SSH session has no display, so this is the platform where
  the console route stays the common case.
* Windows: PowerShell's `MessageBox`. The command is passed as
  `-EncodedCommand`, which is UTF-16LE base64, so no quoting rule of any shell
  or of PowerShell itself has a say in what the peer-supplied text means.

Note that ADR 0002 scopes v1 of the daemon itself to macOS, Linux and WSL2;
the Windows backend here is the dialog, not a claim that the whole daemon runs
natively on Windows yet.

The dialog is a *channel* for the same decision, not a second kind of
decision: it approves the same claim request, through the same
`decide_claim`, holding the same code the console would have printed.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import threading
from typing import Any, Callable, NamedTuple, Optional

#: Set this and the daemon never raises a window: the console code is used
#: instead. The test suite arms it, because a suite that can open a modal
#: dialog on the developer's screen will eventually do it in CI.
NO_DIALOG_ENV = "LUCIAZERO_AGENT_BUS_NO_DIALOG"

#: Exit code `osascript` returns when the user picks the cancel button.
USER_CANCELLED = 1
DIALOG_TIMEOUT_MARGIN = 5


def applescript(title: str, body: str, allow: str, deny: str, seconds: int) -> str:
    """One modal dialog, as AppleScript.

    Every value is escaped here rather than interpolated: the agent id and the
    client name come from the session that is asking, and a quote in either
    would otherwise end the string and start running whatever followed it.
    """
    def quoted(value: str) -> str:
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

    return (
        f'display dialog {quoted(body)} with title {quoted(title)} '
        f'buttons {{{quoted(deny)}, {quoted(allow)}}} default button {quoted(deny)} '
        f'with icon caution giving up after {int(seconds)}'
    )


def powershell(title: str, body: str, allow: str, deny: str) -> str:
    """The same question as a Windows MessageBox.

    Single-quoted PowerShell strings have exactly one escape -- a doubled
    quote -- and the whole thing is then base64'd into `-EncodedCommand`, so
    no shell and no PowerShell parsing rule ever sees the peer's text.
    """
    def quoted(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    return (
        "Add-Type -AssemblyName System.Windows.Forms | Out-Null; "
        f"$a = [System.Windows.Forms.MessageBox]::Show({quoted(body)}, {quoted(title)}, "
        "[System.Windows.Forms.MessageBoxButtons]::YesNo, "
        "[System.Windows.Forms.MessageBoxIcon]::Warning, "
        "[System.Windows.Forms.MessageBoxDefaultButton]::Button2); "
        f"if ($a -eq [System.Windows.Forms.DialogResult]::Yes) {{ Write-Output {quoted('button returned:' + allow)} }} "
        f"else {{ Write-Output {quoted('button returned:' + deny)} }}"
    )


def encoded(command: str) -> str:
    return base64.b64encode(command.encode("utf-16-le")).decode("ascii")


def _osascript(title: str, body: str, allow: str, deny: str, seconds: int) -> list[str]:
    return ["osascript", "-e", applescript(title, body, allow, deny, seconds)]


def _zenity(title: str, body: str, allow: str, deny: str, seconds: int) -> list[str]:
    # Arguments, not a command line: nothing here goes through a shell, so the
    # text needs no escaping and cannot become an option.
    return ["zenity", "--question", "--title", title, "--text", body,
            "--ok-label", allow, "--cancel-label", deny, "--default-cancel",
            "--timeout", str(int(seconds))]


def _kdialog(title: str, body: str, allow: str, deny: str, seconds: int) -> list[str]:
    return ["kdialog", "--title", title, "--warningyesno", body,
            "--yes-label", allow, "--no-label", deny]


def _powershell(title: str, body: str, allow: str, deny: str, seconds: int) -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
            encoded(powershell(title, body, allow, deny))]


class Backend(NamedTuple):
    name: str
    binary: str
    argv: Callable[[str, str, str, str, int], list[str]]
    #: True when a non-zero exit means "the user said no" rather than "this
    #: could not run at all". zenity and kdialog answer with the exit code.
    refusal_exit: tuple[int, ...]


BACKENDS: tuple[Backend, ...] = (
    Backend("osascript", "osascript", _osascript, (USER_CANCELLED,)),
    Backend("zenity", "zenity", _zenity, (1,)),
    Backend("kdialog", "kdialog", _kdialog, (1,)),
    Backend("powershell", "powershell", _powershell, ()),
)
#: Which backends are even considered, per platform. A Linux box with neither
#: zenity nor kdialog installed, or no display at all, simply has no dialog.
PLATFORMS = {"darwin": ("osascript",), "win32": ("powershell",), "cygwin": ("powershell",)}
LINUX_BACKENDS = ("zenity", "kdialog")


def backends_for(platform: str = sys.platform) -> tuple[Backend, ...]:
    wanted = PLATFORMS.get(platform, LINUX_BACKENDS)
    return tuple(b for b in BACKENDS if b.name in wanted)


def has_display(platform: str = sys.platform) -> bool:
    """A Linux session with no display cannot be asked anything."""
    if platform in ("darwin", "win32", "cygwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def pick(platform: str = sys.platform, which: Callable[[str], Optional[str]] = shutil.which) -> Optional[Backend]:
    """The first dialog program this machine actually has."""
    if os.environ.get(NO_DIALOG_ENV) or not has_display(platform):
        return None
    for backend in backends_for(platform):
        if which(backend.binary):
            return backend
    return None


def dialog_available() -> bool:
    """Whether this machine can be asked on screen at all. Everywhere else
    falls back to the console code, which needs no GUI and no permissions."""
    return pick() is not None


def ask(title: str, body: str, *, allow: str = "Allow", deny: str = "Deny",
        seconds: int = 120, runner: Optional[Callable[[list[str], int], Any]] = None,
        backend: Optional[Backend] = None) -> Optional[bool]:
    """Put the question on screen. True to allow, False to deny, None if
    nobody answered before it gave up."""
    backend = backend or pick()
    if backend is None and runner is None:
        return None
    backend = backend or BACKENDS[0]
    run = runner or (lambda argv, timeout: subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False))
    try:
        result = run(backend.argv(title, body, allow, deny, seconds), seconds + DIALOG_TIMEOUT_MARGIN)
    except (subprocess.TimeoutExpired, OSError):
        # The window was killed with the timeout, or never opened. Neither is
        # an answer, and neither may be read as one.
        return None
    code = int(getattr(result, "returncode", 1) or 0)
    if code != 0:
        return False if code in backend.refusal_exit else None
    answer = str(getattr(result, "stdout", "") or "")
    # osascript writes "button returned:, gave up:true"; the spaces are
    # stripped from the haystack, so the needle must be stripped too.
    if "gaveup:true" in answer.replace(" ", ""):
        return None
    if not answer.strip():
        # zenity and kdialog say yes with exit 0 and print nothing.
        return True
    return f"button returned:{allow}" in answer


def prompt(request: dict[str, Any], *, decide: Callable[[bool], None], seconds: int,
           runner: Optional[Callable[[list[str], int], Any]] = None,
           on_error: Optional[Callable[[BaseException], None]] = None) -> threading.Thread:
    """Ask about one claim, off the request thread.

    The daemon must keep answering while the dialog is up: a modal window is
    the user's to leave open, and blocking the bus behind it would make every
    other session hang on one person's attention.
    """
    body = (f"A {request['provider']} session is asking to act as \"{request['agent_id']}\" "
            f"on the Luciazero Agent Bus.\n\n"
            f"Client: {request.get('client') or 'not stated'}\n"
            f"Request: {request['id']}\n"
            f"Session: #{request.get('session_fingerprint', '')}\n\n"
            "Allow only if you just started that session yourself. "
            "Everything it writes will be recorded as that agent.")

    def run() -> None:
        try:
            answer = ask("Luciazero Agent Bus", body, seconds=seconds, runner=runner)
            if answer is not None:
                decide(answer)
        except BaseException as exc:  # noqa: BLE001 - a background thread must not die silently
            if on_error is not None:
                on_error(exc)

    thread = threading.Thread(target=run, name="claim-dialog", daemon=True)
    thread.start()
    return thread

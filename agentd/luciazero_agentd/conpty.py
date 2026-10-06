"""Windows: `run` holding the provider's console, as it holds a pty elsewhere.

What nudge.py needs from a terminal is to be the way into it, so that a
delivery arriving while the session sits idle can be typed at its prompt. On
macOS and Linux the provider gets a pty and `run` copies bytes both ways.
Windows 10 1809 and later have the same thing in the pseudo console (ConPTY):
the provider starts attached to one, its screen arrives on a pipe as VT
sequences, and what is written to the other pipe reaches it as keystrokes.
`run` puts its own console in VT mode -- raw input, VT output, UTF-8 -- copies
between the two, and puts every mode and code page back however it ends.

There is no select() over a console and a pipe, so each direction has a
thread of its own, and the loop that decides when to knock stays on the main
thread, as it does in nudge.proxy. The threads only move bytes and note that
something moved; the watcher is called from the loop.

The provider starts suspended, is put in a Job Object of its own and only
then resumed, as proctree.start does it, so ending the job ends everything
the session started. Imported only on Windows.
"""

from __future__ import annotations

import codecs
import ctypes
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Mapping, Optional, Sequence

if sys.platform != "win32":  # pragma: no cover - nudge imports this on Windows only
    raise ImportError("luciazero_agentd.conpty is Windows-only")

from . import winproc
from .nudge import POLL_SECONDS, Arrival, Typist, Watcher, knock

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HAVE_CONPTY = hasattr(_kernel32, "CreatePseudoConsole")
STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
DISABLE_NEWLINE_AUTO_RETURN = 0x0008
CP_UTF8 = 65001
KEY_EVENT = 0x0001
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
STILL_ACTIVE = 259
ERROR_BROKEN_PIPE = 109
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
DEFAULT_SIZE = (120, 30)


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT), ("Right", wintypes.SHORT),
                ("Bottom", wintypes.SHORT)]


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                ("uChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]


class _EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("raw", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("Event", _EVENT)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


def _bind(name: str, argtypes: list, restype: object) -> None:
    function = getattr(_kernel32, name)
    function.argtypes = argtypes
    function.restype = restype


_bind("GetStdHandle", [wintypes.DWORD], wintypes.HANDLE)
_bind("GetConsoleMode", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
_bind("SetConsoleMode", [wintypes.HANDLE, wintypes.DWORD], wintypes.BOOL)
_bind("GetConsoleCP", [], wintypes.UINT)
_bind("SetConsoleCP", [wintypes.UINT], wintypes.BOOL)
_bind("GetConsoleOutputCP", [], wintypes.UINT)
_bind("SetConsoleOutputCP", [wintypes.UINT], wintypes.BOOL)
_bind("GetConsoleScreenBufferInfo", [wintypes.HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)], wintypes.BOOL)
_bind("PeekConsoleInputW", [wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD), wintypes.DWORD,
                            ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
_bind("ReadConsoleInputW", [wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD), wintypes.DWORD,
                            ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
_bind("ReadConsoleW", [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                       ctypes.c_void_p], wintypes.BOOL)
_bind("WriteConsoleW", [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                        ctypes.c_void_p], wintypes.BOOL)
_bind("ReadFile", [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                   ctypes.c_void_p], wintypes.BOOL)
_bind("WriteFile", [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                    ctypes.c_void_p], wintypes.BOOL)
_bind("CreatePipe", [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p,
                     wintypes.DWORD], wintypes.BOOL)
_bind("CloseHandle", [wintypes.HANDLE], wintypes.BOOL)
_bind("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD)
_bind("GetExitCodeProcess", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)
_bind("TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL)
_bind("ResumeThread", [wintypes.HANDLE], wintypes.DWORD)
_bind("InitializeProcThreadAttributeList", [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                            ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL)
_bind("UpdateProcThreadAttribute", [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL)
_bind("DeleteProcThreadAttributeList", [ctypes.c_void_p], None)
_bind("CreateProcessW", [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                         wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                         ctypes.POINTER(PROCESS_INFORMATION)], wintypes.BOOL)
if HAVE_CONPTY:
    _bind("CreatePseudoConsole", [COORD, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.HANDLE)], ctypes.c_long)
    _bind("ResizePseudoConsole", [wintypes.HANDLE, COORD], ctypes.c_long)
    _bind("ClosePseudoConsole", [wintypes.HANDLE], None)


def _fail(what: str) -> OSError:
    error = ctypes.get_last_error()
    return OSError(error, f"{what}: {ctypes.FormatError(error)}")


def _console_mode(handle: int) -> Optional[int]:
    mode = wintypes.DWORD()
    return int(mode.value) if _kernel32.GetConsoleMode(handle, ctypes.byref(mode)) else None


def std_handle(which: int) -> int:
    return int(_kernel32.GetStdHandle(which) or 0)


def usable() -> bool:
    """A pseudo console exists on this Windows, and stdin and stdout are a
    console to proxy (not a pipe, a file or NUL)."""
    return (HAVE_CONPTY and _console_mode(std_handle(STD_INPUT_HANDLE)) is not None
            and _console_mode(std_handle(STD_OUTPUT_HANDLE)) is not None)


def window_size(handle: int) -> Optional[tuple[int, int]]:
    """The visible window of a console, in cells, or None for anything else."""
    info = CONSOLE_SCREEN_BUFFER_INFO()
    if not _kernel32.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
        return None
    window = info.srWindow
    return max(1, window.Right - window.Left + 1), max(1, window.Bottom - window.Top + 1)


def _environment_block(env: Mapping[str, str]) -> ctypes.Array:
    # CreateProcess wants the block sorted by name, case-insensitively.
    entries = sorted(env.items(), key=lambda item: item[0].upper())
    return ctypes.create_unicode_buffer("".join(f"{name}={value}\0" for name, value in entries) + "\0")


class Session:
    """A provider on a pseudo console: its pid, the two pipes, its job."""

    def __init__(self, argv: Sequence[str], env: Mapping[str, str],
                 size: tuple[int, int] = DEFAULT_SIZE) -> None:
        if not HAVE_CONPTY:
            raise OSError("this Windows has no pseudo console (Windows 10 1809 or later has one)")
        self._lock = threading.Lock()
        self._closed = False
        self.size = size
        in_read, self._in_write = wintypes.HANDLE(), wintypes.HANDLE()
        self._out_read, out_write = wintypes.HANDLE(), wintypes.HANDLE()
        if not _kernel32.CreatePipe(ctypes.byref(in_read), ctypes.byref(self._in_write), None, 0):
            raise _fail("CreatePipe")
        if not _kernel32.CreatePipe(ctypes.byref(self._out_read), ctypes.byref(out_write), None, 0):
            error = _fail("CreatePipe")
            _kernel32.CloseHandle(in_read)
            _kernel32.CloseHandle(self._in_write)
            raise error
        self._console = wintypes.HANDLE()
        try:
            result = _kernel32.CreatePseudoConsole(COORD(*size), in_read, out_write, 0, ctypes.byref(self._console))
            if result < 0:
                raise OSError(result & 0xFFFFFFFF, f"CreatePseudoConsole failed (HRESULT {result & 0xFFFFFFFF:#010x})")
            self._process, self.pid, self.job = self._start(argv, env)
        except BaseException:
            for handle in (self._in_write, self._out_read):
                _kernel32.CloseHandle(handle)
            if self._console:
                _kernel32.ClosePseudoConsole(self._console)
            raise
        finally:
            # The pseudo console holds its own copies of these two.
            _kernel32.CloseHandle(in_read)
            _kernel32.CloseHandle(out_write)

    def _start(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, int, Optional[winproc.Job]]:
        size = ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        if not _kernel32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
            raise _fail("InitializeProcThreadAttributeList")
        try:
            if not _kernel32.UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                                                       self._console.value, ctypes.sizeof(wintypes.HANDLE),
                                                       None, None):
                raise _fail("UpdateProcThreadAttribute")
            startup = STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            # Without this a child whose parent's stdio is redirected writes
            # to those handles and not to the pseudo console.
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = INVALID_HANDLE_VALUE
            startup.StartupInfo.hStdOutput = INVALID_HANDLE_VALUE
            startup.StartupInfo.hStdError = INVALID_HANDLE_VALUE
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            info = PROCESS_INFORMATION()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
            flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | winproc.CREATE_SUSPENDED
            if not _kernel32.CreateProcessW(None, command, None, None, False, flags, _environment_block(env),
                                            None, ctypes.byref(startup), ctypes.byref(info)):
                raise _fail(f"cannot start {argv[0]}")
        finally:
            _kernel32.DeleteProcThreadAttributeList(attributes)
        job: Optional[winproc.Job] = None
        try:
            job = winproc.Job()
            job.add(int(info.dwProcessId))
        except OSError:
            if job is not None:
                job.close()
            job = None  # uncontained: ended by its tree instead, as proctree.start does
        resumed = _kernel32.ResumeThread(info.hThread) != 0xFFFFFFFF
        _kernel32.CloseHandle(info.hThread)
        if not resumed:
            error = _fail("ResumeThread")
            _kernel32.TerminateProcess(info.hProcess, 1)
            _kernel32.CloseHandle(info.hProcess)
            if job is not None:
                job.close()
            raise error
        return int(info.hProcess), int(info.dwProcessId), job

    # -------------------------------------------------------------- the pipes
    def write(self, data: bytes) -> None:
        """Keystrokes for the provider. Serialised, so a typed line never
        lands in the middle of the user's escape sequence."""
        with self._lock:
            view = memoryview(data)
            while view:
                written = wintypes.DWORD()
                buffer = (ctypes.c_char * len(view)).from_buffer_copy(view)
                if not _kernel32.WriteFile(self._in_write, buffer, len(view), ctypes.byref(written), None):
                    raise _fail("WriteFile")
                view = view[written.value:]

    def read(self, limit: int = 65536) -> bytes:
        """The provider's screen, as VT bytes; b"" once the pseudo console
        has closed."""
        buffer = ctypes.create_string_buffer(limit)
        got = wintypes.DWORD()
        if not _kernel32.ReadFile(self._out_read, buffer, limit, ctypes.byref(got), None):
            return b""
        return buffer.raw[:got.value]

    def resize(self, size: tuple[int, int]) -> None:
        if size != self.size and not self._closed:
            self.size = size
            _kernel32.ResizePseudoConsole(self._console, COORD(*size))

    # ------------------------------------------------------------ the process
    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """The exit code, or None if it is still running after `timeout`."""
        milliseconds = INFINITE if timeout is None else max(0, int(timeout * 1000))
        if _kernel32.WaitForSingleObject(self._process, milliseconds) != WAIT_OBJECT_0:
            return None
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(self._process, ctypes.byref(code)):
            return 1
        return int(code.value)

    def end(self) -> None:
        """End the provider and everything it started."""
        if self.job is not None:
            self.job.terminate()
        else:
            _kernel32.TerminateProcess(self._process, 1)

    def close_console(self) -> None:
        """Close the pseudo console, which ends its output pipe once what is
        in it has been read; the reader must still be reading."""
        if not self._closed:
            self._closed = True
            _kernel32.ClosePseudoConsole(self._console)

    def close(self) -> None:
        self.close_console()
        for handle in (self._in_write, self._out_read):
            _kernel32.CloseHandle(handle)
        _kernel32.CloseHandle(self._process)
        if self.job is not None:
            self.job.close()  # anything the provider left running ends here


class _Console:
    """This process's own console, put in VT mode for the proxy and put back
    afterwards. Handles that are not a console (a pipe in a test) are left
    alone and read and written as bytes."""

    def __init__(self, stdin: int, stdout: int) -> None:
        self.stdin, self.stdout = stdin, stdout
        self.in_mode, self.out_mode = _console_mode(stdin), _console_mode(stdout)
        self.codepages: Optional[tuple[int, int]] = None
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def __enter__(self) -> "_Console":
        if self.in_mode is not None or self.out_mode is not None:
            self.codepages = (int(_kernel32.GetConsoleCP()), int(_kernel32.GetConsoleOutputCP()))
            _kernel32.SetConsoleCP(CP_UTF8)
            _kernel32.SetConsoleOutputCP(CP_UTF8)
        if self.in_mode is not None:
            raw = self.in_mode & ~(ENABLE_PROCESSED_INPUT | ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT
                                   | ENABLE_WINDOW_INPUT | ENABLE_MOUSE_INPUT)
            _kernel32.SetConsoleMode(self.stdin, raw | ENABLE_VIRTUAL_TERMINAL_INPUT)
        if self.out_mode is not None:
            _kernel32.SetConsoleMode(self.stdout, self.out_mode | ENABLE_PROCESSED_OUTPUT
                                     | ENABLE_VIRTUAL_TERMINAL_PROCESSING | DISABLE_NEWLINE_AUTO_RETURN)
        return self

    def __exit__(self, *_: object) -> None:
        if self.in_mode is not None:
            _kernel32.SetConsoleMode(self.stdin, self.in_mode)
        if self.out_mode is not None:
            _kernel32.SetConsoleMode(self.stdout, self.out_mode)
        if self.codepages is not None:
            _kernel32.SetConsoleCP(self.codepages[0])
            _kernel32.SetConsoleOutputCP(self.codepages[1])

    def size(self) -> Optional[tuple[int, int]]:
        return window_size(self.stdout) if self.out_mode is not None else None

    def write(self, data: bytes) -> None:
        if self.out_mode is None:
            view = memoryview(data)
            while view:
                written = wintypes.DWORD()
                buffer = (ctypes.c_char * len(view)).from_buffer_copy(view)
                if not _kernel32.WriteFile(self.stdout, buffer, len(view), ctypes.byref(written), None):
                    return
                view = view[written.value:]
            return
        # A UTF-8 character can arrive split across two reads; WriteConsoleW
        # gets whole characters only.
        text = self._decoder.decode(data)
        while text:
            written = wintypes.DWORD()
            if not _kernel32.WriteConsoleW(self.stdout, text, len(text), ctypes.byref(written), None):
                return
            text = text[written.value:]

    def _key_waiting(self) -> bool:
        """Whether a read of the console would return now. Only a key press
        makes ReadConsoleW return; focus changes and key releases sit in the
        buffer and would leave it blocked, so they are taken out here."""
        records = (INPUT_RECORD * 64)()
        count = wintypes.DWORD()
        if not _kernel32.PeekConsoleInputW(self.stdin, records, 64, ctypes.byref(count)) or not count.value:
            return False
        if any(r.EventType == KEY_EVENT and r.Event.KeyEvent.bKeyDown for r in records[:count.value]):
            return True
        _kernel32.ReadConsoleInputW(self.stdin, records, count.value, ctypes.byref(count))
        return False

    def read(self, stop: threading.Event) -> bytes:
        """Keystrokes as UTF-8 VT bytes; b"" at the end of a pipe or once
        `stop` is set."""
        if self.in_mode is None:
            buffer = ctypes.create_string_buffer(4096)
            got = wintypes.DWORD()
            if not _kernel32.ReadFile(self.stdin, buffer, 4096, ctypes.byref(got), None):
                return b""
            return buffer.raw[:got.value]
        pending = ""
        while not stop.is_set():
            if _kernel32.WaitForSingleObject(self.stdin, 100) != WAIT_OBJECT_0 or not self._key_waiting():
                continue
            buffer = ctypes.create_unicode_buffer(1024)
            got = wintypes.DWORD()
            if not _kernel32.ReadConsoleW(self.stdin, buffer, 1024, ctypes.byref(got), None):
                return b""
            text = pending + buffer[:got.value]
            pending = ""
            if text and "\ud800" <= text[-1] <= "\udbff":
                text, pending = text[:-1], text[-1]  # the other half is in the next read
            if text:
                return text.encode("utf-8", "surrogatepass")
        return b""


def spawn(argv: Sequence[str], env: Mapping[str, str]) -> Session:
    """Start the provider on a pseudo console the size of this console."""
    return Session(argv, env, window_size(std_handle(STD_OUTPUT_HANDLE)) or DEFAULT_SIZE)


def proxy(session: Session, *, watcher: Optional[Watcher] = None,
          stdin: Optional[int] = None, stdout: Optional[int] = None, poll: float = POLL_SECONDS,
          clock: Callable[[], float] = time.monotonic, typist: Optional[Typist] = None,
          show: Optional[Callable[[Arrival], None]] = None) -> int:
    """Copy between this console and the provider's pseudo console until the
    provider exits, typing a nudge into it when the watcher says a delivery
    arrived. Returns its exit code. The console's modes are restored however
    this returns."""
    stdin = std_handle(STD_INPUT_HANDLE) if stdin is None else stdin
    stdout = std_handle(STD_OUTPUT_HANDLE) if stdout is None else stdout
    typist = typist or Typist(session.write, clock=clock)
    stop = threading.Event()
    printed, typed = threading.Event(), threading.Event()
    with _Console(stdin, stdout) as console:

        def out() -> None:
            while True:
                data = session.read()
                if not data:
                    return
                console.write(data)
                printed.set()

        def into() -> None:
            while not stop.is_set():
                data = console.read(stop)
                if not data:
                    return
                try:
                    session.write(data)
                except OSError:
                    return
                typed.set()

        reader = threading.Thread(target=out, name="conpty-out", daemon=True)
        writer = threading.Thread(target=into, name="conpty-in", daemon=True)
        reader.start()
        writer.start()
        next_poll = clock() + poll
        code: Optional[int] = None
        try:
            while code is None:
                code = session.wait(0.1)
                size = console.size()
                if size is not None:
                    session.resize(size)
                # Seen by the threads, said to the watcher from here, as the
                # pty proxy does: a pane that printed is busy, a key means a
                # person is here. Neither carries the bytes.
                if printed.is_set():
                    printed.clear()
                    if watcher is not None:
                        watcher.saw_output()
                if typed.is_set():
                    typed.clear()
                    if watcher is not None:
                        watcher.human_typed()
                typist.tick()
                now = clock()
                if watcher is not None and now >= next_poll:
                    next_poll = now + poll
                    knock(watcher, typist, show)
        finally:
            stop.set()
            if code is None:
                session.end()
                session.wait(5.0)
            # What the provider printed on its way out still belongs on screen.
            session.close_console()
            reader.join(timeout=2.0)
            session.close()
    return int(code) if code is not None else 1

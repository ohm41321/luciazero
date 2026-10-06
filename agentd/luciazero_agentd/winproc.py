"""Windows process facts, from the Win32 API through ctypes, never from `ps`.

procinfo asks the process table three things -- which processes exist and
who their parents are, when one started, and whether it is this user's --
and on macOS and Linux `ps` answers. Windows has no `ps`, and the one Git for
Windows puts on PATH prints a table of its own that procinfo would read as
empty: no provider above this shell, so a session could approve its own
claim. On Windows the answers therefore come from the kernel:

* the table from a Toolhelp snapshot: pid, parent pid and image name, and
  for a node.exe, the script it runs, read from its command line -- an
  npm-installed provider is node.exe running the package's CLI script;
* a start time from GetProcessTimes: the creation FILETIME as a decimal
  string, opaque like the `ps` one and only ever compared with itself;
* ownership from the process token's user SID against this process's own.

It also holds the Windows side of a process tree. A provider starts
suspended, is put in a Job Object of its own before its first instruction
runs, and only then resumes, so everything it starts -- and everything those
start, orphaned or not -- is in the job, and ending the job ends all of it.
The job is set to kill what is left when its last handle closes, so a daemon
that dies takes its providers with it instead of leaving them holding a
credential.

It also holds the Windows side of a private file. chmod there only sets the
read-only bit, so the state directory, the token and a credential file get a
protected DACL instead -- this user and SYSTEM, nothing inherited -- which is
what 0700 and 0600 mean on POSIX.

Windows does not reparent an orphan, so a parent pid can name a process that
has exited, or a newer one that took its number. A parent that started after
its child is that newer process, and the edge is cut.

Every failure closes the way the POSIX path's does: a snapshot that cannot
be taken raises OSError (procinfo turns it into ProcessError), and a process
this user may not open is not this user's. Imported only on Windows.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any, Optional

if sys.platform != "win32":  # pragma: no cover - procinfo imports this on Windows only
    raise ImportError("luciazero_agentd.winproc is Windows-only")

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x00000002
PROCESS_TERMINATE = 0x00000001
PROCESS_SET_QUOTA = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
CREATE_SUSPENDED = 0x00000004
PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
SYNCHRONIZE = 0x00100000
TOKEN_QUERY = 0x0008
TOKEN_USER = 1  # TOKEN_INFORMATION_CLASS values
TOKEN_OWNER = 4
SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SDDL_REVISION_1 = 1
ERROR_ACCESS_DENIED = 5
ERROR_NO_MORE_FILES = 18
ERROR_INSUFFICIENT_BUFFER = 122
WAIT_TIMEOUT = 0x00000102
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PROCESS_COMMAND_LINE_INFORMATION = 60  # PROCESSINFOCLASS, Windows 8.1 and later
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
NODE_IMAGE = "node.exe"  # procinfo.WINDOWS_NODE_IMAGE
MAX_PID = 0xFFFFFFFF


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
_kernel32.Thread32First.restype = wintypes.BOOL
_kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
_kernel32.Thread32Next.restype = wintypes.BOOL
_kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenThread.restype = wintypes.HANDLE
_kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
_kernel32.ResumeThread.restype = wintypes.DWORD
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.TerminateProcess.restype = wintypes.BOOL
_kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
_kernel32.CreateJobObjectW.restype = wintypes.HANDLE
_kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_kernel32.SetInformationJobObject.restype = wintypes.BOOL
_kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
_kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.TerminateJobObject.restype = wintypes.BOOL
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
_kernel32.GetProcessTimes.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.GetCurrentProcess.argtypes = []
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]
_advapi32.GetTokenInformation.restype = wintypes.BOOL
_advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
_advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG)]
_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
_advapi32.GetSecurityDescriptorDacl.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
_advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
_advapi32.SetNamedSecurityInfoW.argtypes = [
    wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
_advapi32.GetNamedSecurityInfoW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
_advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
_ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                              ctypes.POINTER(wintypes.ULONG)]
_ntdll.NtQueryInformationProcess.restype = ctypes.c_ulong
_shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
_shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)

_own_sids: dict[int, Optional[str]] = {}


def _valid(pid: Any) -> bool:
    return isinstance(pid, int) and 0 < pid <= MAX_PID


def _open(pid: int, access: int) -> tuple[Optional[int], int]:
    """A handle to the process, or None and the Win32 error."""
    handle = _kernel32.OpenProcess(access, False, pid)
    if not handle:
        return None, ctypes.get_last_error()
    return handle, 0


def _created(handle: int) -> Optional[int]:
    times = [wintypes.FILETIME() for _ in range(4)]
    if not _kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return None
    value = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return value or None


def _running(handle: int) -> bool:
    return _kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT


def _sid_text(sid: int) -> Optional[str]:
    text = wintypes.LPWSTR()
    if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        return None
    try:
        return text.value
    finally:
        _kernel32.LocalFree(text)


def _sid_of(process: int, which: int = TOKEN_USER) -> Optional[str]:
    """The string SID of the user a process runs as (TOKEN_USER), or of the
    owner it gives what it creates (TOKEN_OWNER), or None if this process may
    not read it."""
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD(0)
        _advapi32.GetTokenInformation(token, which, None, 0, ctypes.byref(size))
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER or not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not _advapi32.GetTokenInformation(token, which, buffer, size, ctypes.byref(size)):
            return None
        # TOKEN_USER and TOKEN_OWNER both begin with the SID pointer.
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
        return _sid_text(sid) if sid else None
    finally:
        _kernel32.CloseHandle(token)


def _my_sid(which: int = TOKEN_USER) -> Optional[str]:
    if _own_sids.get(which) is None:
        _own_sids[which] = _sid_of(_kernel32.GetCurrentProcess(), which)
    return _own_sids[which]


def owner_of(path: str) -> Optional[str]:
    """The string SID that owns a file or directory, or None if it cannot be
    read."""
    owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
    error = _advapi32.GetNamedSecurityInfoW(path, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION, ctypes.byref(owner),
                                            None, None, None, ctypes.byref(descriptor))
    if error:
        return None
    try:
        return _sid_text(owner.value) if owner.value else None
    finally:
        _kernel32.LocalFree(descriptor)


def owned_path(path: str) -> bool:
    """True when this user owns the path: its owner is this user, or the owner
    this process gives what it creates (an elevated prompt gives its files to
    the Administrators group)."""
    owner = owner_of(path)
    return owner is not None and owner in {_my_sid(TOKEN_USER), _my_sid(TOKEN_OWNER)} - {None}


def make_private(path: str, directory: bool) -> None:
    """Replace the DACL on a path with one that admits this user and SYSTEM
    alone and inherits nothing; on a directory the same two entries pass to
    everything created in it, and to what is already there that inherits.
    Raises OSError when it cannot."""
    mine = _my_sid()
    if mine is None:
        raise OSError("cannot read this process's own user SID")
    inherit = "OICI" if directory else ""
    sddl = f"D:P(A;{inherit};FA;;;{mine})(A;{inherit};FA;;;SY)"
    descriptor = ctypes.c_void_p()
    if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not _advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl),
                                                   ctypes.byref(defaulted)) or not present:
            raise ctypes.WinError(ctypes.get_last_error())
        error = _advapi32.SetNamedSecurityInfoW(
            path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, dacl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        _kernel32.LocalFree(descriptor)


def command_line(pid: int) -> Optional[list[str]]:
    """A process's arguments, split as the C runtime splits them, or None
    when it is gone or cannot be opened."""
    if not _valid(pid):
        return None
    handle, _ = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if handle is None:
        return None
    try:
        size = wintypes.ULONG(0)
        status = _ntdll.NtQueryInformationProcess(handle, PROCESS_COMMAND_LINE_INFORMATION, None, 0,
                                                  ctypes.byref(size))
        if status != STATUS_INFO_LENGTH_MISMATCH or not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if _ntdll.NtQueryInformationProcess(handle, PROCESS_COMMAND_LINE_INFORMATION, buffer, size,
                                            ctypes.byref(size)):
            return None
        text = ctypes.cast(buffer, ctypes.POINTER(UNICODE_STRING)).contents
        if not text.Buffer or not text.Length:
            return None
        line = ctypes.wstring_at(text.Buffer, text.Length // 2)
    finally:
        _kernel32.CloseHandle(handle)
    count = ctypes.c_int(0)
    argv = _shell32.CommandLineToArgvW(line, ctypes.byref(count))
    if not argv:
        return None
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        _kernel32.LocalFree(argv)


def script_of(pid: int) -> Optional[str]:
    """The script a node.exe runs: its first argument that is not an
    option. None when there is none or the command line cannot be read."""
    argv = command_line(pid)
    for arg in (argv or [])[1:]:
        if not arg.startswith("-"):
            return arg
    return None


def started_at(pid: int) -> Optional[str]:
    """The creation time of a process, or None when it is gone or cannot be
    opened (`ps -p` prints nothing for either)."""
    if not _valid(pid):
        return None
    handle, _ = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if handle is None:
        return None
    try:
        created = _created(handle)
        return None if created is None else str(created)
    finally:
        _kernel32.CloseHandle(handle)


def owned(pid: int) -> bool:
    """True when the process is running and runs as this user."""
    if not _valid(pid):
        return False
    handle, _ = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE)
    if handle is None:
        return False  # gone, or not this user's to open
    try:
        if not _running(handle):
            return False
        mine = _my_sid()
        return mine is not None and _sid_of(handle) == mine
    finally:
        _kernel32.CloseHandle(handle)


def exists(pid: int) -> bool:
    """True when some process with this pid is running, whoever owns it --
    the question `kill -0` answers on POSIX, where EPERM still means alive."""
    if not _valid(pid):
        return False
    handle, error = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE)
    if handle is None:
        return error == ERROR_ACCESS_DENIED
    try:
        return _running(handle)
    finally:
        _kernel32.CloseHandle(handle)


def table() -> list[dict[str, Any]]:
    """Every process: pid, parent pid (0 when the recorded parent is gone or
    is a newer process with its number), tty (always None: Windows consoles
    have no name to bind to), image name, and for a node.exe the script it
    runs (None for every other image, and when it cannot be read)."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    entries: list[tuple[int, int, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            entries.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            more = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != ERROR_NO_MORE_FILES:
            raise ctypes.WinError(error)
    finally:
        _kernel32.CloseHandle(snapshot)
    created: dict[int, Optional[int]] = {}
    for pid, _, _ in entries:
        handle, _ = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION) if pid else (None, 0)
        if handle is None:
            created[pid] = None
            continue
        try:
            created[pid] = _created(handle)
        finally:
            _kernel32.CloseHandle(handle)
    rows = []
    for pid, ppid, name in entries:
        child, parent = created.get(pid), created.get(ppid)
        if ppid not in created or (child is not None and parent is not None and parent > child):
            ppid = 0
        script = script_of(pid) if name.lower() == NODE_IMAGE else None
        rows.append({"pid": pid, "ppid": ppid, "tty": None, "command": name, "script": script})
    return rows


class Job:
    """A Job Object that kills what is in it when its last handle closes."""

    def __init__(self) -> None:
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                                 ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            _kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        self.handle: Optional[int] = handle

    def add(self, pid: int) -> None:
        process, error = _open(pid, PROCESS_SET_QUOTA | PROCESS_TERMINATE)
        if process is None:
            raise ctypes.WinError(error)
        try:
            if not _kernel32.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _kernel32.CloseHandle(process)

    def terminate(self, code: int = 1) -> bool:
        return bool(self.handle) and bool(_kernel32.TerminateJobObject(self.handle, code))

    def close(self) -> None:
        """Let go of the job; whatever is still in it is killed."""
        handle, self.handle = self.handle, None
        if handle:
            _kernel32.CloseHandle(handle)


def resume(pid: int) -> None:
    """Resume a process started with CREATE_SUSPENDED: its one thread."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    threads = []
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        more = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                threads.append(int(entry.th32ThreadID))
            more = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    if not threads:
        raise OSError(f"process {pid} has no thread to resume")
    for tid in threads:
        thread = _kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
        if not thread:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if _kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _kernel32.CloseHandle(thread)


def kill(pid: int) -> None:
    process, _ = _open(pid, PROCESS_TERMINATE)
    if process is not None:
        try:
            _kernel32.TerminateProcess(process, 1)
        finally:
            _kernel32.CloseHandle(process)


def contain(pid: int) -> Optional[Job]:
    """Put a process started suspended in a job of its own, then resume it.
    Returns the job, or None when Windows would not assign one -- the
    process then runs uncontained and is ended by its tree instead. A
    process that cannot be resumed is killed and OSError raised: it would
    otherwise sit suspended for ever."""
    job: Optional[Job] = None
    try:
        job = Job()
        job.add(pid)
    except OSError:
        if job is not None:
            job.close()  # empty: closing it ends nothing
        job = None
    try:
        resume(pid)
    except OSError:
        if job is not None:
            job.terminate()
            job.close()
        else:
            kill(pid)
        raise
    return job

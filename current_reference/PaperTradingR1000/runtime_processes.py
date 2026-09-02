"""Runtime process bookkeeping for local R1000 launchers."""

from __future__ import annotations

import ctypes
import os
import signal
import time
from pathlib import Path
from typing import Any


STILL_ACTIVE = 259


def _windows_pid_running(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def is_pid_running(pid: int | str | None) -> bool:
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_running(value)
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # POSIX EPERM means the process exists but is owned by another user.
        # Treat it as alive so cross-user diagnostics (for example SentinelX)
        # do not report a false STOPPED state.
        return True
    except OSError:
        return False
    return True


def read_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def write_pid(path: Path, pid: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid or os.getpid()), encoding="ascii")


def clear_pid(path: Path, pid: int | None = None) -> None:
    existing = read_pid(path)
    if pid is not None and existing not in {None, int(pid)}:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def process_info(path: Path) -> dict[str, Any]:
    pid = read_pid(path)
    return {
        "pid_file": str(path),
        "pid": pid,
        "running": is_pid_running(pid),
    }


def request_termination(pid: int | None) -> bool:
    if not is_pid_running(pid):
        return True
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return False
    return True


def wait_for_exit(pid: int | None, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        if not is_pid_running(pid):
            return True
        time.sleep(0.25)
    return not is_pid_running(pid)

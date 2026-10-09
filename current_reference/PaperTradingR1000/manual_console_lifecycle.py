"""Single active PC console session with an idle terminal timeout."""
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import sys
import time


class ConsoleSession:
    def __init__(self, state_dir: Path, idle_seconds: int = 600):
        self.state_dir = Path(state_dir)
        self.marker = self.state_dir / "manual_console_session.json"
        self.lock_path = self.state_dir / "manual_console_session.lock"
        self.idle_seconds = idle_seconds
        self.pid = os.getpid()
        self.start_ticks = self._start_ticks(self.pid)
        self.waiting = False
        self._previous_term = None

    @staticmethod
    def _start_ticks(pid: int):
        try:
            return int(Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[19])
        except (OSError, ValueError, IndexError):
            return None

    def _same_process(self, marker: dict) -> bool:
        pid = marker.get("pid")
        if not isinstance(pid, int) or pid == self.pid:
            return False
        try:
            proc = Path(f"/proc/{pid}")
            command = (proc / "cmdline").read_bytes().replace(b"\\0", b" ").decode(errors="replace")
            state = (proc / "status").read_text()
            return (
                self._start_ticks(pid) == marker.get("start_ticks")
                and "State:\tZ " not in state
                and proc.stat().st_uid == os.getuid()
                and "manual_control_console.py" in command
            )
        except OSError:
            return False

    def _lock(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+")
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle

    def _read(self) -> dict:
        try:
            return json.loads(self.marker.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, state: str) -> None:
        tmp = self.marker.with_name(f"{self.marker.name}.{self.pid}.tmp")
        tmp.write_text(json.dumps({"pid": self.pid, "start_ticks": self.start_ticks, "state": state}))
        os.replace(tmp, self.marker)

    def start(self) -> None:
        # A new console may replace an older one only while it is waiting at the menu.
        with self._lock():
            previous = self._read()
            if self._same_process(previous):
                if previous.get("state") != "MENU_WAIT":
                    raise RuntimeError("Another PC console is processing an action; try again shortly.")
                os.kill(previous["pid"], signal.SIGTERM)
                old_pid = previous["pid"]
            else:
                old_pid = None
        if old_pid is not None:
            for _ in range(30):
                if not self._same_process(previous):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("The previous PC console did not exit; no new connection was opened.")
        with self._lock():
            current = self._read()
            if self._same_process(current):
                raise RuntimeError("Another PC console started at the same time; try again.")
            self._write("ACTIVE")
        self._previous_term = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self._on_term)

    def _on_term(self, _signum, _frame):
        if self.waiting:
            raise SystemExit(0)

    def read_choice(self):
        with self._lock():
            self.waiting = True
            self._write("MENU_WAIT")
        try:
            print("Select option: ", end="", flush=True)
            if not select.select([sys.stdin], [], [], self.idle_seconds)[0]:
                print("\\nPC console closed after 10 minutes without menu input.")
                return None
            return input().strip()
        finally:
            self.waiting = False
            with self._lock():
                if self._read().get("pid") == self.pid:
                    self._write("ACTIVE")

    def stop(self) -> None:
        self.waiting = False
        if self._previous_term is not None:
            signal.signal(signal.SIGTERM, self._previous_term)
        with self._lock():
            current = self._read()
            if current.get("pid") == self.pid and current.get("start_ticks") == self.start_ticks:
                self.marker.unlink(missing_ok=True)

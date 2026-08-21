from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _python_executable(project_root: Path) -> Path | None:
    current = Path(sys.executable)
    if current.exists():
        return current

    scripts_dir = project_root / ".venv" / "Scripts"
    pythonw = scripts_dir / "pythonw.exe"
    if pythonw.exists():
        return pythonw
    python = scripts_dir / "python.exe"
    if python.exists():
        return python

    linux_python = project_root / ".venv" / "bin" / "python"
    if linux_python.exists():
        return linux_python

    return None


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )


def _start_process(
    *,
    python_exe: Path,
    bot_dir: Path,
    script_name: str,
    args: list[str],
    pid_file,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, object]:
    from runtime_processes import clear_pid, process_info

    status = process_info(pid_file)
    if status["running"]:
        return {"script": script_name, "started": False, "already_running": True, **status}
    if status["pid"] is not None:
        clear_pid(pid_file, status["pid"])

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("ab", buffering=0) as stdout, stderr_path.open("ab", buffering=0) as stderr:
        process = subprocess.Popen(
            [str(python_exe), "-X", "utf8", "-B", "-u", script_name, *args],
            cwd=str(bot_dir),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            creationflags=_creation_flags(),
        )

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        confirmed = process_info(pid_file)
        if confirmed["running"]:
            return {
                "script": script_name,
                "started": True,
                "already_running": False,
                **confirmed,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            }
        returncode = process.poll()
        if returncode is not None:
            return {
                "script": script_name,
                "started": False,
                "already_running": False,
                "pid": process.pid,
                "returncode": returncode,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            }
        time.sleep(0.25)

    return {
        "script": script_name,
        "started": True,
        "already_running": False,
        "pid": process.pid,
        "pid_file": str(pid_file),
        "pid_confirmed": False,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def main() -> int:
    run_dir = Path(__file__).resolve().parent
    project_root = run_dir.parent
    bot_dir = project_root / "current_reference" / "PaperTradingR1000"
    python_exe = _python_executable(project_root)
    if python_exe is None or not bot_dir.exists():
        print("ERROR: R1000 runtime or project virtual environment was not found.", file=sys.stderr)
        return 64

    sys.path.insert(0, str(bot_dir))
    import config as cfg
    from control_utils import clear_stop_request
    import operational_controller
    from startup_validation import validate_startup

    cfg.ensure_runtime_dirs()
    validation = validate_startup(require_universe_file=True, require_gateway=False)
    if not validation.get("ok"):
        print("ERROR: startup validation failed.", file=sys.stderr)
        for issue in validation.get("issues", []):
            print(f"- {issue}", file=sys.stderr)
        return 2

    if cfg.EXECUTE_ORDERS:
        from activation_preflight import validate_automated_activation

        activation = validate_automated_activation()
        if not activation.get("ok"):
            print("ERROR: automated PAPER execution activation preflight failed.", file=sys.stderr)
            for issue in activation.get("issues", []):
                print(f"- {issue}", file=sys.stderr)
            print(f"Evidence: {cfg.STATE_DIR / 'automated_activation_preflight.json'}", file=sys.stderr)
            return 3

    clear_stop_request()
    operational_controller.authorize_current_boot()
    operational_controller.write_desired_running(True)

    results = [
        _start_process(
            python_exe=python_exe,
            bot_dir=bot_dir,
            script_name="health_supervisor.py",
            args=["--interval", str(cfg.CHECK_INTERVAL_SECONDS)],
            pid_file=cfg.SUPERVISOR_PID_FILE,
            stdout_path=cfg.LOGS_DIR / "health_supervisor.stdout.log",
            stderr_path=cfg.LOGS_DIR / "health_supervisor.stderr.log",
        ),
        _start_process(
            python_exe=python_exe,
            bot_dir=bot_dir,
            script_name="operational_controller.py",
            args=[],
            pid_file=cfg.CONTROLLER_PID_FILE,
            stdout_path=cfg.LOGS_DIR / "operational_controller.stdout.log",
            stderr_path=cfg.LOGS_DIR / "operational_controller.stderr.log",
        ),
    ]

    print(f"[{_timestamp()}] TradingbotR1000 start requested.")
    for result in results:
        status = "already running" if result.get("already_running") else "started" if result.get("started") else "failed"
        print(f"{result.get('script')}: {status} | pid={result.get('pid')} | pid_file={result.get('pid_file')}")
    return 0 if all(item.get("started") or item.get("already_running") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

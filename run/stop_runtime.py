from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    bot_dir = project_root / "current_reference" / "PaperTradingR1000"
    sys.path.insert(0, str(bot_dir))

    import config as cfg
    import operational_controller
    from control_utils import request_stop
    from heartbeat_utils import heartbeat_is_fresh
    from monitoring_core import write_bot_status
    from monitoring_io import atomic_write_json, utc_timestamp
    from runtime_health import mark_stopped
    from runtime_processes import clear_pid, process_info, wait_for_exit

    cfg.ensure_runtime_dirs()
    controller_before = process_info(cfg.CONTROLLER_PID_FILE)
    supervisor_before = process_info(cfg.SUPERVISOR_PID_FILE)
    request_stop("operator_stop")
    operational_controller.write_desired_running(False)
    operational_controller.write_controller_status("STOP_REQUESTED")

    controller_stopped = wait_for_exit(controller_before.get("pid"), timeout_seconds=20.0)
    supervisor_stopped = wait_for_exit(supervisor_before.get("pid"), timeout_seconds=20.0)
    if controller_stopped:
        clear_pid(cfg.CONTROLLER_PID_FILE, controller_before.get("pid"))
        operational_controller.write_controller_status("STOPPED", reason="operator_stop")
    if supervisor_stopped:
        clear_pid(cfg.SUPERVISOR_PID_FILE, supervisor_before.get("pid"))
        atomic_write_json(
            cfg.SUPERVISOR_STATUS_FILE,
            {
                "bot": cfg.BOT_NAME,
                "timestamp_utc": utc_timestamp(),
                "heartbeat_fresh": heartbeat_is_fresh(),
                "status": "STOPPED",
                "reason": "operator_stop",
            },
        )
    mark_stopped("operator_stop")
    write_bot_status(
        "STOPPED",
        detail="operator_stop",
        extra={
            "runtime_process": "STOPPED",
            "main_process": "operational_controller.py",
            "controller_pid": controller_before.get("pid"),
            "scheduler_pid": supervisor_before.get("pid"),
        },
    )

    print("Stop request completed.")
    print(f"Controller stopped: {'yes' if controller_stopped else 'no'}")
    print(f"Health supervisor stopped: {'yes' if supervisor_stopped else 'no'}")
    print("No positions were closed and no broker orders were cancelled.")
    return 0 if controller_stopped and supervisor_stopped else 1


if __name__ == "__main__":
    raise SystemExit(main())

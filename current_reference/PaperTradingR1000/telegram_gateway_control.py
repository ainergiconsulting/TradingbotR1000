"""Restricted remote control for the TradingbotR1000 IB Gateway service."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


SERVICE = "tradingbot-ibgateway.service"
SYSTEMCTL = "/usr/bin/systemctl"
SUDO = "/usr/bin/sudo"

AUDIT_FILE = Path(__file__).resolve().parent / "logs" / "telegram_gateway_actions.log"


class GatewayControlError(RuntimeError):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _audit(action: str, status: str, **details) -> None:
    record = {
        "timestamp_utc": _timestamp(),
        "action": action,
        "status": status,
        "details": details,
    }

    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        handle.flush()

        import os
        os.fsync(handle.fileno())


def _service_active() -> bool:
    result = subprocess.run(
        [SYSTEMCTL, "is-active", "--quiet", SERVICE],
        check=False,
    )
    return result.returncode == 0


def _api_4002_listening() -> bool:
    result = subprocess.run(
        ["/usr/bin/ss", "-ltn"],
        capture_output=True,
        text=True,
        check=False,
    )
    return ":4002" in result.stdout


def restart_gateway(*, requested_by: int) -> dict:
    try:
        _audit(
            "GATEWAY_RESTART",
            "REQUESTED",
            requested_by=requested_by,
            service=SERVICE,
        )
    except Exception as error:
        raise GatewayControlError(
            f"audit unavailable before restart: {type(error).__name__}"
        ) from error

    result = subprocess.run(
        [SUDO, "-n", SYSTEMCTL, "restart", SERVICE],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    if result.returncode != 0:
        try:
            _audit(
                "GATEWAY_RESTART",
                "FAILED",
                requested_by=requested_by,
                returncode=result.returncode,
            )
        finally:
            raise GatewayControlError("systemctl restart failed")

    deadline = time.monotonic() + 90

    while time.monotonic() < deadline:
        if _service_active() and _api_4002_listening():
            try:
                _audit(
                    "GATEWAY_RESTART",
                    "RECOVERED",
                    requested_by=requested_by,
                    api_port=4002,
                )
            except Exception:
                pass

            return {
                "ok": True,
                "service": "RUNNING",
                "api_4002": "LISTENING",
            }

        time.sleep(3)

    try:
        _audit(
            "GATEWAY_RESTART",
            "NOT_RECOVERED",
            requested_by=requested_by,
            service_active=_service_active(),
            api_4002=_api_4002_listening(),
        )
    except Exception:
        pass

    return {
        "ok": False,
        "service": "RUNNING" if _service_active() else "NOT RUNNING",
        "api_4002": "LISTENING" if _api_4002_listening() else "NOT LISTENING",
    }

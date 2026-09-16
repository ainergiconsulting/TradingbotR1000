"""Read-only IBKR Flex sync into the durable execution ledger.

Downloads Trade Confirmation via the existing Flex client, imports only new
fills, and emits Telegram FILLED notifications only for newly inserted rows.
No broker order API is used by this module.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from flex_execution_ledger import claim_execution_notification, import_flex_xml
from telegram_alerts import alert_execution_filled

BASE = Path(__file__).resolve().parent
RAW = BASE / "reports" / "flex_raw"
PYTHON = Path("/home/ibkradmin/trading/venv/bin/python")
CLIENT = BASE / "ibkr_flex_client.py"


def newest_trade_confirmation() -> Path | None:
    files = list(RAW.glob("ibkr_flex_trade_confirmation_*.xml"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def sync() -> dict:
    before = newest_trade_confirmation()
    proc = subprocess.run(
        [str(PYTHON), str(CLIENT), "--report-type", "trade_confirmation"],
        cwd=BASE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Flex Trade Confirmation download failed (exit {proc.returncode})")
    after = newest_trade_confirmation()
    if after is None or (before is not None and after == before):
        raise RuntimeError("Flex client returned success but no new Trade Confirmation XML was found")
    result = import_flex_xml(after)
    notified = 0
    for fill in result.get("inserted_rows", []):
        exec_id = str(fill.get("ib_exec_id") or "").strip()
        if not claim_execution_notification(
            exec_id,
            source="FLEX",
            symbol=str(fill.get("symbol") or ""),
            side=str(fill.get("side") or ""),
            quantity=float(fill.get("quantity") or 0),
            price=float(fill.get("price") or 0),
        ):
            continue
        alert_execution_filled(fill)
        notified += 1
    return {
        "source_file": after.name,
        "parsed": result["parsed"],
        "inserted": result["inserted"],
        "duplicates": result["duplicates"],
        "total": result["total"],
        "telegram_fill_notifications": notified,
    }


if __name__ == "__main__":
    print(sync())

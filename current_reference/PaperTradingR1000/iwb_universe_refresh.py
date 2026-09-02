"""Weekly IWB holdings refresh from the official iShares CSV.

This update is deliberately non-blocking for trading: failures are recorded so
Telegram can alert the operator, while the last validated universe file remains
in place. A successful refresh replaces the universe atomically after basic
sanity checks.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config as cfg
from monitoring_io import atomic_write_json, utc_timestamp
from symbol_mapping import canonical_symbol

SOURCE_URL = "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/latest-holdings.csv"
UNIVERSE_FILE = cfg.PROJECT_ROOT / "IWB_holdings.csv"
STATUS_FILE = cfg.STATE_DIR / "iwb_universe_refresh.json"
BACKUP_DIR = cfg.PROJECT_ROOT / "universe_backups"
MIN_EQUITY_COUNT = 950
MAX_EQUITY_COUNT = 1100


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise RuntimeError("universe_decode_failed")


def _validate(text: str) -> dict[str, Any]:
    rows = list(csv.reader(io.StringIO(text)))
    header_index = None
    for idx, row in enumerate(rows):
        normalized = [cell.strip() for cell in row]
        if "Ticker" in normalized and "Asset Class" in normalized:
            header_index = idx
            break
    if header_index is None:
        raise RuntimeError("iwb_header_not_found")
    reader = csv.DictReader(io.StringIO("\n".join(",".join('"'+c.replace('"','""')+'"' for c in row) for row in rows[header_index:])))
    symbols: set[str] = set()
    equity_rows = 0
    for row in reader:
        if str(row.get("Asset Class") or "").strip().lower() != "equity":
            continue
        if str(row.get("Currency") or "").strip().upper() not in {"", "USD"}:
            continue
        symbol = canonical_symbol(row.get("Ticker"))
        if symbol:
            equity_rows += 1
            symbols.add(symbol)
    if not (MIN_EQUITY_COUNT <= len(symbols) <= MAX_EQUITY_COUNT):
        raise RuntimeError(f"unexpected_equity_count:{len(symbols)}")
    as_of = ""
    for row in rows[:8]:
        joined = ",".join(row)
        if "Fund Holdings as of" in joined:
            as_of = joined.split("Fund Holdings as of", 1)[1].strip(" ,\"")
            break
    return {"equity_rows": equity_rows, "unique_equity_symbols": len(symbols), "as_of": as_of}


def refresh() -> dict[str, Any]:
    cfg.ensure_runtime_dirs()
    started = utc_timestamp()
    try:
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0 TradingbotR1000"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
        text = _decode(payload)
        validation = _validate(text)

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = ""
        if UNIVERSE_FILE.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = BACKUP_DIR / f"IWB_holdings.{stamp}.csv"
            shutil.copy2(UNIVERSE_FILE, backup)
            backup_path = str(backup)

        fd, temp_name = tempfile.mkstemp(prefix="IWB_holdings.", suffix=".tmp", dir=str(UNIVERSE_FILE.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.replace(temp_name, UNIVERSE_FILE)
            os.chmod(UNIVERSE_FILE, 0o644)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

        result = {
            "bot": cfg.BOT_NAME,
            "source": "iShares IWB official holdings CSV",
            "url": SOURCE_URL,
            "status": "OK",
            "started_at_utc": started,
            "completed_at_utc": utc_timestamp(),
            "as_of": validation.get("as_of", ""),
            "equity_rows": validation["equity_rows"],
            "unique_equity_symbols": validation["unique_equity_symbols"],
            "backup_path": backup_path,
        }
    except Exception as exc:
        result = {
            "bot": cfg.BOT_NAME,
            "source": "iShares IWB official holdings CSV",
            "url": SOURCE_URL,
            "status": "FAILED",
            "started_at_utc": started,
            "completed_at_utc": utc_timestamp(),
            "error": f"{type(exc).__name__}:{exc}",
        }
    atomic_write_json(STATUS_FILE, result)
    return result


def main() -> int:
    result = refresh()
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from ib_insync import IB, Stock

from current_reference.PaperTradingR1000.config_loader import load_universe_config
from current_reference.PaperTradingR1000.symbol_mapping import ibkr_symbol
from current_reference.PaperTradingR1000.trading_engine import (
    _resolve_project_path,
    load_universe_symbols,
)

ROOT = Path("data/daily_bars")
REPORT_FILE = Path("ibkr_r1000_results/ibkr_daily_update_report.json")
CLIENT_ID = 93
PAUSE_SECONDS = 1.0
MAX_RETRIES = 3


def read_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_rows(path: Path, fieldnames, rows):
    rows = sorted(rows, key=lambda r: r["date"])
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
    tmp_path.replace(path)


def normalize_date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")


def main():
    universe_cfg = load_universe_config()
    symbols = load_universe_symbols(
        _resolve_project_path(universe_cfg["source_path"]),
        universe_cfg["symbol_column"],
    )

    ib = IB()
    ib.connect("127.0.0.1", 4002, clientId=CLIENT_ID)

    report = {
        "symbols_total": len(symbols),
        "updated": [],
        "unchanged": [],
        "failed": [],
    }

    try:
        for index, symbol in enumerate(symbols, start=1):
            path = ROOT / f"{symbol}.csv"

            try:
                fieldnames, rows = read_rows(path)
                if not rows:
                    raise RuntimeError("empty_csv")

                last_date = rows[-1]["date"]
                existing = {row["date"]: row for row in rows}

                contract = Stock(ibkr_symbol(symbol), "SMART", "USD")
                qualified = ib.qualifyContracts(contract)

                if not qualified:
                    raise RuntimeError("contract_not_qualified")

                contract = qualified[0]

                bars = None
                last_error = None

                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        bars = ib.reqHistoricalData(
                            contract,
                            endDateTime="",
                            durationStr="1 M",
                            barSizeSetting="1 day",
                            whatToShow="TRADES",
                            useRTH=True,
                            formatDate=1,
                        )
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt < MAX_RETRIES:
                            ib.sleep(2 ** attempt)

                if bars is None:
                    raise last_error or RuntimeError("historical_request_failed")

                added = 0
                today_et = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")

                for bar in bars:
                    date = normalize_date(bar.date)

                    # Never persist the current US trading day's daily bar.
                    # It may still be incomplete while the market is open.
                    if date >= today_et:
                        continue
                    if date <= last_date:
                        continue

                    existing[date] = {
                        "ticker": rows[-1]["ticker"],
                        "name": rows[-1]["name"],
                        "con_id": contract.conId,
                        "local_symbol": contract.localSymbol,
                        "date": date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "bar_count": bar.barCount,
                        "average": bar.average,
                    }
                    added += 1

                if added:
                    write_rows(path, fieldnames, list(existing.values()))
                    report["updated"].append({
                        "symbol": symbol,
                        "previous_last": last_date,
                        "new_last": max(existing),
                        "added": added,
                    })
                    status = f"updated +{added}"
                else:
                    report["unchanged"].append({
                        "symbol": symbol,
                        "last_date": last_date,
                    })
                    status = "unchanged"

                print(f"[{index}/{len(symbols)}] {symbol}: {status}")

            except Exception as exc:
                report["failed"].append({
                    "symbol": symbol,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                print(f"[{index}/{len(symbols)}] {symbol}: FAILED {type(exc).__name__}: {exc}")

            ib.sleep(PAUSE_SECONDS)

    finally:
        ib.disconnect()

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print("DONE")
    print("updated:", len(report["updated"]))
    print("unchanged:", len(report["unchanged"]))
    print("failed:", len(report["failed"]))
    print("report:", REPORT_FILE)


if __name__ == "__main__":
    main()

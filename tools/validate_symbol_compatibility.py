"""Validate TradingbotR1000 symbol compatibility across IWB, Massive, and IBKR.

This tool does not download historical data and does not submit orders. It
qualifies IBKR stock contracts read-only and caches successful validations so a
later run can resume without repeating completed checks.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = PROJECT_ROOT / "current_reference" / "PaperTradingR1000"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

import config as cfg  # noqa: E402
from ibkr_utils import connect, stock_contract  # noqa: E402
from massive_historical_downloader import load_iwb_universe  # noqa: E402
from symbol_mapping import (  # noqa: E402
    canonical_symbol_from_ibkr,
    expected_ibkr_primary_exchange,
    ibkr_symbol,
    identity_for,
)


RESULTS_DIR = PROJECT_ROOT / "ibkr_r1000_results"
VALIDATION_CSV = RESULTS_DIR / "symbol_compatibility_validation.csv"
VALIDATION_REPORT = RESULTS_DIR / "symbol_compatibility_validation_report.json"
VALIDATOR_VERSION = "1"

FIELDS = [
    "validator_version",
    "validated_at_utc",
    "source_symbol",
    "canonical_symbol",
    "historical_file",
    "historical_file_exists",
    "source_exchange",
    "expected_ibkr_primary_exchange",
    "ibkr_request_symbol",
    "ibkr_symbol",
    "ibkr_local_symbol",
    "ibkr_trading_class",
    "ibkr_sec_type",
    "ibkr_exchange",
    "ibkr_primary_exchange",
    "ibkr_currency",
    "ibkr_con_id",
    "status",
    "reason",
    "attempts",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def print_progress(message: str, **fields: Any) -> None:
    print(json.dumps({"timestamp_utc": utc_now(), "message": message, **fields}, sort_keys=True), flush=True)


def cache_by_symbol(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    usable = {}
    for row in rows:
        if row.get("validator_version") != VALIDATOR_VERSION:
            continue
        symbol = row.get("canonical_symbol", "")
        if symbol and row.get("status") == "ok":
            usable[symbol] = row
    return usable


def detail_from_contract(contract: Any) -> dict[str, str]:
    raw_symbol = str(getattr(contract, "symbol", "") or "")
    return {
        "ibkr_symbol": raw_symbol,
        "ibkr_local_symbol": str(getattr(contract, "localSymbol", "") or ""),
        "ibkr_trading_class": str(getattr(contract, "tradingClass", "") or ""),
        "ibkr_sec_type": str(getattr(contract, "secType", "") or ""),
        "ibkr_exchange": str(getattr(contract, "exchange", "") or ""),
        "ibkr_primary_exchange": str(getattr(contract, "primaryExchange", "") or ""),
        "ibkr_currency": str(getattr(contract, "currency", "") or ""),
        "ibkr_con_id": str(getattr(contract, "conId", "") or ""),
        "canonical_from_ibkr": canonical_symbol_from_ibkr(raw_symbol),
    }


def candidate_contracts(source_symbol: str, canonical_symbol: str, currency: str, source_exchange: str) -> list[Any]:
    expected_primary = expected_ibkr_primary_exchange(source_exchange)
    candidates: list[tuple[str, str]] = []
    for request_symbol in [
        ibkr_symbol(canonical_symbol),
        canonical_symbol,
        str(source_symbol).strip().upper(),
        canonical_symbol.replace(".", "/"),
        canonical_symbol.replace(".", ""),
    ]:
        if not request_symbol:
            continue
        for primary in [expected_primary, ""]:
            item = (request_symbol, primary)
            if item not in candidates:
                candidates.append(item)

    contracts = []
    for request_symbol, primary in candidates:
        contracts.append(stock_contract(request_symbol, currency=currency or "USD", primary_exchange=primary or None))
    return contracts


def validate_entry(ib: Any, entry: Any, daily_bars_dir: Path, pause_seconds: float) -> dict[str, Any]:
    identity = identity_for(entry.source_symbol, source_exchange=entry.exchange, daily_bars_dir=daily_bars_dir)
    base = {
        "validator_version": VALIDATOR_VERSION,
        "validated_at_utc": utc_now(),
        "source_symbol": entry.source_symbol,
        "canonical_symbol": entry.symbol,
        "historical_file": str(daily_bars_dir / f"{entry.symbol}.csv"),
        "historical_file_exists": str((daily_bars_dir / f"{entry.symbol}.csv").exists()).lower(),
        "source_exchange": entry.exchange,
        "expected_ibkr_primary_exchange": identity.expected_ibkr_primary_exchange,
        "ibkr_request_symbol": identity.ibkr_symbol,
    }

    if identity.exclusion_reason:
        return {**base, "status": "excluded", "reason": identity.exclusion_reason, "attempts": 0}

    attempts = 0
    errors = []
    for contract in candidate_contracts(entry.source_symbol, entry.symbol, entry.currency, entry.exchange):
        attempts += 1
        request_symbol = str(getattr(contract, "symbol", "") or "")
        primary = str(getattr(contract, "primaryExchange", "") or "")
        try:
            qualified = ib.qualifyContracts(contract)
        except Exception as exc:
            errors.append(f"{request_symbol}/{primary}: {exc!r}")
            qualified = []
        if pause_seconds > 0:
            time.sleep(pause_seconds)
        if not qualified:
            continue
        chosen = qualified[0]
        details = detail_from_contract(chosen)
        canonical_from_ibkr = details.pop("canonical_from_ibkr")
        if details["ibkr_sec_type"] != "STK":
            errors.append(f"{request_symbol}/{primary}: secType={details['ibkr_sec_type']}")
            continue
        if details["ibkr_currency"] != (entry.currency or "USD"):
            errors.append(f"{request_symbol}/{primary}: currency={details['ibkr_currency']}")
            continue
        if canonical_from_ibkr != entry.symbol:
            errors.append(f"{request_symbol}/{primary}: canonical_from_ibkr={canonical_from_ibkr}")
            continue
        return {
            **base,
            **details,
            "ibkr_request_symbol": request_symbol,
            "status": "ok",
            "reason": "",
            "attempts": attempts,
        }

    return {
        **base,
        "status": "unresolved",
        "reason": "; ".join(errors[-3:]) or "no IBKR stock contract qualified",
        "attempts": attempts,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    mapping_changes = []
    unresolved = []
    excluded = []
    missing_files = []
    for row in rows:
        status = str(row.get("status", ""))
        status_counts[status] = status_counts.get(status, 0) + 1
        source = str(row.get("source_symbol", ""))
        canonical = str(row.get("canonical_symbol", ""))
        ibkr_request = str(row.get("ibkr_request_symbol", ""))
        if source and (source != canonical or ibkr_request != canonical):
            mapping_changes.append(
                {
                    "source_symbol": source,
                    "canonical_symbol": canonical,
                    "ibkr_request_symbol": ibkr_request,
                }
            )
        if status == "unresolved":
            unresolved.append({"symbol": canonical, "source_symbol": source, "reason": row.get("reason", "")})
        if status == "excluded":
            excluded.append({"symbol": canonical, "source_symbol": source, "reason": row.get("reason", "")})
        if str(row.get("historical_file_exists", "")).lower() != "true":
            missing_files.append(canonical)
    return {
        "created_at_utc": utc_now(),
        "validator_version": VALIDATOR_VERSION,
        "total_symbols": len(rows),
        "status_counts": status_counts,
        "mapping_changes": mapping_changes,
        "unresolved_symbols": unresolved,
        "excluded_symbols": excluded,
        "missing_historical_files": sorted(set(missing_files)),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate R1000 Massive/Polygon-to-IBKR ticker compatibility")
    parser.add_argument("--universe-file", type=Path, default=PROJECT_ROOT / "IWB_holdings.csv")
    parser.add_argument("--daily-bars-dir", type=Path, default=PROJECT_ROOT / "data" / "daily_bars")
    parser.add_argument("--output-csv", type=Path, default=VALIDATION_CSV)
    parser.add_argument("--report-json", type=Path, default=VALIDATION_REPORT)
    parser.add_argument("--symbols", help="comma-separated canonical or source symbols to validate")
    parser.add_argument("--max-symbols", type=int, help="limit number of symbols checked")
    parser.add_argument("--max-targets", type=int, help="limit uncached symbols validated in this run")
    parser.add_argument("--force", action="store_true", help="revalidate symbols that already have ok cached rows")
    parser.add_argument("--pause-seconds", type=float, default=0.02)
    parser.add_argument("--client-id", type=int, default=1010)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    all_entries = load_iwb_universe(args.universe_file)
    entries = list(all_entries)
    if args.symbols:
        requested = {identity_for(symbol).canonical_symbol for symbol in args.symbols.split(",") if symbol.strip()}
        entries = [entry for entry in entries if entry.symbol in requested]
    if args.max_symbols is not None:
        entries = entries[: args.max_symbols]

    cached_rows = read_csv_rows(args.output_csv)
    cached_ok = cache_by_symbol(cached_rows)
    output_by_symbol = {row.get("canonical_symbol", ""): row for row in cached_rows if row.get("canonical_symbol")}
    targets = [entry for entry in entries if args.force or entry.symbol not in cached_ok]
    if args.max_targets is not None:
        targets = targets[: args.max_targets]

    print_progress("validation_start", universe_symbols=len(entries), targets=len(targets), cached_ok=len(cached_ok))
    if targets:
        ib = connect(client_id=args.client_id, readonly=True)
        try:
            for index, entry in enumerate(targets, start=1):
                print_progress("symbol_validation_start", index=index, total=len(targets), symbol=entry.symbol, source_symbol=entry.source_symbol)
                row = validate_entry(ib, entry, args.daily_bars_dir, args.pause_seconds)
                output_by_symbol[entry.symbol] = row
                ordered_rows = [output_by_symbol[entry.symbol] for entry in all_entries if entry.symbol in output_by_symbol]
                write_csv_atomic(args.output_csv, ordered_rows)
                write_json_atomic(args.report_json, summarize(ordered_rows))
                print_progress(
                    "symbol_validation_complete",
                    symbol=entry.symbol,
                    status=row.get("status", ""),
                    reason=row.get("reason", ""),
                    attempts=row.get("attempts", 0),
                )
        finally:
            ib.disconnect()

    ordered_rows = [output_by_symbol[entry.symbol] for entry in all_entries if entry.symbol in output_by_symbol]
    report = summarize(ordered_rows)
    write_csv_atomic(args.output_csv, ordered_rows)
    write_json_atomic(args.report_json, report)
    print_progress("validation_complete", **report["status_counts"], total_symbols=report["total_symbols"])
    return 0 if not report["unresolved_symbols"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

"""Repair short daily-bar histories for the active TradingbotR1000 universe.

This tool targets only symbols whose existing per-symbol CSV has fewer than the
minimum completed daily closes required by the strategy engine. It never
rewrites the large consolidated historical dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from current_reference.PaperTradingR1000.massive_historical_downloader import (  # noqa: E402
    DEFAULT_DAILY_BARS_DIR,
    DEFAULT_SCHEMA_FILE,
    DEFAULT_UNIVERSE_FILE,
    DownloadError,
    MassiveClient,
    UniverseEntry,
    aggregate_to_schema_row,
    default_start_date,
    load_iwb_universe,
    load_schema,
    merge_rows,
    normalize_symbol,
    read_schema_rows,
    validate_rows_against_schema,
    write_csv_atomic,
)


RESULTS_DIR = PROJECT_ROOT / "ibkr_r1000_results"
CHECKPOINT_FILE = RESULTS_DIR / "short_history_repair_checkpoint.json"
REPORT_FILE = RESULTS_DIR / "short_history_repair_report.json"
FAILED_FILE = RESULTS_DIR / "short_history_repair_failed_symbols.csv"
LOG_FILE = RESULTS_DIR / "short_history_repair.log"
BACKUP_DIR = DEFAULT_DAILY_BARS_DIR / "repair_backups"
REQUIRED_FIELDS = ("ticker", "name", "local_symbol", "date", "open", "high", "low", "close", "volume")


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def print_progress(message: str, **fields: Any) -> None:
    payload = {"timestamp_utc": utc_now_text(), "message": message, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


def append_log(message: str, **fields: Any) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp_utc": utc_now_text(), "message": message, **fields}
    with LOG_FILE.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def parse_yyyymmdd(value: str) -> date | None:
    text = value.strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def valid_completed_rows(path: Path, schema: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        rows = read_schema_rows(path, schema)
    except DownloadError:
        return []
    valid_rows = []
    seen: set[str] = set()
    for row in rows:
        date_text = str(row.get("date", "")).strip()
        if date_text in seen:
            continue
        parsed = parse_yyyymmdd(date_text)
        if parsed is None:
            continue
        if any(str(row.get(field, "")).strip() == "" for field in REQUIRED_FIELDS):
            continue
        valid_rows.append(row)
        seen.add(date_text)
    return sorted(valid_rows, key=lambda item: str(item.get("date", "")))


def identify_short_symbols(entries: list[UniverseEntry], schema: list[str], daily_bars_dir: Path, min_rows: int) -> list[dict[str, Any]]:
    short: list[dict[str, Any]] = []
    for entry in entries:
        rows = valid_completed_rows(daily_bars_dir / f"{entry.symbol}.csv", schema)
        if len(rows) < min_rows:
            short.append(
                {
                    "symbol": entry.symbol,
                    "rows": len(rows),
                    "path": str(daily_bars_dir / f"{entry.symbol}.csv"),
                    "first_date": str(rows[0].get("date", "")) if rows else "",
                    "last_date": str(rows[-1].get("date", "")) if rows else "",
                }
            )
    return short


def load_checkpoint() -> dict[str, Any]:
    checkpoint = read_json(CHECKPOINT_FILE)
    checkpoint.setdefault("completed_symbols", [])
    checkpoint.setdefault("failed_symbols", {})
    return checkpoint


def save_checkpoint(*, completed_symbols: set[str], failed_symbols: dict[str, str], target_symbols: list[str], min_rows: int) -> None:
    write_json_atomic(
        CHECKPOINT_FILE,
        {
            "updated_at_utc": utc_now_text(),
            "min_completed_rows": min_rows,
            "target_symbols": target_symbols,
            "completed_symbols": sorted(completed_symbols),
            "failed_symbols": dict(sorted(failed_symbols.items())),
        },
    )


def backup_symbol_file(path: Path) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{path.stem}.{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def calculate_request_windows(end_date: date, calendar_lookback_days: int, fallback_years: int) -> list[tuple[str, date, date]]:
    primary_start = max(end_date - timedelta(days=calendar_lookback_days), date(1970, 1, 1))
    fallback_start = default_start_date(end_date.replace(year=end_date.year)) if fallback_years == 10 else max(
        end_date - timedelta(days=365 * fallback_years + 7),
        date(1970, 1, 1),
    )
    windows = [("readiness_window", primary_start, end_date)]
    if fallback_start < primary_start:
        windows.append(("fallback_window", fallback_start, end_date))
    return windows


def write_failed_report(failed_symbols: dict[str, str]) -> None:
    rows = [{"symbol": symbol, "error": error} for symbol, error in sorted(failed_symbols.items())]
    write_csv_atomic(FAILED_FILE, ["symbol", "error"], rows)


def write_report(payload: dict[str, Any]) -> None:
    write_json_atomic(REPORT_FILE, payload)


def make_client(args: argparse.Namespace) -> MassiveClient:
    api_key = os.environ.get("MASSIVE_API_KEY", "")
    if not api_key.strip():
        raise DownloadError(
            "MASSIVE_API_KEY is not available in this Python process; "
            f"pid={os.getpid()} cwd={Path.cwd()}"
        )
    return MassiveClient(
        api_key,
        base_url=args.api_base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        backoff_seconds=args.backoff_seconds,
        rate_limit_pause_seconds=args.rate_limit_pause_seconds,
    )


def request_massive_json(args: argparse.Namespace, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
        raise DownloadError("MASSIVE_API_KEY is not available in this Python process")
    query = dict(params or {})
    query["apiKey"] = api_key
    url = args.api_base_url.rstrip("/") + path + "?" + urllib.parse.urlencode(query)
    for attempt in range(1, args.max_retries + 2):
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "TradingbotR1000/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if args.rate_limit_pause_seconds > 0:
                time.sleep(args.rate_limit_pause_seconds)
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt > args.max_retries:
                raise DownloadError(f"Massive reference request failed: HTTP {exc.code}") from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else args.backoff_seconds * (2 ** (attempt - 1))
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt > args.max_retries:
                raise DownloadError(f"Massive reference request failed: {exc.__class__.__name__}") from exc
            time.sleep(args.backoff_seconds * (2 ** (attempt - 1)))
    raise DownloadError("Massive reference request failed")


def confirmed_ticker_lineage(symbol: str, args: argparse.Namespace) -> list[str]:
    path = f"/vX/reference/tickers/{urllib.parse.quote(symbol, safe='')}/events"
    try:
        payload = request_massive_json(args, path)
    except DownloadError as exc:
        append_log("ticker_events_failed", symbol=symbol, error=str(exc))
        return [symbol]
    events = ((payload.get("results") or {}).get("events") or []) if isinstance(payload, dict) else []
    ticker_changes = [
        str((event.get("ticker_change") or {}).get("ticker") or "").strip().upper()
        for event in events
        if event.get("type") == "ticker_change"
    ]
    lineage: list[str] = []
    for ticker in [symbol, *reversed(ticker_changes)]:
        normalized = normalize_symbol(ticker)
        if normalized and normalized not in lineage:
            lineage.append(normalized)
    if symbol not in lineage:
        lineage.insert(0, symbol)
    return lineage


def rows_as_current_symbol(rows: list[dict[str, str]], entry: UniverseEntry) -> list[dict[str, str]]:
    normalized_rows = []
    for row in rows:
        item = dict(row)
        item["ticker"] = entry.symbol
        item["local_symbol"] = entry.symbol
        item["name"] = entry.name
        normalized_rows.append(item)
    return normalized_rows


def repair_symbol(
    client: MassiveClient,
    entry: UniverseEntry,
    schema: list[str],
    args: argparse.Namespace,
) -> tuple[bool, str, int, int, Path | None]:
    symbol_path = args.daily_bars_dir / f"{entry.symbol}.csv"
    existing_rows = valid_completed_rows(symbol_path, schema)
    if len(existing_rows) >= args.min_rows:
        return True, "already_ready", len(existing_rows), len(existing_rows), None

    windows = calculate_request_windows(args.end_date, args.calendar_lookback_days, args.fallback_years)
    lineage = confirmed_ticker_lineage(entry.symbol, args)
    print_progress("symbol_lineage_resolved", symbol=entry.symbol, lineage=lineage)
    append_log("symbol_lineage_resolved", symbol=entry.symbol, lineage=lineage)
    best_rows = existing_rows
    total_attempts = 0
    for request_symbol in lineage:
        request_entry = UniverseEntry(
            source_symbol=request_symbol,
            symbol=request_symbol,
            name=entry.name,
            exchange=entry.exchange,
            currency=entry.currency,
            sector=entry.sector,
        )
        for label, start_date, end_date in windows:
            print_progress(
                "symbol_download_start",
                symbol=entry.symbol,
                request_symbol=request_symbol,
                window=label,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
            append_log(
                "symbol_download_start",
                symbol=entry.symbol,
                request_symbol=request_symbol,
                window=label,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
            try:
                aggregates, attempts = client.get_daily_aggregates(request_symbol, start_date, end_date, adjusted=args.adjusted)
                total_attempts += attempts
                incoming = rows_as_current_symbol(
                    merge_rows([], [aggregate_to_schema_row(item, request_entry) for item in aggregates]),
                    entry,
                )
                merged = merge_rows(best_rows, incoming)
                if len(merged) > len(best_rows):
                    best_rows = merged
                print_progress(
                    "symbol_download_complete",
                    symbol=entry.symbol,
                    request_symbol=request_symbol,
                    window=label,
                    incoming_rows=len(incoming),
                    merged_rows=len(merged),
                    attempts=attempts,
                )
                if len(best_rows) >= args.min_rows:
                    break
            except DownloadError as exc:
                error = str(exc)
                print_progress("symbol_download_failed", symbol=entry.symbol, request_symbol=request_symbol, window=label, error=error)
                append_log("symbol_download_failed", symbol=entry.symbol, request_symbol=request_symbol, window=label, error=error)
        if len(best_rows) >= args.min_rows:
            break

    if len(best_rows) < args.min_rows:
        return False, f"insufficient rows after repair: {len(best_rows)}", len(existing_rows), len(best_rows), None

    backup_path = backup_symbol_file(symbol_path)
    print_progress("symbol_file_write_start", symbol=entry.symbol, rows=len(best_rows), path=str(symbol_path), backup=str(backup_path or ""))
    write_csv_atomic(symbol_path, schema, best_rows)
    print_progress("symbol_file_write_complete", symbol=entry.symbol, rows=len(best_rows), path=str(symbol_path), attempts=total_attempts)
    append_log("symbol_repaired", symbol=entry.symbol, rows_before=len(existing_rows), rows_after=len(best_rows), backup=str(backup_path or ""))
    return True, "repaired", len(existing_rows), len(best_rows), backup_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair only short-history TradingbotR1000 daily bar files from Massive")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--identify-only", action="store_true", help="list short-history symbols without API calls")
    mode.add_argument("--download", action="store_true", help="download only short-history symbols")
    parser.add_argument("--symbols", help="comma-separated target symbols; defaults to all currently short-history symbols")
    parser.add_argument("--min-rows", type=int, default=200)
    parser.add_argument("--end-date", type=parse_iso_date, default=date.today())
    parser.add_argument("--calendar-lookback-days", type=int, default=500)
    parser.add_argument("--fallback-years", type=int, default=10)
    parser.add_argument("--adjusted", action="store_true")
    parser.add_argument("--api-base-url", default="https://api.massive.com")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--schema-file", type=Path, default=DEFAULT_SCHEMA_FILE)
    parser.add_argument("--daily-bars-dir", type=Path, default=DEFAULT_DAILY_BARS_DIR)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--backoff-seconds", type=float, default=2.0)
    parser.add_argument("--rate-limit-pause-seconds", type=float, default=1.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.min_rows < 1:
        parser.error("--min-rows must be at least 1")
    if args.calendar_lookback_days < 1:
        parser.error("--calendar-lookback-days must be at least 1")
    if args.fallback_years < 1:
        parser.error("--fallback-years must be at least 1")

    schema = load_schema(args.schema_file)
    entries = load_iwb_universe(args.universe_file)
    entries_by_symbol = {entry.symbol: entry for entry in entries}
    if args.symbols:
        requested = [normalize_symbol(symbol) for symbol in args.symbols.split(",") if symbol.strip()]
        requested_set = set(requested)
        scan_entries = [entry for entry in entries if entry.symbol in requested_set]
        unknown_symbols = sorted(requested_set - set(entries_by_symbol))
    else:
        scan_entries = entries
        unknown_symbols = []

    short = identify_short_symbols(scan_entries, schema, args.daily_bars_dir, args.min_rows)
    short_symbols = [item["symbol"] for item in short]
    if args.symbols:
        targets = short_symbols
    else:
        targets = short_symbols

    print_progress("short_history_identified", count=len(short), symbols=short_symbols, unknown_symbols=unknown_symbols)
    write_report(
        {
            "created_at_utc": utc_now_text(),
            "mode": "identify" if args.identify_only or not args.download else "download",
            "min_completed_rows": args.min_rows,
            "short_history_symbols": short,
            "target_symbols": targets,
            "unknown_symbols": unknown_symbols,
        }
    )
    if args.identify_only or not args.download:
        return 0
    if not targets:
        checkpoint = load_checkpoint()
        completed_symbols = {
            normalize_symbol(symbol)
            for symbol in (checkpoint.get("completed_symbols") or [])
            if normalize_symbol(symbol) in set(requested if args.symbols else [])
        }
        save_checkpoint(
            completed_symbols=completed_symbols,
            failed_symbols={},
            target_symbols=[],
            min_rows=args.min_rows,
        )
        write_failed_report({})
        print_progress("repair_run_complete", targets=0, remaining=0)
        append_log("repair_run_complete", targets=0, remaining=0)
        write_report(
            {
                "created_at_utc": utc_now_text(),
                "mode": "download",
                "min_completed_rows": args.min_rows,
                "target_symbols": [],
                "completed_symbols": sorted(completed_symbols),
                "failed_symbols": {},
                "remaining_short_target_symbols": [],
                "results": [],
                "unknown_symbols": unknown_symbols,
            }
        )
        return 0

    try:
        client = make_client(args)
    except DownloadError as exc:
        error = str(exc)
        print_progress("repair_run_failed_before_download", error=error)
        append_log("repair_run_failed_before_download", error=error)
        write_report(
            {
                "created_at_utc": utc_now_text(),
                "mode": "download",
                "min_completed_rows": args.min_rows,
                "target_symbols": targets,
                "completed_symbols": [],
                "failed_symbols": {symbol: error for symbol in targets},
                "remaining_short_target_symbols": short,
                "results": [],
            }
        )
        return 2

    checkpoint = load_checkpoint()
    target_set = set(targets)
    completed_symbols = {
        normalize_symbol(symbol)
        for symbol in (checkpoint.get("completed_symbols") or [])
        if normalize_symbol(symbol) in target_set
    }
    failed_symbols = {
        normalize_symbol(symbol): str(error)
        for symbol, error in (checkpoint.get("failed_symbols") or {}).items()
        if normalize_symbol(symbol) in target_set
    }
    results: list[dict[str, Any]] = []

    save_checkpoint(
        completed_symbols=completed_symbols,
        failed_symbols=failed_symbols,
        target_symbols=targets,
        min_rows=args.min_rows,
    )
    write_failed_report(failed_symbols)

    print_progress("repair_run_start", targets=len(targets), min_rows=args.min_rows)
    append_log("repair_run_start", targets=len(targets), min_rows=args.min_rows)
    for index, symbol in enumerate(targets, start=1):
        entry = entries_by_symbol[symbol]
        current_rows = valid_completed_rows(args.daily_bars_dir / f"{symbol}.csv", schema)
        if symbol in completed_symbols and len(current_rows) >= args.min_rows:
            print_progress("symbol_skipped_checkpoint_complete", symbol=symbol, index=index, total=len(targets), rows=len(current_rows))
            continue
        print_progress("symbol_repair_begin", symbol=symbol, index=index, total=len(targets), existing_rows=len(current_rows))
        ok, status, before_rows, after_rows, backup_path = repair_symbol(client, entry, schema, args)
        result = {
            "symbol": symbol,
            "ok": ok,
            "status": status,
            "rows_before": before_rows,
            "rows_after": after_rows,
            "backup_file": str(backup_path or ""),
        }
        results.append(result)
        if ok:
            completed_symbols.add(symbol)
            failed_symbols.pop(symbol, None)
        else:
            failed_symbols[symbol] = status
        save_checkpoint(
            completed_symbols=completed_symbols,
            failed_symbols=failed_symbols,
            target_symbols=targets,
            min_rows=args.min_rows,
        )
        write_failed_report(failed_symbols)
        write_report(
            {
                "created_at_utc": utc_now_text(),
                "mode": "download",
                "min_completed_rows": args.min_rows,
                "target_symbols": targets,
                "completed_symbols": sorted(completed_symbols),
                "failed_symbols": dict(sorted(failed_symbols.items())),
                "results": results,
            }
        )
        print_progress("symbol_repair_finished", symbol=symbol, ok=ok, status=status, rows_before=before_rows, rows_after=after_rows)
        time.sleep(0.1)

    remaining = identify_short_symbols(entries, schema, args.daily_bars_dir, args.min_rows)
    remaining_targets = [item for item in remaining if item["symbol"] in set(targets)]
    print_progress("repair_run_complete", targets=len(targets), remaining=len(remaining_targets))
    append_log("repair_run_complete", targets=len(targets), remaining=len(remaining_targets))
    write_report(
        {
            "created_at_utc": utc_now_text(),
            "mode": "download",
            "min_completed_rows": args.min_rows,
            "target_symbols": targets,
            "completed_symbols": sorted(completed_symbols),
            "failed_symbols": dict(sorted(failed_symbols.items())),
            "remaining_short_target_symbols": remaining_targets,
            "results": results,
        }
    )
    return 0 if not remaining_targets and not failed_symbols else 4


if __name__ == "__main__":
    raise SystemExit(main())

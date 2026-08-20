"""Resume interrupted Massive historical data downloads safely.

The script treats IWB_holdings.csv as the authoritative Russell 1000 universe
and historical_bars.csv as the schema contract. It resumes from the Massive
checkpoint file, skips only trusted completed symbols, and never deletes valid
existing data.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from current_reference.PaperTradingR1000.massive_historical_downloader import (  # noqa: E402
    DEFAULT_CHECKPOINT_FILE,
    DEFAULT_DAILY_BARS_DIR,
    DEFAULT_OUTPUT_FILE,
    DEFAULT_SCHEMA_FILE,
    DEFAULT_UNIVERSE_FILE,
    EXPECTED_SCHEMA,
    DownloadError,
    MassiveClient,
    SymbolDownloadResult,
    UniverseEntry,
    aggregate_to_schema_row,
    backup_file,
    default_start_date,
    load_iwb_universe,
    load_schema,
    merge_rows,
    normalize_symbol,
    read_schema_rows,
    rows_for_symbol,
    validate_rows_against_schema,
    write_csv_atomic,
)

RESULTS_DIR = PROJECT_ROOT / "ibkr_r1000_results"
LEGACY_PROGRESS_FILE = RESULTS_DIR / "massive_download_progress.json"
RESUME_PROGRESS_FILE = RESULTS_DIR / "massive_resume_progress.json"
VALIDATION_REPORT_FILE = RESULTS_DIR / "massive_resume_validation_report.json"
MISSING_REPORT_FILE = RESULTS_DIR / "massive_resume_missing_symbols.csv"
FAILED_REPORT_FILE = RESULTS_DIR / "massive_resume_failed_symbols.csv"
LOG_FILE = RESULTS_DIR / "massive_resume.log"

REQUIRED_FIELDS = ("ticker", "name", "local_symbol", "date", "open", "high", "low", "close", "volume")


def print_progress(message: str, **fields: Any) -> None:
    payload = {"timestamp_utc": utc_now_text(), "message": message, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def parse_yyyymmdd(value: str) -> date | None:
    text = value.strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def append_log(log_path: Path, message: str, **fields: Any) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp_utc": utc_now_text(), "message": message, **fields}
    with log_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


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


def default_download_dates() -> tuple[date, date]:
    progress = read_json(LEGACY_PROGRESS_FILE)
    start_text = progress.get("start_date")
    end_text = progress.get("end_date")
    if isinstance(start_text, str) and isinstance(end_text, str):
        try:
            return parse_iso_date(start_text), parse_iso_date(end_text)
        except argparse.ArgumentTypeError:
            pass
    today = date.today()
    return default_start_date(today), today


def read_progress(path: Path) -> tuple[set[str], dict[str, str]]:
    progress = read_json(path)
    completed = {normalize_symbol(str(symbol)) for symbol in progress.get("completed_symbols") or []}
    failed_raw = progress.get("failed_symbols") or {}
    failed = {normalize_symbol(str(symbol)): str(error) for symbol, error in failed_raw.items()}
    return completed, failed


def write_progress(
    path: Path,
    *,
    start_date: date,
    end_date: date,
    adjusted: bool,
    completed_symbols: set[str],
    failed_symbols: dict[str, str],
) -> None:
    write_json_atomic(
        path,
        {
            "updated_at_utc": utc_now_text(),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "adjusted": adjusted,
            "completed_symbols": sorted(completed_symbols),
            "failed_symbols": dict(sorted(failed_symbols.items())),
        },
    )


def read_current_rows(checkpoint_file: Path, output_file: Path, schema: list[str]) -> tuple[list[dict[str, str]], Path]:
    if checkpoint_file.exists() and checkpoint_file.stat().st_size > 0:
        return read_schema_rows(checkpoint_file, schema), checkpoint_file
    return read_schema_rows(output_file, schema), output_file


def current_rows_source(checkpoint_file: Path, output_file: Path) -> Path:
    if checkpoint_file.exists() and checkpoint_file.stat().st_size > 0:
        return checkpoint_file
    return output_file


def read_symbol_rows_from_file(path: Path, schema: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        return read_schema_rows(path, schema)
    except DownloadError:
        return []


def row_date_in_range(row: dict[str, str], start_date: date, end_date: date) -> bool:
    parsed = parse_yyyymmdd(str(row.get("date", "")))
    if parsed is None:
        return False
    return start_date <= parsed <= end_date


def warn_about_stale_temp_file(path: Path, log_file: Path) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    if tmp_path.exists():
        message = (
            "stale_temp_checkpoint_ignored"
            if path.name.endswith(".csv")
            else "stale_temp_file_ignored"
        )
        fields = {"path": str(tmp_path), "bytes": tmp_path.stat().st_size}
        print_progress(message, **fields)
        append_log(log_file, message, **fields)


def validate_symbol_rows(
    symbol: str,
    rows: list[dict[str, str]],
    entry: UniverseEntry,
    schema: list[str],
    start_date: date,
    end_date: date,
) -> tuple[bool, list[str]]:
    symbol_rows = rows_for_symbol(rows, symbol)
    if not symbol_rows:
        return False, ["no_rows"]
    validation = validate_rows_against_schema(symbol_rows, schema, [entry], start_date, end_date)
    return validation.passed, validation.errors


def analyze_dataset(
    entries: list[UniverseEntry],
    rows: list[dict[str, str]],
    schema: list[str],
    *,
    start_date: date,
    end_date: date,
    daily_bars_dir: Path,
    legacy_progress_file: Path,
    resume_progress_file: Path,
) -> dict[str, Any]:
    universe_symbols = [entry.symbol for entry in entries]
    entries_by_symbol = {entry.symbol: entry for entry in entries}
    universe_set = set(universe_symbols)

    legacy_completed, legacy_failed = read_progress(legacy_progress_file)
    resume_completed, resume_failed = read_progress(resume_progress_file)
    trusted_completed = (legacy_completed | resume_completed) & universe_set
    failed_symbols = {**legacy_failed, **resume_failed}

    symbol_counts: dict[str, int] = {}
    duplicate_rows: dict[str, int] = {}
    missing_fields: dict[str, int] = {}
    invalid_dates: dict[str, int] = {}
    out_of_range: dict[str, int] = {}
    local_symbol_mismatches: dict[str, int] = {}
    rows_by_symbol: dict[str, list[dict[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    out_of_order = 0
    previous_key: tuple[str, str] | None = None

    for index, row in enumerate(rows, start=1):
        symbol = normalize_symbol(str(row.get("ticker", "")))
        date_text = str(row.get("date", "")).strip()
        if symbol:
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
            rows_by_symbol.setdefault(symbol, []).append(row)

        key = (symbol, date_text)
        if key in seen:
            duplicate_rows[symbol] = duplicate_rows.get(symbol, 0) + 1
        seen.add(key)

        if previous_key is not None and key < previous_key:
            out_of_order += 1
        previous_key = key

        if any(str(row.get(field, "")).strip() == "" for field in REQUIRED_FIELDS):
            missing_fields[symbol] = missing_fields.get(symbol, 0) + 1

        parsed_date = parse_yyyymmdd(date_text)
        if parsed_date is None:
            invalid_dates[symbol] = invalid_dates.get(symbol, 0) + 1
        elif parsed_date < start_date or parsed_date > end_date:
            out_of_range[symbol] = out_of_range.get(symbol, 0) + 1

        local_symbol = normalize_symbol(str(row.get("local_symbol", "")))
        if symbol and local_symbol != symbol:
            local_symbol_mismatches[symbol] = local_symbol_mismatches.get(symbol, 0) + 1
        if index % 250_000 == 0:
            print_progress("dataset_analysis_rows_progress", rows_analyzed=index, rows_total=len(rows))

    daily_files = {path.stem for path in daily_bars_dir.glob("*.csv") if path.name != ".gitkeep"} if daily_bars_dir.exists() else set()
    rows_symbols = set(symbol_counts) & universe_set

    valid_completed: list[str] = []
    invalid_completed: list[str] = []
    sorted_trusted_completed = sorted(trusted_completed)
    for index, symbol in enumerate(sorted_trusted_completed, start=1):
        entry = entries_by_symbol[symbol]
        file_rows = read_symbol_rows_from_file(daily_bars_dir / f"{symbol}.csv", schema)
        source_rows = file_rows if symbol in resume_completed and file_rows else rows_by_symbol.get(symbol, [])
        if not source_rows and file_rows:
            source_rows = file_rows
        symbol_rows = [row for row in sorted(source_rows, key=lambda item: str(item.get("date", ""))) if row_date_in_range(row, start_date, end_date)]
        ok, _errors = validate_symbol_rows(symbol, symbol_rows, entry, schema, start_date, end_date)
        if ok:
            valid_completed.append(symbol)
        else:
            invalid_completed.append(symbol)
        if index % 100 == 0:
            print_progress(
                "dataset_analysis_completed_symbols_progress",
                symbols_analyzed=index,
                symbols_total=len(sorted_trusted_completed),
            )

    missing_symbols = [symbol for symbol in universe_symbols if symbol not in rows_symbols and symbol not in daily_files]
    untrusted_with_rows = sorted((rows_symbols | (daily_files & universe_set)) - set(valid_completed))
    incomplete_or_failed = sorted(set(untrusted_with_rows) | set(invalid_completed) | (set(failed_symbols) & universe_set))
    download_targets = [symbol for symbol in universe_symbols if symbol in set(missing_symbols) | set(incomplete_or_failed)]

    first_dates: dict[str, str] = {}
    last_dates: dict[str, str] = {}
    history_starts_after_requested_start_symbols: list[str] = []
    potential_partial_history_symbols: list[str] = []
    for symbol in sorted(rows_symbols):
        dates = sorted(str(row.get("date", "")).strip() for row in rows_by_symbol.get(symbol, []) if str(row.get("date", "")).strip())
        if not dates:
            continue
        first_dates[symbol] = dates[0]
        last_dates[symbol] = dates[-1]
        first = parse_yyyymmdd(dates[0])
        last = parse_yyyymmdd(dates[-1])
        if first is None or last is None:
            continue
        if first > start_date:
            history_starts_after_requested_start_symbols.append(symbol)
        if last < end_date - timedelta(days=10):
            potential_partial_history_symbols.append(symbol)

    return {
        "created_at_utc": utc_now_text(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "schema_matches_reference": schema == EXPECTED_SCHEMA,
        "universe_symbols": len(universe_symbols),
        "rows": len(rows),
        "symbols_with_rows": len(rows_symbols),
        "daily_bar_files": len(daily_files & universe_set),
        "completed_symbols": valid_completed,
        "missing_symbols": missing_symbols,
        "incomplete_or_failed_symbols": incomplete_or_failed,
        "download_targets": download_targets,
        "failed_symbols": {symbol: failed_symbols[symbol] for symbol in sorted(failed_symbols) if symbol in universe_set},
        "quality": {
            "duplicate_ticker_date_symbols": {k: v for k, v in sorted(duplicate_rows.items()) if k in universe_set},
            "missing_ohlcv_symbols": {k: v for k, v in sorted(missing_fields.items()) if k in universe_set},
            "invalid_date_symbols": {k: v for k, v in sorted(invalid_dates.items()) if k in universe_set},
            "out_of_range_symbols": {k: v for k, v in sorted(out_of_range.items()) if k in universe_set},
            "local_symbol_mismatch_symbols": {k: v for k, v in sorted(local_symbol_mismatches.items()) if k in universe_set},
            "out_of_order_rows": out_of_order,
            "history_starts_after_requested_start_symbols": history_starts_after_requested_start_symbols,
            "potential_partial_history_symbols": potential_partial_history_symbols,
        },
        "row_counts": {symbol: symbol_counts.get(symbol, 0) for symbol in universe_symbols if symbol_counts.get(symbol, 0)},
        "first_dates": first_dates,
        "last_dates": last_dates,
    }


def write_validation_artifacts(report: dict[str, Any], validation_report_file: Path, missing_report_file: Path, failed_report_file: Path) -> None:
    write_json_atomic(validation_report_file, report)

    row_counts = report["row_counts"]
    missing_rows = []
    for symbol in report["missing_symbols"]:
        missing_rows.append({"symbol": symbol, "status": "missing", "reason": "no rows found", "row_count": 0})
    for symbol in report["incomplete_or_failed_symbols"]:
        reason = "failed" if symbol in report["failed_symbols"] else "untrusted_or_incomplete"
        missing_rows.append({"symbol": symbol, "status": "incomplete_or_failed", "reason": reason, "row_count": row_counts.get(symbol, 0)})
    write_csv_atomic(missing_report_file, ["symbol", "status", "reason", "row_count"], missing_rows)

    failed_rows = [
        {"symbol": symbol, "error": error}
        for symbol, error in sorted(report["failed_symbols"].items())
    ]
    write_csv_atomic(failed_report_file, ["symbol", "error"], failed_rows)


def print_summary(mode: str, report: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
    payload = {
        "mode": mode,
        "universe_symbols": report["universe_symbols"],
        "completed_symbols": len(report["completed_symbols"]),
        "missing_symbols": len(report["missing_symbols"]),
        "incomplete_or_failed_symbols": len(report["incomplete_or_failed_symbols"]),
        "download_targets": len(report["download_targets"]),
        "quality": {
            "duplicate_ticker_date_symbols": len(report["quality"]["duplicate_ticker_date_symbols"]),
            "missing_ohlcv_symbols": len(report["quality"]["missing_ohlcv_symbols"]),
            "invalid_date_symbols": len(report["quality"]["invalid_date_symbols"]),
            "out_of_range_symbols": len(report["quality"]["out_of_range_symbols"]),
            "local_symbol_mismatch_symbols": len(report["quality"]["local_symbol_mismatch_symbols"]),
            "out_of_order_rows": report["quality"]["out_of_order_rows"],
            "history_starts_after_requested_start_symbols": len(report["quality"]["history_starts_after_requested_start_symbols"]),
            "potential_partial_history_symbols": len(report["quality"]["potential_partial_history_symbols"]),
        },
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, indent=2, sort_keys=True))


def select_targets(report: dict[str, Any], symbols_arg: str | None, max_symbols: int | None) -> list[str]:
    targets = list(report["download_targets"])
    if symbols_arg:
        requested = [normalize_symbol(symbol) for symbol in symbols_arg.split(",") if symbol.strip()]
        target_set = set(targets)
        targets = [symbol for symbol in requested if symbol in target_set]
    if max_symbols is not None:
        targets = targets[:max_symbols]
    return targets


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


def write_csv_atomic_with_progress(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
    *,
    operation: str,
    progress_every: int = 50_000,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    print_progress(f"{operation}_start", path=str(path), rows=len(rows), temp_path=str(tmp_path))
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow({field: row.get(field, "") for field in fieldnames})
            if index % progress_every == 0:
                print_progress(f"{operation}_progress", path=str(path), rows_written=index, rows_total=len(rows))
    print_progress(f"{operation}_replace_start", path=str(path), temp_path=str(tmp_path))
    tmp_path.replace(path)
    print_progress(f"{operation}_complete", path=str(path), rows_written=len(rows))


def consolidate_rows_with_symbol_files(
    base_rows: list[dict[str, str]],
    schema: list[str],
    completed_symbols: list[str],
    daily_bars_dir: Path,
) -> list[dict[str, str]]:
    mapped: dict[tuple[str, str], dict[str, str]] = {}
    for row in base_rows:
        symbol = normalize_symbol(str(row.get("ticker", "")))
        date_text = str(row.get("date", "")).strip()
        if symbol and date_text:
            mapped[(symbol, date_text)] = dict(row)

    for symbol in completed_symbols:
        file_rows = read_symbol_rows_from_file(daily_bars_dir / f"{symbol}.csv", schema)
        if not file_rows:
            continue
        for key in [key for key in mapped if key[0] == symbol]:
            del mapped[key]
        for row in file_rows:
            date_text = str(row.get("date", "")).strip()
            if date_text:
                mapped[(symbol, date_text)] = dict(row)

    return [mapped[key] for key in sorted(mapped, key=lambda item: (item[0], item[1]))]


def download_targets(
    client: MassiveClient,
    targets: list[str],
    entries_by_symbol: dict[str, UniverseEntry],
    rows: list[dict[str, str]],
    schema: list[str],
    args: argparse.Namespace,
    completed_symbols: set[str],
    failed_symbols: dict[str, str],
) -> tuple[list[dict[str, str]], list[SymbolDownloadResult]]:
    results: list[SymbolDownloadResult] = []

    for index, symbol in enumerate(targets, start=1):
        entry = entries_by_symbol[symbol]
        append_log(args.log_file, "download_start", symbol=symbol, index=index, total=len(targets))
        started = datetime.now(timezone.utc)
        try:
            aggregates, attempts = client.get_daily_aggregates(
                symbol,
                args.start_date,
                args.end_date,
                adjusted=args.adjusted,
            )
            incoming_rows = merge_rows([], [aggregate_to_schema_row(item, entry) for item in aggregates])
            if not incoming_rows:
                failed_symbols[symbol] = "no rows returned by Massive"
                result = SymbolDownloadResult(
                    ticker=symbol,
                    name=entry.name,
                    status="no_data",
                    bars_received=0,
                    attempts=attempts,
                    elapsed_seconds=(datetime.now(timezone.utc) - started).total_seconds(),
                    local_symbol=symbol,
                    primary_exchange=entry.exchange,
                    error=failed_symbols[symbol],
                )
                results.append(result)
                append_log(args.log_file, "download_no_data", symbol=symbol, attempts=attempts)
                continue

            ok, errors = validate_symbol_rows(symbol, incoming_rows, entry, schema, args.start_date, args.end_date)
            if not ok:
                failed_symbols[symbol] = "; ".join(errors)
                result = SymbolDownloadResult(
                    ticker=symbol,
                    name=entry.name,
                    status="failed",
                    bars_received=len(incoming_rows),
                    attempts=attempts,
                    elapsed_seconds=(datetime.now(timezone.utc) - started).total_seconds(),
                    local_symbol=symbol,
                    primary_exchange=entry.exchange,
                    error=failed_symbols[symbol],
                )
                results.append(result)
                append_log(args.log_file, "download_validation_failed", symbol=symbol, attempts=attempts, error=failed_symbols[symbol])
                continue

            symbol_checkpoint = args.daily_bars_dir / f"{symbol}.csv"
            print_progress("symbol_checkpoint_write_start", symbol=symbol, rows=len(incoming_rows), path=str(symbol_checkpoint))
            write_csv_atomic(symbol_checkpoint, schema, incoming_rows)
            print_progress("symbol_checkpoint_write_complete", symbol=symbol, rows=len(incoming_rows), path=str(symbol_checkpoint))
            completed_symbols.add(symbol)
            failed_symbols.pop(symbol, None)

            result = SymbolDownloadResult(
                ticker=symbol,
                name=entry.name,
                status="ok",
                bars_received=len(incoming_rows),
                attempts=attempts,
                elapsed_seconds=(datetime.now(timezone.utc) - started).total_seconds(),
                local_symbol=symbol,
                primary_exchange=entry.exchange,
            )
            results.append(result)
            append_log(args.log_file, "download_complete", symbol=symbol, rows=len(incoming_rows), attempts=attempts)
        except DownloadError as exc:
            failed_symbols[symbol] = str(exc)
            result = SymbolDownloadResult(
                ticker=symbol,
                name=entry.name,
                status="failed",
                bars_received=0,
                attempts=0,
                elapsed_seconds=(datetime.now(timezone.utc) - started).total_seconds(),
                local_symbol=symbol,
                primary_exchange=entry.exchange,
                error=str(exc),
            )
            results.append(result)
            append_log(args.log_file, "download_failed", symbol=symbol, error=str(exc))
        finally:
            write_progress(
                args.resume_progress_file,
                start_date=args.start_date,
                end_date=args.end_date,
                adjusted=args.adjusted,
                completed_symbols=completed_symbols,
                failed_symbols=failed_symbols,
            )
            failed_rows = [{"symbol": item, "error": failed_symbols[item]} for item in sorted(failed_symbols)]
            write_csv_atomic(args.failed_report_file, ["symbol", "error"], failed_rows)
            append_log(
                args.log_file,
                "checkpoint_updated",
                checkpoint_type="per_symbol_csv_and_progress_json",
                symbol=symbol,
                symbols_processed=index,
                full_checkpoint_rewrite=False,
            )

    return rows, results


def maybe_finalize_output(
    entries: list[UniverseEntry],
    rows: list[dict[str, str]],
    schema: list[str],
    args: argparse.Namespace,
    report: dict[str, Any],
) -> Path | None:
    if report["download_targets"]:
        return None
    if not args.finalize_output:
        append_log(
            args.log_file,
            "final_output_not_rewritten",
            reason="finalize_output_not_requested",
            output_file=str(args.output_file),
        )
        return None
    backup = backup_file(args.output_file)
    print_progress(
        "final_output_consolidation_start",
        base_rows=len(rows),
        completed_symbols=len(report["completed_symbols"]),
    )
    consolidated_rows = consolidate_rows_with_symbol_files(
        rows,
        schema,
        report["completed_symbols"],
        args.daily_bars_dir,
    )
    print_progress("final_output_consolidation_complete", rows=len(consolidated_rows))
    write_csv_atomic_with_progress(
        args.output_file,
        schema,
        consolidated_rows,
        operation="final_output_write",
    )
    append_log(args.log_file, "finalized_output", output_file=str(args.output_file), backup_file=str(backup or ""))
    return backup


def build_parser() -> argparse.ArgumentParser:
    start_default, end_default = default_download_dates()
    parser = argparse.ArgumentParser(description="Resume Massive OHLCV downloads for missing TradingbotR1000 symbols")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validation-only", action="store_true", help="validate current dataset and write reports without API calls")
    mode.add_argument("--dry-run", action="store_true", help="show symbols that would be downloaded without API calls")
    mode.add_argument("--download-missing", action="store_true", help="download only missing or untrusted symbols")
    parser.add_argument("--symbols", help="comma-separated symbols to consider, restricted to missing/incomplete targets")
    parser.add_argument("--max-symbols", type=int, help="cap downloads or dry-run target count")
    parser.add_argument("--start-date", type=parse_iso_date, default=start_default)
    parser.add_argument("--end-date", type=parse_iso_date, default=end_default)
    parser.add_argument("--adjusted", action="store_true", help="request adjusted bars from Massive")
    parser.add_argument("--api-base-url", default="https://api.massive.com")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--schema-file", type=Path, default=DEFAULT_SCHEMA_FILE)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--checkpoint-file", type=Path, default=DEFAULT_CHECKPOINT_FILE)
    parser.add_argument("--daily-bars-dir", type=Path, default=DEFAULT_DAILY_BARS_DIR)
    parser.add_argument("--legacy-progress-file", type=Path, default=LEGACY_PROGRESS_FILE)
    parser.add_argument("--resume-progress-file", type=Path, default=RESUME_PROGRESS_FILE)
    parser.add_argument("--validation-report-file", type=Path, default=VALIDATION_REPORT_FILE)
    parser.add_argument("--missing-report-file", type=Path, default=MISSING_REPORT_FILE)
    parser.add_argument("--failed-report-file", type=Path, default=FAILED_REPORT_FILE)
    parser.add_argument("--log-file", type=Path, default=LOG_FILE)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--backoff-seconds", type=float, default=2.0)
    parser.add_argument("--rate-limit-pause-seconds", type=float, default=1.0)
    parser.add_argument(
        "--finalize-output",
        action="store_true",
        help="after all targets are complete, rewrite the consolidated historical_bars.csv with progress output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start_date > args.end_date:
        parser.error("--start-date cannot be after --end-date")
    if args.max_symbols is not None and args.max_symbols < 1:
        parser.error("--max-symbols must be at least 1")
    schema = load_schema(args.schema_file)
    entries = load_iwb_universe(args.universe_file)
    entries_by_symbol = {entry.symbol: entry for entry in entries}
    warn_about_stale_temp_file(args.checkpoint_file, args.log_file)
    read_source = current_rows_source(args.checkpoint_file, args.output_file)
    print_progress(
        "checkpoint_read_start",
        path=str(read_source),
        bytes=read_source.stat().st_size if read_source.exists() else 0,
    )
    rows, source_file = read_current_rows(args.checkpoint_file, args.output_file, schema)
    print_progress(
        "checkpoint_read_complete",
        path=str(source_file),
        rows=len(rows),
        bytes=source_file.stat().st_size if source_file.exists() else 0,
    )
    if source_file != args.checkpoint_file:
        print_progress(
            "full_checkpoint_rewrite_skipped",
            reason="normal resume uses per-symbol CSV checkpoints and progress JSON",
            source_file=str(source_file),
            checkpoint_file=str(args.checkpoint_file),
        )

    print_progress("dataset_analysis_start", rows=len(rows), universe_symbols=len(entries))
    report = analyze_dataset(
        entries,
        rows,
        schema,
        start_date=args.start_date,
        end_date=args.end_date,
        daily_bars_dir=args.daily_bars_dir,
        legacy_progress_file=args.legacy_progress_file,
        resume_progress_file=args.resume_progress_file,
    )
    print_progress(
        "dataset_analysis_complete",
        completed_symbols=len(report["completed_symbols"]),
        missing_symbols=len(report["missing_symbols"]),
        incomplete_or_failed_symbols=len(report["incomplete_or_failed_symbols"]),
        download_targets=len(report["download_targets"]),
    )
    write_validation_artifacts(report, args.validation_report_file, args.missing_report_file, args.failed_report_file)

    if args.validation_only:
        append_log(args.log_file, "validation_only", source_file=str(source_file), download_targets=len(report["download_targets"]))
        print_summary("validation-only", report, {"source_file": str(source_file)})
        return 0

    targets = select_targets(report, args.symbols, args.max_symbols)
    if args.dry_run:
        append_log(args.log_file, "dry_run", targets=len(targets))
        print_summary("dry-run", report, {"selected_targets": targets})
        return 0

    client = make_client(args)
    legacy_completed, legacy_failed = read_progress(args.legacy_progress_file)
    resume_completed, resume_failed = read_progress(args.resume_progress_file)
    completed_symbols = (legacy_completed | resume_completed) & set(entries_by_symbol)
    failed_symbols = {**legacy_failed, **resume_failed}
    append_log(args.log_file, "download_run_start", targets=len(targets), max_symbols=args.max_symbols)
    rows, results = download_targets(
        client,
        targets,
        entries_by_symbol,
        rows,
        schema,
        args,
        completed_symbols,
        failed_symbols,
    )

    final_report = analyze_dataset(
        entries,
        rows,
        schema,
        start_date=args.start_date,
        end_date=args.end_date,
        daily_bars_dir=args.daily_bars_dir,
        legacy_progress_file=args.legacy_progress_file,
        resume_progress_file=args.resume_progress_file,
    )
    write_validation_artifacts(final_report, args.validation_report_file, args.missing_report_file, args.failed_report_file)
    backup = maybe_finalize_output(entries, rows, schema, args, final_report)
    print_summary(
        "download-missing",
        final_report,
        {
            "attempted_symbols": len(targets),
            "download_results": [asdict(item) for item in results],
            "output_finalized": backup is not None,
            "backup_file": str(backup) if backup else "",
        },
    )
    append_log(args.log_file, "download_run_complete", attempted=len(targets), remaining=len(final_report["download_targets"]))
    return 0 if not any(item.status == "failed" for item in results) else 4


if __name__ == "__main__":
    raise SystemExit(main())

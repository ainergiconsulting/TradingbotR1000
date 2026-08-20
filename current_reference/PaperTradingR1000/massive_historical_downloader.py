"""Massive historical market data downloader for TradingbotR1000.

This module acquires daily OHLCV bars from Massive and writes data in the
existing IBKR historical_bars.csv schema so the migrated R1000 loader can use
the same CSV contract. It contains no strategy logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .symbol_mapping import canonical_symbol as normalize_symbol
except ImportError:  # pragma: no cover - supports direct script execution.
    from symbol_mapping import canonical_symbol as normalize_symbol


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE_FILE = PROJECT_ROOT / "IWB_holdings.csv"
DEFAULT_SCHEMA_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "historical_bars.csv"
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "historical_bars.csv"
DEFAULT_SAMPLE_OUTPUT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "massive_sample_historical_bars.csv"
DEFAULT_REQUEST_REPORT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "massive_request_report.csv"
DEFAULT_SAMPLE_REQUEST_REPORT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "massive_sample_request_report.csv"
DEFAULT_DOWNLOAD_REPORT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "massive_download_report.json"
DEFAULT_SAMPLE_REPORT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "massive_sample_download_report.json"
DEFAULT_PROGRESS_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "massive_download_progress.json"
DEFAULT_CHECKPOINT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "historical_bars.massive_checkpoint.csv"
DEFAULT_DAILY_BARS_DIR = PROJECT_ROOT / "data" / "daily_bars"
DEFAULT_ENGINE_UNIVERSE_FILE = PROJECT_ROOT / "config" / "russell1000_universe.csv"

EXPECTED_SCHEMA = [
    "ticker",
    "name",
    "con_id",
    "local_symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "bar_count",
    "average",
]

REQUEST_REPORT_FIELDS = [
    "ticker",
    "name",
    "status",
    "bars_received",
    "attempts",
    "elapsed_seconds",
    "con_id",
    "local_symbol",
    "primary_exchange",
    "error",
]

RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
DATE_RE = re.compile(r"^\d{8}$")


class DownloadError(RuntimeError):
    """Raised when a Massive request or CSV validation cannot continue."""


@dataclass(frozen=True)
class UniverseEntry:
    source_symbol: str
    symbol: str
    name: str
    exchange: str
    currency: str
    sector: str


@dataclass
class SymbolDownloadResult:
    ticker: str
    name: str
    status: str
    bars_received: int
    attempts: int
    elapsed_seconds: float
    local_symbol: str
    primary_exchange: str
    error: str = ""
    con_id: str = ""


@dataclass
class ValidationResult:
    passed: bool
    rows: int
    symbols: int
    duplicates: int
    missing_fields: int
    invalid_dates: int
    out_of_order: int
    symbol_mismatches: int
    errors: list[str]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_start_date(today: date | None = None) -> date:
    today = today or date.today()
    try:
        return today.replace(year=today.year - 10)
    except ValueError:
        return today.replace(year=today.year - 10, day=28)


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def _is_valid_symbol(symbol: str) -> bool:
    return bool(symbol) and bool(re.match(r"^[A-Z0-9]+(?:\.[A-Z0-9]+)?$", symbol))


def load_iwb_universe(path: Path) -> list[UniverseEntry]:
    if not path.exists():
        raise DownloadError(f"universe file missing: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    header_index = None
    for index, row in enumerate(rows):
        cleaned = [cell.strip() for cell in row]
        if "Ticker" in cleaned and "Name" in cleaned:
            header_index = index
            break

    if header_index is None:
        raise DownloadError("IWB universe header row was not found")

    entries: list[UniverseEntry] = []
    seen: set[str] = set()
    fieldnames = rows[header_index]
    for raw in rows[header_index + 1 :]:
        if not raw or not any(cell.strip() for cell in raw):
            continue
        row = {fieldnames[i].strip(): raw[i].strip() if i < len(raw) else "" for i in range(len(fieldnames))}
        source_symbol = row.get("Ticker", "").strip()
        symbol = normalize_symbol(source_symbol)
        asset_class = row.get("Asset Class", "").strip().lower()
        currency = row.get("Currency", "").strip().upper()
        market_currency = row.get("Market Currency", "").strip().upper()
        if asset_class and asset_class != "equity":
            continue
        if currency and currency != "USD":
            continue
        if market_currency and market_currency != "USD":
            continue
        if not _is_valid_symbol(symbol):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        entries.append(
            UniverseEntry(
                source_symbol=source_symbol,
                symbol=symbol,
                name=row.get("Name", "").strip(),
                exchange=row.get("Exchange", "").strip(),
                currency=currency or market_currency,
                sector=row.get("Sector", "").strip(),
            )
        )

    if not entries:
        raise DownloadError("IWB universe contains no valid equity symbols")
    return entries


def load_schema(path: Path) -> list[str]:
    if not path.exists():
        raise DownloadError(f"schema reference missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise DownloadError(f"schema reference is empty: {path}") from exc
    schema = [column.strip() for column in header]
    if schema != EXPECTED_SCHEMA:
        raise DownloadError(
            "schema reference does not match expected historical_bars.csv columns: "
            + ",".join(schema)
        )
    return schema


def _format_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.10f}".rstrip("0").rstrip(".")


def _timestamp_to_yyyymmdd(value: Any) -> str:
    if value is None:
        return ""
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).strftime("%Y%m%d")


def aggregate_to_schema_row(aggregate: dict[str, Any], entry: UniverseEntry) -> dict[str, str]:
    return {
        "ticker": entry.symbol,
        "name": entry.name,
        "con_id": "",
        "local_symbol": entry.symbol,
        "date": _timestamp_to_yyyymmdd(aggregate.get("t")),
        "open": _format_number(aggregate.get("o")),
        "high": _format_number(aggregate.get("h")),
        "low": _format_number(aggregate.get("l")),
        "close": _format_number(aggregate.get("c")),
        "volume": _format_number(aggregate.get("v")),
        "bar_count": _format_number(aggregate.get("n")),
        "average": _format_number(aggregate.get("vw")),
    }


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8", newline="")
    tmp_path.replace(path)


def write_csv_atomic(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    tmp_path.replace(path)


def backup_file(path: Path) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}.backup_{stamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    return backup_path


def read_schema_rows(path: Path, schema: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != schema:
            raise DownloadError(f"CSV schema mismatch: {path}")
        return [{field: row.get(field, "") for field in schema} for row in reader]


def merge_rows(existing: Iterable[dict[str, str]], incoming: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str], dict[str, str]] = {}
    for row in existing:
        key = (str(row.get("ticker", "")).strip().upper(), str(row.get("date", "")).strip())
        if key[0] and key[1]:
            merged[key] = dict(row)
    for row in incoming:
        key = (str(row.get("ticker", "")).strip().upper(), str(row.get("date", "")).strip())
        if key[0] and key[1]:
            merged[key] = dict(row)
    return [merged[key] for key in sorted(merged, key=lambda item: (item[0], item[1]))]


def filter_rows_by_date_range(rows: Iterable[dict[str, str]], start_date: date, end_date: date) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for row in rows:
        date_text = str(row.get("date", "")).strip()
        try:
            parsed_date = datetime.strptime(date_text, "%Y%m%d").date()
        except ValueError:
            continue
        if start_date <= parsed_date <= end_date:
            filtered.append(row)
    return filtered


def rows_for_symbol(rows: Iterable[dict[str, str]], symbol: str) -> list[dict[str, str]]:
    return sorted(
        [row for row in rows if str(row.get("ticker", "")).strip().upper() == symbol],
        key=lambda row: str(row.get("date", "")),
    )


def validate_rows_against_schema(
    rows: list[dict[str, str]],
    schema: list[str],
    entries: list[UniverseEntry],
    start_date: date,
    end_date: date,
) -> ValidationResult:
    errors: list[str] = []
    duplicate_count = 0
    missing_fields = 0
    invalid_dates = 0
    symbol_mismatches = 0
    out_of_order = 0
    seen: set[tuple[str, str]] = set()
    expected_symbols = {entry.symbol for entry in entries}
    previous_key: tuple[str, str] | None = None
    required_fields = {"ticker", "name", "local_symbol", "date", "open", "high", "low", "close", "volume"}

    for row in rows:
        if set(schema) - set(row):
            missing_fields += 1
        for field in required_fields:
            if str(row.get(field, "")).strip() == "":
                missing_fields += 1
                break

        ticker = str(row.get("ticker", "")).strip().upper()
        local_symbol = str(row.get("local_symbol", "")).strip().upper()
        date_text = str(row.get("date", "")).strip()
        if ticker not in expected_symbols or local_symbol != ticker:
            symbol_mismatches += 1

        key = (ticker, date_text)
        if key in seen:
            duplicate_count += 1
        seen.add(key)

        if previous_key is not None and key < previous_key:
            out_of_order += 1
        previous_key = key

        try:
            if not DATE_RE.match(date_text):
                raise ValueError(date_text)
            parsed_date = datetime.strptime(date_text, "%Y%m%d").date()
            if parsed_date < start_date or parsed_date > end_date:
                raise ValueError(date_text)
        except ValueError:
            invalid_dates += 1

        for numeric_field in ("open", "high", "low", "close", "volume"):
            try:
                float(str(row.get(numeric_field, "")).strip())
            except ValueError:
                missing_fields += 1
                break

    if not rows:
        errors.append("no rows returned")
    missing_symbols = sorted(symbol for symbol in expected_symbols if not rows_for_symbol(rows, symbol))
    if missing_symbols:
        errors.append("no bars returned for: " + ", ".join(missing_symbols))
    if duplicate_count:
        errors.append(f"duplicate ticker/date rows: {duplicate_count}")
    if missing_fields:
        errors.append(f"rows with missing or invalid required fields: {missing_fields}")
    if invalid_dates:
        errors.append(f"invalid or out-of-range dates: {invalid_dates}")
    if symbol_mismatches:
        errors.append(f"symbol normalization mismatches: {symbol_mismatches}")
    if out_of_order:
        errors.append(f"rows out of ticker/date order: {out_of_order}")

    return ValidationResult(
        passed=not errors,
        rows=len(rows),
        symbols=len({row.get("ticker", "") for row in rows}),
        duplicates=duplicate_count,
        missing_fields=missing_fields,
        invalid_dates=invalid_dates,
        out_of_order=out_of_order,
        symbol_mismatches=symbol_mismatches,
        errors=errors,
    )


class MassiveClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.massive.com",
        timeout_seconds: int = 30,
        max_retries: int = 5,
        backoff_seconds: float = 2.0,
        rate_limit_pause_seconds: float = 0.25,
    ) -> None:
        if not api_key.strip():
            raise DownloadError("MASSIVE_API_KEY is not present in this process")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.rate_limit_pause_seconds = rate_limit_pause_seconds

    def _add_api_key(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not any(key.lower() == "apikey" for key, _ in query):
            query.append(("apiKey", self.api_key))
        return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))

    def _request_json(self, url: str) -> tuple[dict[str, Any], int]:
        safe_error = "Massive request failed"
        for attempt in range(1, self.max_retries + 2):
            request = urllib.request.Request(
                self._add_api_key(url),
                headers={"Accept": "application/json", "User-Agent": "TradingbotR1000/1.0"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if self.rate_limit_pause_seconds > 0:
                    time.sleep(self.rate_limit_pause_seconds)
                return payload, attempt
            except urllib.error.HTTPError as exc:
                status = exc.code
                body = exc.read(500).decode("utf-8", errors="replace")
                if status not in RETRYABLE_HTTP_STATUS or attempt > self.max_retries:
                    raise DownloadError(f"{safe_error}: HTTP {status}: {body}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else self.backoff_seconds * (2 ** (attempt - 1))
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt > self.max_retries:
                    raise DownloadError(f"{safe_error}: {exc.__class__.__name__}") from exc
                time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        raise DownloadError(safe_error)

    def get_daily_aggregates(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        *,
        adjusted: bool,
    ) -> tuple[list[dict[str, Any]], int]:
        encoded_symbol = urllib.parse.quote(symbol, safe="")
        path = f"{self.base_url}/v2/aggs/ticker/{encoded_symbol}/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}"
        query = urllib.parse.urlencode(
            {
                "adjusted": str(adjusted).lower(),
                "sort": "asc",
                "limit": "50000",
            }
        )
        next_url = f"{path}?{query}"
        results: list[dict[str, Any]] = []
        attempts = 0

        while next_url:
            payload, page_attempts = self._request_json(next_url)
            attempts += page_attempts
            page_results = payload.get("results") or []
            if not isinstance(page_results, list):
                raise DownloadError(f"unexpected Massive response for {symbol}: results is not a list")
            results.extend(page_results)
            next_url = str(payload.get("next_url") or "").strip()

        return results, attempts

    def validate_connection(self, symbol: str, start_date: date, end_date: date, *, adjusted: bool) -> dict[str, Any]:
        results, attempts = self.get_daily_aggregates(symbol, start_date, end_date, adjusted=adjusted)
        return {"symbol": symbol, "bars": len(results), "attempts": attempts}


def download_symbol_rows(
    client: MassiveClient,
    entry: UniverseEntry,
    start_date: date,
    end_date: date,
    *,
    adjusted: bool,
) -> tuple[list[dict[str, str]], SymbolDownloadResult]:
    started = time.monotonic()
    try:
        aggregates, attempts = client.get_daily_aggregates(entry.symbol, start_date, end_date, adjusted=adjusted)
        rows = [aggregate_to_schema_row(item, entry) for item in aggregates]
        rows = merge_rows([], rows)
        status = "ok" if rows else "no_data"
        return rows, SymbolDownloadResult(
            ticker=entry.symbol,
            name=entry.name,
            status=status,
            bars_received=len(rows),
            attempts=attempts,
            elapsed_seconds=round(time.monotonic() - started, 3),
            local_symbol=entry.symbol,
            primary_exchange=entry.exchange,
        )
    except DownloadError as exc:
        return [], SymbolDownloadResult(
            ticker=entry.symbol,
            name=entry.name,
            status="failed",
            bars_received=0,
            attempts=0,
            elapsed_seconds=round(time.monotonic() - started, 3),
            local_symbol=entry.symbol,
            primary_exchange=entry.exchange,
            error=str(exc),
        )


def write_request_report(path: Path, results: list[SymbolDownloadResult]) -> None:
    rows = []
    for result in results:
        row = asdict(result)
        row["elapsed_seconds"] = f"{result.elapsed_seconds:.3f}"
        rows.append(row)
    write_csv_atomic(path, REQUEST_REPORT_FIELDS, rows)


def write_download_report(
    path: Path,
    *,
    stage: str,
    start_date: date,
    end_date: date,
    universe_count: int,
    results: list[SymbolDownloadResult],
    validation: ValidationResult,
    output_file: Path,
    backup_path: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    ok_results = [item for item in results if item.status == "ok"]
    failed_results = [item for item in results if item.status == "failed"]
    no_data_results = [item for item in results if item.status == "no_data"]
    report: dict[str, Any] = {
        "created_at_utc": utc_now_text(),
        "stage": stage,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "universe_count": universe_count,
        "symbols_ok": len(ok_results),
        "symbols_no_data": len(no_data_results),
        "symbols_failed": len(failed_results),
        "bars_downloaded": sum(item.bars_received for item in results),
        "validation": asdict(validation),
        "output_file": str(output_file),
        "backup_file": str(backup_path) if backup_path else "",
        "failed_symbols": [{"ticker": item.ticker, "error": item.error} for item in failed_results],
    }
    if extra:
        report.update(extra)
    _write_text_atomic(path, json.dumps(report, indent=2, sort_keys=True) + "\n")


def write_engine_universe(path: Path, entries: list[UniverseEntry]) -> None:
    rows = [
        {
            "symbol": entry.symbol,
            "name": entry.name,
            "source_symbol": entry.source_symbol,
            "exchange": entry.exchange,
            "currency": entry.currency,
            "sector": entry.sector,
        }
        for entry in entries
    ]
    write_csv_atomic(path, ["symbol", "name", "source_symbol", "exchange", "currency", "sector"], rows)


def write_symbol_files(daily_bars_dir: Path, schema: list[str], rows: list[dict[str, str]], symbols: Iterable[str]) -> int:
    daily_bars_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for symbol in symbols:
        symbol_rows = rows_for_symbol(rows, symbol)
        if not symbol_rows:
            continue
        write_csv_atomic(daily_bars_dir / f"{symbol}.csv", schema, symbol_rows)
        written += 1
    return written


def load_progress(path: Path, start_date: date, end_date: date, adjusted: bool) -> dict[str, Any]:
    if not path.exists():
        return {"completed_symbols": [], "failed_symbols": []}
    try:
        progress = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"completed_symbols": [], "failed_symbols": []}
    if progress.get("start_date") != start_date.isoformat():
        return {"completed_symbols": [], "failed_symbols": []}
    if progress.get("end_date") != end_date.isoformat():
        return {"completed_symbols": [], "failed_symbols": []}
    if bool(progress.get("adjusted", False)) != adjusted:
        return {"completed_symbols": [], "failed_symbols": []}
    return progress


def write_progress(
    path: Path,
    *,
    start_date: date,
    end_date: date,
    adjusted: bool,
    completed_symbols: set[str],
    failed_symbols: dict[str, str],
) -> None:
    payload = {
        "updated_at_utc": utc_now_text(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "adjusted": adjusted,
        "completed_symbols": sorted(completed_symbols),
        "failed_symbols": dict(sorted(failed_symbols.items())),
    }
    _write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def run_sample_validation(
    client: MassiveClient,
    entries: list[UniverseEntry],
    schema: list[str],
    *,
    sample_size: int,
    start_date: date,
    end_date: date,
    adjusted: bool,
    output_file: Path,
    request_report_file: Path,
    report_file: Path,
) -> tuple[bool, list[SymbolDownloadResult], ValidationResult]:
    sample_entries = entries[:sample_size]
    all_rows: list[dict[str, str]] = []
    results: list[SymbolDownloadResult] = []
    for entry in sample_entries:
        rows, result = download_symbol_rows(client, entry, start_date, end_date, adjusted=adjusted)
        all_rows.extend(rows)
        results.append(result)

    all_rows = merge_rows([], all_rows)
    validation = validate_rows_against_schema(all_rows, schema, sample_entries, start_date, end_date)
    if validation.passed:
        write_csv_atomic(output_file, schema, all_rows)
    write_request_report(request_report_file, results)
    write_download_report(
        report_file,
        stage="sample",
        start_date=start_date,
        end_date=end_date,
        universe_count=len(sample_entries),
        results=results,
        validation=validation,
        output_file=output_file,
    )
    return validation.passed, results, validation


def run_full_download(
    client: MassiveClient,
    entries: list[UniverseEntry],
    schema: list[str],
    *,
    start_date: date,
    end_date: date,
    adjusted: bool,
    output_file: Path,
    checkpoint_file: Path,
    request_report_file: Path,
    report_file: Path,
    progress_file: Path,
    daily_bars_dir: Path,
    engine_universe_file: Path,
    checkpoint_every: int,
) -> tuple[list[SymbolDownloadResult], ValidationResult, Path | None]:
    existing_rows = filter_rows_by_date_range(read_schema_rows(output_file, schema), start_date, end_date)
    checkpoint_rows = filter_rows_by_date_range(read_schema_rows(checkpoint_file, schema), start_date, end_date)
    merged_rows = merge_rows(existing_rows, checkpoint_rows)

    progress = load_progress(progress_file, start_date, end_date, adjusted)
    completed_symbols = set(progress.get("completed_symbols") or [])
    failed_symbols = dict(progress.get("failed_symbols") or {})
    symbols_with_rows = {str(row.get("ticker", "")).strip().upper() for row in merged_rows}
    completed_symbols = {symbol for symbol in completed_symbols if symbol in symbols_with_rows}

    results: list[SymbolDownloadResult] = []
    changed_since_checkpoint = 0
    for index, entry in enumerate(entries, start=1):
        if entry.symbol in completed_symbols:
            symbol_rows = rows_for_symbol(merged_rows, entry.symbol)
            results.append(
                SymbolDownloadResult(
                    ticker=entry.symbol,
                    name=entry.name,
                    status="ok",
                    bars_received=len(symbol_rows),
                    attempts=0,
                    elapsed_seconds=0.0,
                    local_symbol=entry.symbol,
                    primary_exchange=entry.exchange,
                )
            )
            continue

        rows, result = download_symbol_rows(client, entry, start_date, end_date, adjusted=adjusted)
        results.append(result)
        if result.status == "ok":
            merged_rows = merge_rows(merged_rows, rows)
            completed_symbols.add(entry.symbol)
            failed_symbols.pop(entry.symbol, None)
            write_symbol_files(daily_bars_dir, schema, merged_rows, [entry.symbol])
        elif result.status == "no_data":
            completed_symbols.add(entry.symbol)
            failed_symbols.pop(entry.symbol, None)
        else:
            failed_symbols[entry.symbol] = result.error
        changed_since_checkpoint += 1

        if changed_since_checkpoint >= checkpoint_every or index == len(entries):
            write_csv_atomic(checkpoint_file, schema, merged_rows)
            write_progress(
                progress_file,
                start_date=start_date,
                end_date=end_date,
                adjusted=adjusted,
                completed_symbols=completed_symbols,
                failed_symbols=failed_symbols,
            )
            changed_since_checkpoint = 0

    final_rows = merge_rows([], merged_rows)
    validation = validate_rows_against_schema(final_rows, schema, entries, start_date, end_date)

    backup_path = backup_file(output_file)
    write_csv_atomic(output_file, schema, final_rows)
    write_symbol_files(daily_bars_dir, schema, final_rows, [entry.symbol for entry in entries])
    write_engine_universe(engine_universe_file, entries)
    write_request_report(request_report_file, results)
    write_download_report(
        report_file,
        stage="full",
        start_date=start_date,
        end_date=end_date,
        universe_count=len(entries),
        results=results,
        validation=validation,
        output_file=output_file,
        backup_path=backup_path,
        extra={
            "daily_bars_dir": str(daily_bars_dir),
            "daily_bar_files_written": len([entry for entry in entries if rows_for_symbol(final_rows, entry.symbol)]),
            "engine_universe_file": str(engine_universe_file),
            "checkpoint_file": str(checkpoint_file),
            "progress_file": str(progress_file),
        },
    )
    if validation.passed and checkpoint_file.exists():
        checkpoint_file.unlink()
    return results, validation, backup_path


def _connection_window(end_date: date) -> tuple[date, date]:
    return max(end_date - timedelta(days=14), date(1970, 1, 1)), end_date


def build_parser() -> argparse.ArgumentParser:
    today = date.today()
    parser = argparse.ArgumentParser(description="Download Massive daily OHLCV data for TradingbotR1000")
    parser.add_argument("--full", action="store_true", help="run sample validation, then full universe download")
    parser.add_argument("--sample-only", action="store_true", help="run only sample validation")
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--start-date", type=parse_iso_date, default=default_start_date(today))
    parser.add_argument("--end-date", type=parse_iso_date, default=today)
    parser.add_argument("--adjusted", action="store_true", help="request adjusted bars from Massive")
    parser.add_argument("--api-base-url", default="https://api.massive.com")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--schema-file", type=Path, default=DEFAULT_SCHEMA_FILE)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--sample-output-file", type=Path, default=DEFAULT_SAMPLE_OUTPUT_FILE)
    parser.add_argument("--request-report-file", type=Path, default=DEFAULT_REQUEST_REPORT_FILE)
    parser.add_argument("--sample-request-report-file", type=Path, default=DEFAULT_SAMPLE_REQUEST_REPORT_FILE)
    parser.add_argument("--download-report-file", type=Path, default=DEFAULT_DOWNLOAD_REPORT_FILE)
    parser.add_argument("--sample-report-file", type=Path, default=DEFAULT_SAMPLE_REPORT_FILE)
    parser.add_argument("--progress-file", type=Path, default=DEFAULT_PROGRESS_FILE)
    parser.add_argument("--checkpoint-file", type=Path, default=DEFAULT_CHECKPOINT_FILE)
    parser.add_argument("--daily-bars-dir", type=Path, default=DEFAULT_DAILY_BARS_DIR)
    parser.add_argument("--engine-universe-file", type=Path, default=DEFAULT_ENGINE_UNIVERSE_FILE)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--backoff-seconds", type=float, default=2.0)
    parser.add_argument("--rate-limit-pause-seconds", type=float, default=0.25)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.sample_size < 1:
        parser.error("--sample-size must be at least 1")
    if args.checkpoint_every < 1:
        parser.error("--checkpoint-every must be at least 1")
    if args.start_date > args.end_date:
        parser.error("--start-date cannot be after --end-date")

    api_key = os.environ.get("MASSIVE_API_KEY", "")
    if not api_key.strip():
        print(
            json.dumps(
                {
                    "massive_api_key_present": False,
                    "process": "python",
                    "pid": os.getpid(),
                    "cwd": str(Path.cwd()),
                },
                indent=2,
            )
        )
        return 2

    schema = load_schema(args.schema_file)
    universe = load_iwb_universe(args.universe_file)
    sample_size = min(args.sample_size, len(universe))
    client = MassiveClient(
        api_key,
        base_url=args.api_base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        backoff_seconds=args.backoff_seconds,
        rate_limit_pause_seconds=args.rate_limit_pause_seconds,
    )

    connection_start, connection_end = _connection_window(args.end_date)
    try:
        connection = client.validate_connection(universe[0].symbol, connection_start, connection_end, adjusted=args.adjusted)
    except DownloadError as exc:
        print(json.dumps({"stage": "api_connection", "ok": False, "error": str(exc)}, indent=2))
        return 5
    print(json.dumps({"stage": "api_connection", "ok": True, **connection}, indent=2))

    sample_ok, sample_results, sample_validation = run_sample_validation(
        client,
        universe,
        schema,
        sample_size=sample_size,
        start_date=args.start_date,
        end_date=args.end_date,
        adjusted=args.adjusted,
        output_file=args.sample_output_file,
        request_report_file=args.sample_request_report_file,
        report_file=args.sample_report_file,
    )
    print(
        json.dumps(
            {
                "stage": "sample",
                "ok": sample_ok,
                "symbols": sample_size,
                "bars": sum(item.bars_received for item in sample_results),
                "validation": asdict(sample_validation),
            },
            indent=2,
        )
    )
    if not sample_ok:
        return 3
    if args.sample_only or not args.full:
        return 0

    full_results, full_validation, backup_path = run_full_download(
        client,
        universe,
        schema,
        start_date=args.start_date,
        end_date=args.end_date,
        adjusted=args.adjusted,
        output_file=args.output_file,
        checkpoint_file=args.checkpoint_file,
        request_report_file=args.request_report_file,
        report_file=args.download_report_file,
        progress_file=args.progress_file,
        daily_bars_dir=args.daily_bars_dir,
        engine_universe_file=args.engine_universe_file,
        checkpoint_every=args.checkpoint_every,
    )
    print(
        json.dumps(
            {
                "stage": "full",
                "ok": full_validation.passed,
                "symbols": len(universe),
                "symbols_ok": len([item for item in full_results if item.status == "ok"]),
                "symbols_no_data": len([item for item in full_results if item.status == "no_data"]),
                "symbols_failed": len([item for item in full_results if item.status == "failed"]),
                "bars": sum(item.bars_received for item in full_results),
                "backup_file": str(backup_path) if backup_path else "",
                "validation": asdict(full_validation),
            },
            indent=2,
        )
    )
    return 0 if full_validation.passed else 4


if __name__ == "__main__":
    raise SystemExit(main())

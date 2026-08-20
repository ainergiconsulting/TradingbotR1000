"""One-time Massive corporate-action collector for TradingbotR1000.

This tool is for the historical correction phase only. It does not download
OHLCV bars and is not part of normal production operation after correction.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from current_reference.PaperTradingR1000.massive_historical_downloader import (  # noqa: E402
    DEFAULT_UNIVERSE_FILE,
    DownloadError,
    UniverseEntry,
    load_iwb_universe,
    normalize_symbol,
    write_csv_atomic,
)

RESULTS_DIR = PROJECT_ROOT / "ibkr_r1000_results"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "source" / "massive"
CORPORATE_ACTION_ROOT = OUTPUT_ROOT / "corporate_actions"
REFERENCE_ROOT = OUTPUT_ROOT / "reference"
BY_SYMBOL_ROOT = CORPORATE_ACTION_ROOT / "by_symbol"
CHECKPOINT_FILE = RESULTS_DIR / "massive_corporate_actions_checkpoint.json"
REPORT_FILE = RESULTS_DIR / "massive_corporate_actions_report.json"
FAILED_FILE = RESULTS_DIR / "massive_corporate_actions_failed_symbols.csv"
LOG_FILE = RESULTS_DIR / "massive_corporate_actions.log"

SPLIT_FIELDS = [
    "source_symbol",
    "canonical_symbol",
    "event_class",
    "execution_date",
    "split_from",
    "split_to",
    "ratio",
    "adjustment_type",
    "historical_adjustment_factor",
    "raw_json",
]

DIVIDEND_FIELDS = [
    "source_symbol",
    "canonical_symbol",
    "event_class",
    "ex_dividend_date",
    "declaration_date",
    "record_date",
    "pay_date",
    "cash_amount",
    "split_adjusted_cash_amount",
    "currency",
    "dividend_type",
    "frequency",
    "historical_adjustment_factor",
    "raw_json",
]

TICKER_DETAIL_FIELDS = [
    "source_symbol",
    "canonical_symbol",
    "massive_ticker",
    "name",
    "market",
    "locale",
    "primary_exchange",
    "currency_name",
    "active",
    "list_date",
    "delisted_utc",
    "cik",
    "composite_figi",
    "share_class_figi",
    "raw_json",
]

TICKER_EVENT_FIELDS = [
    "source_symbol",
    "canonical_symbol",
    "event_class",
    "event_date",
    "event_type",
    "ticker",
    "name",
    "composite_figi",
    "share_class_figi",
    "cik",
    "raw_json",
]

EVENT_CAPABILITY_FIELDS = [
    "event_class",
    "source",
    "initial_support",
    "notes",
]

RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def print_progress(message: str, **fields: Any) -> None:
    payload = {"timestamp_utc": utc_now_text(), "message": message, **fields}
    print(json.dumps(payload, sort_keys=True), flush=True)


def append_log(log_path: Path, message: str, **fields: Any) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp_utc": utc_now_text(), "message": message, **fields}
    with log_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_event_key(row: dict[str, Any], fields: Iterable[str]) -> tuple[str, ...]:
    return tuple(str(row.get(field, "")).strip() for field in fields)


def dedupe_rows(rows: Iterable[dict[str, Any]], key_fields: Iterable[str]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = stable_event_key(row, key_fields)
        if any(key):
            by_key[key] = dict(row)
    return [by_key[key] for key in sorted(by_key)]


class MassiveReferenceClient:
    """Small Massive REST client for reference and corporate-action endpoints."""

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
            raise DownloadError("MASSIVE_API_KEY is not available in this Python process")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.rate_limit_pause_seconds = rate_limit_pause_seconds

    def request_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self._build_url(path_or_url, params or {})
        for attempt in range(1, self.max_retries + 2):
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "TradingbotR1000/1.0"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if self.rate_limit_pause_seconds > 0:
                    time.sleep(self.rate_limit_pause_seconds)
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRYABLE_HTTP_STATUS or attempt > self.max_retries:
                    raise DownloadError(f"Massive request failed: HTTP {exc.code} for {self._safe_url(url)}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else self.backoff_seconds * (2 ** (attempt - 1))
                print_progress("massive_retry", status=exc.code, attempt=attempt, delay_seconds=delay)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt > self.max_retries:
                    raise DownloadError(f"Massive request failed: {exc.__class__.__name__} for {self._safe_url(url)}") from exc
                delay = self.backoff_seconds * (2 ** (attempt - 1))
                print_progress("massive_retry", status=exc.__class__.__name__, attempt=attempt, delay_seconds=delay)
                time.sleep(delay)
        raise DownloadError(f"Massive request failed for {self._safe_url(url)}")

    def paged_results(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = self.request_json(path, params)
        results = list(payload.get("results") or [])
        next_url = payload.get("next_url")
        while isinstance(next_url, str) and next_url.strip():
            payload = self.request_json(next_url)
            results.extend(payload.get("results") or [])
            next_url = payload.get("next_url")
        return [item for item in results if isinstance(item, dict)]

    def _build_url(self, path_or_url: str, params: dict[str, Any]) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            parsed = urllib.parse.urlparse(path_or_url)
            query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            query.setdefault("apiKey", self.api_key)
            return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
        query = {key: value for key, value in params.items() if value not in (None, "")}
        query["apiKey"] = self.api_key
        return self.base_url + path_or_url + "?" + urllib.parse.urlencode(query)

    @staticmethod
    def _safe_url(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        if "apiKey" in query:
            query["apiKey"] = "***"
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def target_entries(entries: list[UniverseEntry], symbols: str | None, limit: int | None) -> list[UniverseEntry]:
    if symbols:
        requested = [normalize_symbol(item.strip()) for item in symbols.split(",") if item.strip()]
        requested_set = set(requested)
        entries = [entry for entry in entries if entry.symbol in requested_set]
        missing = sorted(requested_set - {entry.symbol for entry in entries})
        if missing:
            raise DownloadError(f"requested symbols are not in the IWB universe: {','.join(missing)}")
    if limit is not None:
        entries = entries[: max(limit, 0)]
    return entries


def checkpoint_sets(path: Path) -> tuple[set[str], dict[str, str]]:
    payload = read_json(path)
    completed = {normalize_symbol(str(symbol)) for symbol in payload.get("completed_symbols") or []}
    failed = {
        normalize_symbol(str(symbol)): str(error)
        for symbol, error in (payload.get("failed_symbols") or {}).items()
    }
    return completed, failed


def save_checkpoint(path: Path, completed: set[str], failed: dict[str, str], targets: list[str]) -> None:
    write_json_atomic(
        path,
        {
            "updated_at_utc": utc_now_text(),
            "purpose": "one_time_historical_correction_corporate_actions",
            "normal_operation_dependency": False,
            "completed_symbols": sorted(completed),
            "failed_symbols": dict(sorted(failed.items())),
            "target_symbols": sorted(targets),
        },
    )


def collect_symbol_payload(
    client: MassiveReferenceClient,
    entry: UniverseEntry,
    *,
    start_date: date,
    end_date: date,
    include_ticker_events: bool,
) -> dict[str, Any]:
    symbol = entry.symbol
    quoted = urllib.parse.quote(symbol, safe="")
    split_params = {
        "ticker": symbol,
        "execution_date.gte": start_date.isoformat(),
        "execution_date.lte": end_date.isoformat(),
        "limit": 1000,
        "sort": "execution_date",
        "order": "asc",
    }
    dividend_params = {
        "ticker": symbol,
        "ex_dividend_date.gte": start_date.isoformat(),
        "ex_dividend_date.lte": end_date.isoformat(),
        "limit": 1000,
        "sort": "ex_dividend_date",
        "order": "asc",
    }
    payload: dict[str, Any] = {
        "source_symbol": entry.source_symbol,
        "canonical_symbol": symbol,
        "name": entry.name,
        "collected_at_utc": utc_now_text(),
        "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "splits": client.paged_results("/stocks/v1/splits", split_params),
        "dividends": client.paged_results("/stocks/v1/dividends", dividend_params),
        "ticker_details": client.request_json(f"/v3/reference/tickers/{quoted}"),
        "ticker_events": {},
    }
    if include_ticker_events:
        try:
            payload["ticker_events"] = client.request_json(f"/vX/reference/tickers/{quoted}/events")
        except DownloadError as exc:
            payload["ticker_events"] = {"error": str(exc)}
    return payload


def save_symbol_payload(entry: UniverseEntry, payload: dict[str, Any], output_root: Path) -> Path:
    path = output_root / f"{entry.symbol}.json"
    write_json_atomic(path, payload)
    return path


def read_symbol_payloads(by_symbol_root: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if not by_symbol_root.exists():
        return payloads
    for path in sorted(by_symbol_root.glob("*.json")):
        payload = read_json(path)
        if payload:
            payloads.append(payload)
    return payloads


def event_class_for_split(raw: dict[str, Any]) -> str:
    try:
        split_from = float(raw.get("split_from", 0) or 0)
        split_to = float(raw.get("split_to", 0) or 0)
    except (TypeError, ValueError):
        return "split"
    if split_from <= 0 or split_to <= 0:
        return "split"
    return "forward_split" if split_to > split_from else "reverse_split"


def split_row(payload: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    split_from = raw.get("split_from", "")
    split_to = raw.get("split_to", "")
    ratio = ""
    try:
        if float(split_from) != 0:
            ratio = float(split_to) / float(split_from)
    except (TypeError, ValueError):
        ratio = ""
    return {
        "source_symbol": payload.get("source_symbol", ""),
        "canonical_symbol": payload.get("canonical_symbol", ""),
        "event_class": event_class_for_split(raw),
        "execution_date": raw.get("execution_date", ""),
        "split_from": split_from,
        "split_to": split_to,
        "ratio": ratio,
        "adjustment_type": raw.get("adjustment_type", ""),
        "historical_adjustment_factor": raw.get("historical_adjustment_factor", ""),
        "raw_json": compact_json(raw),
    }


def dividend_row(payload: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_symbol": payload.get("source_symbol", ""),
        "canonical_symbol": payload.get("canonical_symbol", ""),
        "event_class": "cash_dividend",
        "ex_dividend_date": raw.get("ex_dividend_date", ""),
        "declaration_date": raw.get("declaration_date", ""),
        "record_date": raw.get("record_date", ""),
        "pay_date": raw.get("pay_date", ""),
        "cash_amount": raw.get("cash_amount", ""),
        "split_adjusted_cash_amount": raw.get("split_adjusted_cash_amount", ""),
        "currency": raw.get("currency", ""),
        "dividend_type": raw.get("dividend_type", ""),
        "frequency": raw.get("frequency", ""),
        "historical_adjustment_factor": raw.get("historical_adjustment_factor", ""),
        "raw_json": compact_json(raw),
    }


def ticker_detail_row(payload: dict[str, Any]) -> dict[str, Any]:
    details_payload = payload.get("ticker_details") or {}
    details = details_payload.get("results") if isinstance(details_payload, dict) else {}
    if not isinstance(details, dict):
        details = {}
    return {
        "source_symbol": payload.get("source_symbol", ""),
        "canonical_symbol": payload.get("canonical_symbol", ""),
        "massive_ticker": details.get("ticker", ""),
        "name": details.get("name", ""),
        "market": details.get("market", ""),
        "locale": details.get("locale", ""),
        "primary_exchange": details.get("primary_exchange", ""),
        "currency_name": details.get("currency_name", ""),
        "active": details.get("active", ""),
        "list_date": details.get("list_date", ""),
        "delisted_utc": details.get("delisted_utc", ""),
        "cik": details.get("cik", ""),
        "composite_figi": details.get("composite_figi", ""),
        "share_class_figi": details.get("share_class_figi", ""),
        "raw_json": compact_json(details),
    }


def flatten_ticker_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    event_payload = payload.get("ticker_events") or {}
    if not isinstance(event_payload, dict) or event_payload.get("error"):
        return []
    results = event_payload.get("results")
    if isinstance(results, dict):
        events = results.get("events") or []
    elif isinstance(results, list):
        events = results
    else:
        events = []
    rows: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "source_symbol": payload.get("source_symbol", ""),
                "canonical_symbol": payload.get("canonical_symbol", ""),
                "event_class": raw.get("type", raw.get("event_type", "ticker_event")),
                "event_date": raw.get("date", raw.get("event_date", "")),
                "event_type": raw.get("type", raw.get("event_type", "")),
                "ticker": raw.get("ticker", ""),
                "name": raw.get("name", ""),
                "composite_figi": raw.get("composite_figi", ""),
                "share_class_figi": raw.get("share_class_figi", ""),
                "cik": raw.get("cik", ""),
                "raw_json": compact_json(raw),
            }
        )
    return rows


def event_capability_rows() -> list[dict[str, str]]:
    return [
        {"event_class": "forward_split", "source": "Massive splits", "initial_support": "yes", "notes": "Derived from split_to > split_from."},
        {"event_class": "reverse_split", "source": "Massive splits", "initial_support": "yes", "notes": "Derived from split_to < split_from."},
        {"event_class": "cash_dividend", "source": "Massive dividends", "initial_support": "yes", "notes": "Cash and split-adjusted cash amounts are stored when supplied."},
        {"event_class": "stock_dividend", "source": "future source or manual curation", "initial_support": "schema_only", "notes": "Architecture can record the event class, but current Massive dividend output may not identify all stock dividends."},
        {"event_class": "ticker_change", "source": "Massive ticker events", "initial_support": "best_effort", "notes": "Experimental endpoint; unavailable events are recorded as missing rather than inferred."},
        {"event_class": "merger", "source": "future source or manual curation", "initial_support": "schema_only", "notes": "No automatic predecessor history combination."},
        {"event_class": "acquisition", "source": "future source or manual curation", "initial_support": "schema_only", "notes": "No automatic predecessor history combination."},
        {"event_class": "spin_off", "source": "future source or manual curation", "initial_support": "schema_only", "notes": "No automatic predecessor history combination."},
        {"event_class": "delisting", "source": "Massive ticker details or future source", "initial_support": "best_effort", "notes": "Stored when delisted metadata is available."},
    ]


def consolidate_payloads(payloads: list[dict[str, Any]], output_root: Path) -> dict[str, int]:
    split_rows: list[dict[str, Any]] = []
    dividend_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []

    for payload in payloads:
        for raw in payload.get("splits") or []:
            if isinstance(raw, dict):
                split_rows.append(split_row(payload, raw))
        for raw in payload.get("dividends") or []:
            if isinstance(raw, dict):
                dividend_rows.append(dividend_row(payload, raw))
        detail_rows.append(ticker_detail_row(payload))
        event_rows.extend(flatten_ticker_events(payload))

    split_rows = dedupe_rows(split_rows, ["canonical_symbol", "execution_date", "split_from", "split_to"])
    dividend_rows = dedupe_rows(dividend_rows, ["canonical_symbol", "ex_dividend_date", "cash_amount", "dividend_type"])
    detail_rows = dedupe_rows(detail_rows, ["canonical_symbol"])
    event_rows = dedupe_rows(event_rows, ["canonical_symbol", "event_date", "event_type", "ticker", "name"])

    corporate_dir = output_root / "corporate_actions"
    reference_dir = output_root / "reference"
    write_csv_atomic(corporate_dir / "splits.csv", SPLIT_FIELDS, split_rows)
    write_csv_atomic(corporate_dir / "dividends.csv", DIVIDEND_FIELDS, dividend_rows)
    write_csv_atomic(corporate_dir / "ticker_events.csv", TICKER_EVENT_FIELDS, event_rows)
    write_csv_atomic(corporate_dir / "event_capabilities.csv", EVENT_CAPABILITY_FIELDS, event_capability_rows())
    write_csv_atomic(reference_dir / "ticker_details.csv", TICKER_DETAIL_FIELDS, detail_rows)

    return {
        "symbols": len(payloads),
        "splits": len(split_rows),
        "dividends": len(dividend_rows),
        "ticker_details": len(detail_rows),
        "ticker_events": len(event_rows),
    }


def validate_outputs(output_root: Path) -> tuple[bool, dict[str, Any]]:
    checks: dict[str, Any] = {}
    files = {
        "splits": (output_root / "corporate_actions" / "splits.csv", SPLIT_FIELDS, ["canonical_symbol", "execution_date", "split_from", "split_to"]),
        "dividends": (output_root / "corporate_actions" / "dividends.csv", DIVIDEND_FIELDS, ["canonical_symbol", "ex_dividend_date", "cash_amount", "dividend_type"]),
        "ticker_events": (output_root / "corporate_actions" / "ticker_events.csv", TICKER_EVENT_FIELDS, ["canonical_symbol", "event_date", "event_type", "ticker", "name"]),
        "event_capabilities": (output_root / "corporate_actions" / "event_capabilities.csv", EVENT_CAPABILITY_FIELDS, ["event_class"]),
        "ticker_details": (output_root / "reference" / "ticker_details.csv", TICKER_DETAIL_FIELDS, ["canonical_symbol"]),
    }
    ok = True
    for name, (path, expected_fields, key_fields) in files.items():
        file_ok = path.exists()
        rows = 0
        duplicates = 0
        schema_ok = False
        if file_ok:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                schema_ok = reader.fieldnames == expected_fields
                seen: set[tuple[str, ...]] = set()
                for row in reader:
                    rows += 1
                    key = stable_event_key(row, key_fields)
                    if key in seen:
                        duplicates += 1
                    seen.add(key)
        file_ok = file_ok and schema_ok and duplicates == 0
        ok = ok and file_ok
        checks[name] = {
            "path": str(path),
            "exists": path.exists(),
            "schema_ok": schema_ok,
            "rows": rows,
            "duplicates": duplicates,
            "ok": file_ok,
        }
    return ok, checks


def write_failed_report(failed: dict[str, str], path: Path) -> None:
    rows = [{"symbol": symbol, "error": failed[symbol]} for symbol in sorted(failed)]
    write_csv_atomic(path, ["symbol", "error"], rows)


def run_collection(args: argparse.Namespace) -> int:
    entries = load_iwb_universe(args.universe_file)
    selected = target_entries(entries, args.symbols, args.max_symbols)
    targets = [entry.symbol for entry in selected]

    if args.dry_run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "massive_api_key_present": bool(os.environ.get("MASSIVE_API_KEY", "").strip()),
                    "universe_symbols": len(entries),
                    "target_symbols": targets,
                    "output_root": str(args.output_root),
                    "downloads_ohlcv": False,
                    "normal_operation_dependency": False,
                },
                indent=2,
            )
        )
        return 0

    if args.consolidate_only:
        payloads = read_symbol_payloads(args.by_symbol_root)
        counts = consolidate_payloads(payloads, args.output_root)
        ok, checks = validate_outputs(args.output_root)
        write_json_atomic(args.report_file, {"updated_at_utc": utc_now_text(), "mode": "consolidate_only", "counts": counts, "validation": checks, "ok": ok})
        print(json.dumps({"mode": "consolidate_only", "ok": ok, "counts": counts}, indent=2))
        return 0 if ok else 4

    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
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

    completed, failed = checkpoint_sets(args.checkpoint_file)
    if args.force:
        completed -= set(targets)

    client = MassiveReferenceClient(
        api_key,
        base_url=args.api_base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        backoff_seconds=args.backoff_seconds,
        rate_limit_pause_seconds=args.rate_limit_pause_seconds,
    )

    print_progress("corporate_action_collection_start", targets=len(targets), output_root=str(args.output_root))
    append_log(args.log_file, "corporate_action_collection_start", targets=len(targets), output_root=str(args.output_root))

    for index, entry in enumerate(selected, start=1):
        if entry.symbol in completed and (args.by_symbol_root / f"{entry.symbol}.json").exists():
            print_progress("symbol_skipped_checkpoint_complete", symbol=entry.symbol, index=index, total=len(selected))
            continue
        try:
            print_progress("symbol_collection_start", symbol=entry.symbol, index=index, total=len(selected))
            payload = collect_symbol_payload(
                client,
                entry,
                start_date=args.start_date,
                end_date=args.end_date,
                include_ticker_events=not args.skip_ticker_events,
            )
            path = save_symbol_payload(entry, payload, args.by_symbol_root)
            completed.add(entry.symbol)
            failed.pop(entry.symbol, None)
            save_checkpoint(args.checkpoint_file, completed, failed, targets)
            append_log(args.log_file, "symbol_collection_complete", symbol=entry.symbol, path=str(path))
            print_progress(
                "symbol_collection_complete",
                symbol=entry.symbol,
                splits=len(payload.get("splits") or []),
                dividends=len(payload.get("dividends") or []),
                path=str(path),
            )
        except DownloadError as exc:
            failed[entry.symbol] = str(exc)
            save_checkpoint(args.checkpoint_file, completed, failed, targets)
            write_failed_report(failed, args.failed_file)
            append_log(args.log_file, "symbol_collection_failed", symbol=entry.symbol, error=str(exc))
            print_progress("symbol_collection_failed", symbol=entry.symbol, error=str(exc))
            if args.stop_on_error:
                break

    payloads = read_symbol_payloads(args.by_symbol_root)
    counts = consolidate_payloads(payloads, args.output_root)
    write_failed_report(failed, args.failed_file)
    ok, checks = validate_outputs(args.output_root)
    report = {
        "updated_at_utc": utc_now_text(),
        "mode": "collection",
        "normal_operation_dependency": False,
        "downloads_ohlcv": False,
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        "target_symbols": targets,
        "completed_symbols": sorted(completed & set(targets)),
        "failed_symbols": dict(sorted((symbol, failed[symbol]) for symbol in failed if symbol in set(targets))),
        "counts": counts,
        "validation": checks,
        "ok": ok and not any(symbol in failed for symbol in targets),
    }
    write_json_atomic(args.report_file, report)
    print(json.dumps({"stage": "corporate_actions", "ok": report["ok"], "counts": counts, "failed": len(report["failed_symbols"])}, indent=2))
    return 0 if report["ok"] else 5


def build_parser() -> argparse.ArgumentParser:
    today = date.today()
    parser = argparse.ArgumentParser(description="Collect Massive corporate actions for one-time TradingbotR1000 historical correction")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="show planned targets and outputs without API requests")
    mode.add_argument("--sample", action="store_true", help="collect a small sample from the current universe")
    mode.add_argument("--full", action="store_true", help="collect all current-universe corporate actions")
    mode.add_argument("--consolidate-only", action="store_true", help="rebuild consolidated CSVs from existing per-symbol JSON payloads")
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--symbols", help="comma-separated symbols; overrides sample selection")
    parser.add_argument("--max-symbols", type=int)
    parser.add_argument("--start-date", type=parse_iso_date, default=date(today.year - 10, today.month, min(today.day, 28)))
    parser.add_argument("--end-date", type=parse_iso_date, default=today)
    parser.add_argument("--api-base-url", default="https://api.massive.com")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--by-symbol-root", type=Path, default=BY_SYMBOL_ROOT)
    parser.add_argument("--checkpoint-file", type=Path, default=CHECKPOINT_FILE)
    parser.add_argument("--report-file", type=Path, default=REPORT_FILE)
    parser.add_argument("--failed-file", type=Path, default=FAILED_FILE)
    parser.add_argument("--log-file", type=Path, default=LOG_FILE)
    parser.add_argument("--skip-ticker-events", action="store_true", help="skip experimental ticker-events endpoint")
    parser.add_argument("--force", action="store_true", help="recollect selected symbols even if checkpoint says complete")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--backoff-seconds", type=float, default=2.0)
    parser.add_argument("--rate-limit-pause-seconds", type=float, default=0.25)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start_date > args.end_date:
        parser.error("--start-date cannot be after --end-date")
    if args.sample and not args.symbols:
        args.max_symbols = args.sample_size
    if args.full and args.max_symbols is not None:
        parser.error("--full cannot be combined with --max-symbols")
    if args.sample_size < 1:
        parser.error("--sample-size must be at least 1")
    return run_collection(args)


if __name__ == "__main__":
    raise SystemExit(main())

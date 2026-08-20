"""Validate local historical bars against collected corporate actions.

This implements the Phase A2.5 validation design without changing raw market
data or production runtime behavior.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from current_reference.PaperTradingR1000.massive_historical_downloader import (  # noqa: E402
    DEFAULT_DAILY_BARS_DIR,
    DEFAULT_UNIVERSE_FILE,
    DownloadError,
    UniverseEntry,
    load_iwb_universe,
    normalize_symbol,
    write_csv_atomic,
)

RESULTS_DIR = PROJECT_ROOT / "data" / "validation" / "historical_corporate_actions"
SPLITS_FILE = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "splits.csv"
DIVIDENDS_FILE = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "dividends.csv"
TICKER_EVENTS_FILE = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "ticker_events.csv"
TICKER_DETAILS_FILE = PROJECT_ROOT / "data" / "source" / "massive" / "reference" / "ticker_details.csv"
COLLECTION_REPORT_FILE = PROJECT_ROOT / "ibkr_r1000_results" / "massive_corporate_actions_report.json"
SYMBOL_COMPATIBILITY_REPORT = PROJECT_ROOT / "ibkr_r1000_results" / "symbol_compatibility_validation_report.json"

SYMBOL_REPORT_FIELDS = [
    "symbol",
    "status",
    "reason",
    "rows",
    "first_date",
    "last_date",
    "missing_dates",
    "duplicate_dates",
    "duplicate_bars",
    "invalid_dates",
    "missing_required_fields",
    "invalid_prices",
    "invalid_ohlc",
    "invalid_volume",
    "inconsistent_identifiers",
    "splits",
    "dividends",
    "ticker_events",
    "split_consistent",
    "split_possible_already_adjusted",
    "split_inconsistent",
    "split_not_observable",
    "suspicious_gaps",
    "unexplained_suspicious_gaps",
    "blocking_issues",
    "warning_issues",
]

SPLIT_REPORT_FIELDS = [
    "symbol",
    "execution_date",
    "event_class",
    "split_from",
    "split_to",
    "expected_price_ratio",
    "pre_date",
    "pre_close",
    "post_date",
    "post_open",
    "observed_gap_ratio",
    "split_gap_residual",
    "local_median_abs_gap",
    "classification",
    "blocking",
]

GAP_REPORT_FIELDS = [
    "symbol",
    "prior_date",
    "current_date",
    "prior_close",
    "current_open",
    "raw_gap_ratio",
    "local_median_abs_gap",
    "classification",
    "nearby_events",
]


@dataclass(frozen=True)
class Bar:
    date_text: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    ticker: str
    local_symbol: str
    raw: dict[str, str]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_yyyymmdd(value: str) -> date | None:
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def parse_iso_date(value: str) -> date | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


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


def print_progress(message: str, **fields: Any) -> None:
    print(json.dumps({"timestamp_utc": utc_now_text(), "message": message, **fields}, sort_keys=True), flush=True)


def load_known_exclusions(path: Path) -> dict[str, str]:
    payload = read_json(path)
    exclusions: dict[str, str] = {}
    for item in payload.get("excluded_symbols") or []:
        if isinstance(item, dict):
            symbol = normalize_symbol(str(item.get("symbol") or item.get("source_symbol") or ""))
            if symbol:
                exclusions[symbol] = str(item.get("reason") or "known_exclusion")
    return exclusions


def group_by_symbol(rows: Iterable[dict[str, str]], symbol_field: str = "canonical_symbol") -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        symbol = normalize_symbol(str(row.get(symbol_field, "")))
        if symbol:
            grouped[symbol].append(row)
    return grouped


def read_bars(path: Path, symbol: str) -> tuple[list[Bar], dict[str, int]]:
    counts = {
        "invalid_dates": 0,
        "missing_required_fields": 0,
        "invalid_prices": 0,
        "invalid_ohlc": 0,
        "invalid_volume": 0,
        "inconsistent_identifiers": 0,
    }
    required = {"ticker", "date", "open", "high", "low", "close", "volume"}
    bars: list[Bar] = []
    if not path.exists():
        return bars, counts
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        if required - fieldnames:
            counts["missing_required_fields"] += 1
            return bars, counts
        for row in reader:
            if any(str(row.get(field, "")).strip() == "" for field in required):
                counts["missing_required_fields"] += 1
                continue
            parsed_date = parse_yyyymmdd(row.get("date", ""))
            if parsed_date is None:
                counts["invalid_dates"] += 1
                continue
            values = {field: parse_float(row.get(field)) for field in ("open", "high", "low", "close", "volume")}
            if any(values[field] is None for field in ("open", "high", "low", "close")):
                counts["invalid_prices"] += 1
                continue
            if values["volume"] is None:
                counts["invalid_volume"] += 1
                continue
            open_price = float(values["open"])
            high = float(values["high"])
            low = float(values["low"])
            close = float(values["close"])
            volume = float(values["volume"])
            if min(open_price, high, low, close) <= 0:
                counts["invalid_prices"] += 1
            if high < low or open_price < low or open_price > high or close < low or close > high:
                counts["invalid_ohlc"] += 1
            if volume < 0:
                counts["invalid_volume"] += 1
            ticker = normalize_symbol(str(row.get("ticker", "")))
            local_symbol = normalize_symbol(str(row.get("local_symbol", row.get("ticker", ""))))
            if ticker != symbol or local_symbol != symbol:
                counts["inconsistent_identifiers"] += 1
            bars.append(
                Bar(
                    date_text=str(row.get("date", "")).strip(),
                    day=parsed_date,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    ticker=ticker,
                    local_symbol=local_symbol,
                    raw=dict(row),
                )
            )
    bars.sort(key=lambda item: item.day)
    return bars, counts


def build_market_calendar(entries: list[UniverseEntry], daily_bars_dir: Path) -> list[date]:
    dates: set[date] = set()
    for entry in entries:
        path = daily_bars_dir / f"{entry.symbol}.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                parsed = parse_yyyymmdd(row.get("date", ""))
                if parsed is not None:
                    dates.add(parsed)
    return sorted(dates)


def duplicate_counts(bars: list[Bar]) -> tuple[int, int]:
    by_date: dict[str, list[Bar]] = defaultdict(list)
    for bar in bars:
        by_date[bar.date_text].append(bar)
    duplicate_dates = sum(1 for rows in by_date.values() if len(rows) > 1)
    duplicate_bars = 0
    for rows in by_date.values():
        seen: set[tuple[float, float, float, float, float]] = set()
        for bar in rows:
            key = (bar.open, bar.high, bar.low, bar.close, bar.volume)
            if key in seen:
                duplicate_bars += 1
            seen.add(key)
    return duplicate_dates, duplicate_bars


def missing_dates_count(bars: list[Bar], market_calendar: list[date]) -> int:
    if len(bars) < 2:
        return 0
    available = {bar.day for bar in bars}
    first = bars[0].day
    last = bars[-1].day
    return sum(1 for day in market_calendar if first <= day <= last and day not in available)


def median_abs_gap(bars: list[Bar], index: int, window: int = 20) -> float:
    values: list[float] = []
    start = max(1, index - window)
    end = min(len(bars), index + window + 1)
    for offset in range(start, end):
        prior = bars[offset - 1]
        current = bars[offset]
        if prior.close > 0 and current.open > 0:
            values.append(abs(math.log(current.open / prior.close)))
    if not values:
        return 0.0
    return statistics.median(values)


def event_class_for_split(row: dict[str, str]) -> str:
    split_from = parse_float(row.get("split_from"))
    split_to = parse_float(row.get("split_to"))
    if split_from is None or split_to is None or split_from <= 0 or split_to <= 0:
        return "split"
    return "forward_split" if split_to > split_from else "reverse_split"


def classify_split_event(bars: list[Bar], row: dict[str, str]) -> dict[str, Any]:
    execution_date = parse_iso_date(row.get("execution_date", ""))
    split_from = parse_float(row.get("split_from"))
    split_to = parse_float(row.get("split_to"))
    if execution_date is None or split_from is None or split_to is None or split_from <= 0 or split_to <= 0:
        return {
            "classification": "invalid_split_event",
            "blocking": True,
            "expected_price_ratio": "",
            "pre_date": "",
            "pre_close": "",
            "post_date": "",
            "post_open": "",
            "observed_gap_ratio": "",
            "split_gap_residual": "",
            "local_median_abs_gap": "",
        }
    pre_candidates = [bar for bar in bars if bar.day < execution_date]
    post_candidates = [bar for bar in bars if bar.day >= execution_date]
    if not pre_candidates or not post_candidates:
        return {
            "classification": "not_observable",
            "blocking": False,
            "expected_price_ratio": split_from / split_to,
            "pre_date": "",
            "pre_close": "",
            "post_date": "",
            "post_open": "",
            "observed_gap_ratio": "",
            "split_gap_residual": "",
            "local_median_abs_gap": "",
        }
    pre = pre_candidates[-1]
    post = post_candidates[0]
    post_index = bars.index(post)
    local_median = median_abs_gap(bars, post_index)
    expected_ratio = split_from / split_to
    observed_ratio = post.open / pre.close if pre.close > 0 else 0.0
    residual = observed_ratio / expected_ratio if expected_ratio > 0 else 0.0
    consistent_threshold = max(0.20, 5 * local_median)
    already_adjusted_threshold = max(0.10, 3 * local_median)
    material_split = abs(math.log(expected_ratio)) > 0.20
    if residual > 0 and abs(math.log(residual)) <= consistent_threshold:
        classification = "raw_split_consistent"
        blocking = False
    elif observed_ratio > 0 and material_split and abs(math.log(observed_ratio)) <= already_adjusted_threshold:
        classification = "possible_already_adjusted"
        blocking = True
    else:
        classification = "split_gap_inconsistent"
        blocking = True
    return {
        "classification": classification,
        "blocking": blocking,
        "expected_price_ratio": expected_ratio,
        "pre_date": pre.day.isoformat(),
        "pre_close": pre.close,
        "post_date": post.day.isoformat(),
        "post_open": post.open,
        "observed_gap_ratio": observed_ratio,
        "split_gap_residual": residual,
        "local_median_abs_gap": local_median,
    }


def event_dates_for_symbol(
    split_rows: list[dict[str, str]],
    ticker_event_rows: list[dict[str, str]],
) -> list[tuple[date, str]]:
    events: list[tuple[date, str]] = []
    for row in split_rows:
        parsed = parse_iso_date(row.get("execution_date", ""))
        if parsed is not None:
            events.append((parsed, event_class_for_split(row)))
    for row in ticker_event_rows:
        parsed = parse_iso_date(row.get("event_date", ""))
        if parsed is not None:
            events.append((parsed, str(row.get("event_class", "ticker_event"))))
    return events


def nearby_events(day: date, events: list[tuple[date, str]], window_days: int) -> list[str]:
    found: list[str] = []
    for event_date, event_class in events:
        if abs((day - event_date).days) <= window_days:
            found.append(f"{event_class}:{event_date.isoformat()}")
    return found


def suspicious_gap_rows(bars: list[Bar], events: list[tuple[date, str]], event_window_days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, len(bars)):
        prior = bars[index - 1]
        current = bars[index]
        if prior.close <= 0 or current.open <= 0:
            continue
        ratio = current.open / prior.close
        local_median = median_abs_gap(bars, index)
        threshold = max(0.35, 8 * local_median)
        if ratio >= 1.5 or ratio <= 0.67 or abs(math.log(ratio)) > threshold:
            found_events = nearby_events(current.day, events, event_window_days)
            classification = "corporate_action_explained" if found_events else "suspicious_gap_without_corporate_action"
            rows.append(
                {
                    "symbol": current.ticker,
                    "prior_date": prior.day.isoformat(),
                    "current_date": current.day.isoformat(),
                    "prior_close": prior.close,
                    "current_open": current.open,
                    "raw_gap_ratio": ratio,
                    "local_median_abs_gap": local_median,
                    "classification": classification,
                    "nearby_events": ";".join(found_events),
                }
            )
    return rows


def corrected_output_check(bars: list[Bar], split_rows: list[dict[str, str]]) -> dict[str, int]:
    """Validate in-memory split-adjusted rows without writing a dataset."""
    factors_by_date: list[tuple[date, float]] = []
    for row in split_rows:
        execution_date = parse_iso_date(row.get("execution_date", ""))
        split_from = parse_float(row.get("split_from"))
        split_to = parse_float(row.get("split_to"))
        if execution_date is None or split_from is None or split_to is None or split_from <= 0 or split_to <= 0:
            continue
        factors_by_date.append((execution_date, split_from / split_to))
    issues = {
        "negative_adjusted_prices": 0,
        "invalid_adjusted_ohlc": 0,
        "negative_adjusted_volume": 0,
    }
    for bar in bars:
        factor = 1.0
        for execution_date, price_factor in factors_by_date:
            if bar.day < execution_date:
                factor *= price_factor
        adj_open = bar.open * factor
        adj_high = bar.high * factor
        adj_low = bar.low * factor
        adj_close = bar.close * factor
        adj_volume = bar.volume / factor if factor else -1
        if min(adj_open, adj_high, adj_low, adj_close) <= 0:
            issues["negative_adjusted_prices"] += 1
        if adj_high < adj_low or adj_open < adj_low or adj_open > adj_high or adj_close < adj_low or adj_close > adj_high:
            issues["invalid_adjusted_ohlc"] += 1
        if adj_volume < 0:
            issues["negative_adjusted_volume"] += 1
    return issues


def validate_symbol(
    entry: UniverseEntry,
    *,
    daily_bars_dir: Path,
    market_calendar: list[date],
    split_rows: list[dict[str, str]],
    dividend_rows: list[dict[str, str]],
    ticker_event_rows: list[dict[str, str]],
    ticker_detail_rows: list[dict[str, str]],
    known_exclusions: dict[str, str],
    event_window_days: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    symbol = entry.symbol
    if symbol in known_exclusions:
        return (
            {
                "symbol": symbol,
                "status": "excluded",
                "reason": known_exclusions[symbol],
                "rows": 0,
                "first_date": "",
                "last_date": "",
                "missing_dates": 0,
                "duplicate_dates": 0,
                "duplicate_bars": 0,
                "invalid_dates": 0,
                "missing_required_fields": 0,
                "invalid_prices": 0,
                "invalid_ohlc": 0,
                "invalid_volume": 0,
                "inconsistent_identifiers": 0,
                "splits": len(split_rows),
                "dividends": len(dividend_rows),
                "ticker_events": len(ticker_event_rows),
                "split_consistent": 0,
                "split_possible_already_adjusted": 0,
                "split_inconsistent": 0,
                "split_not_observable": 0,
                "suspicious_gaps": 0,
                "unexplained_suspicious_gaps": 0,
                "blocking_issues": 0,
                "warning_issues": 1,
            },
            [],
            [],
        )

    bars, raw_counts = read_bars(daily_bars_dir / f"{symbol}.csv", symbol)
    duplicate_dates, duplicate_bars = duplicate_counts(bars)
    missing_dates = missing_dates_count(bars, market_calendar)
    detail_missing = 0 if ticker_detail_rows else 1

    split_report_rows: list[dict[str, Any]] = []
    split_classes = defaultdict(int)
    split_blocking = 0
    for row in split_rows:
        classification = classify_split_event(bars, row)
        split_classes[classification["classification"]] += 1
        if classification["blocking"]:
            split_blocking += 1
        split_report_rows.append(
            {
                "symbol": symbol,
                "execution_date": row.get("execution_date", ""),
                "event_class": event_class_for_split(row),
                "split_from": row.get("split_from", ""),
                "split_to": row.get("split_to", ""),
                **classification,
            }
        )

    gaps = suspicious_gap_rows(bars, event_dates_for_symbol(split_rows, ticker_event_rows), event_window_days)
    unexplained_gaps = sum(1 for row in gaps if row["classification"] == "suspicious_gap_without_corporate_action")
    adjusted_issues = corrected_output_check(bars, split_rows)

    blocking_issues = (
        (1 if not bars else 0)
        + duplicate_dates
        + duplicate_bars
        + raw_counts["invalid_dates"]
        + raw_counts["missing_required_fields"]
        + raw_counts["invalid_prices"]
        + raw_counts["invalid_ohlc"]
        + raw_counts["invalid_volume"]
        + raw_counts["inconsistent_identifiers"]
        + split_blocking
        + sum(adjusted_issues.values())
    )
    warning_issues = missing_dates + detail_missing + unexplained_gaps

    if blocking_issues:
        status = "failed"
        reason = "blocking_data_quality_or_split_issue"
    elif warning_issues:
        status = "review_required"
        reason = "non_blocking_missing_dates_or_unexplained_gaps"
    else:
        status = "passed"
        reason = "validated"

    return (
        {
            "symbol": symbol,
            "status": status,
            "reason": reason,
            "rows": len(bars),
            "first_date": bars[0].day.isoformat() if bars else "",
            "last_date": bars[-1].day.isoformat() if bars else "",
            "missing_dates": missing_dates,
            "duplicate_dates": duplicate_dates,
            "duplicate_bars": duplicate_bars,
            "invalid_dates": raw_counts["invalid_dates"],
            "missing_required_fields": raw_counts["missing_required_fields"],
            "invalid_prices": raw_counts["invalid_prices"],
            "invalid_ohlc": raw_counts["invalid_ohlc"],
            "invalid_volume": raw_counts["invalid_volume"],
            "inconsistent_identifiers": raw_counts["inconsistent_identifiers"],
            "splits": len(split_rows),
            "dividends": len(dividend_rows),
            "ticker_events": len(ticker_event_rows),
            "split_consistent": split_classes["raw_split_consistent"],
            "split_possible_already_adjusted": split_classes["possible_already_adjusted"],
            "split_inconsistent": split_classes["split_gap_inconsistent"],
            "split_not_observable": split_classes["not_observable"],
            "suspicious_gaps": len(gaps),
            "unexplained_suspicious_gaps": unexplained_gaps,
            "blocking_issues": blocking_issues,
            "warning_issues": warning_issues,
        },
        split_report_rows,
        gaps,
    )


def run_validation(args: argparse.Namespace) -> int:
    entries = load_iwb_universe(args.universe_file)
    splits_by_symbol = group_by_symbol(read_csv_rows(args.splits_file))
    dividends_by_symbol = group_by_symbol(read_csv_rows(args.dividends_file))
    ticker_events_by_symbol = group_by_symbol(read_csv_rows(args.ticker_events_file))
    ticker_details_by_symbol = group_by_symbol(read_csv_rows(args.ticker_details_file))
    known_exclusions = load_known_exclusions(args.symbol_compatibility_report)
    collection_report = read_json(args.collection_report_file)

    if args.symbols:
        requested = {normalize_symbol(item.strip()) for item in args.symbols.split(",") if item.strip()}
        entries = [entry for entry in entries if entry.symbol in requested]

    print_progress("market_calendar_build_start", symbols=len(entries))
    market_calendar = build_market_calendar(entries, args.daily_bars_dir)
    print_progress("market_calendar_build_complete", dates=len(market_calendar))

    symbol_rows: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []

    for index, entry in enumerate(entries, start=1):
        row, symbol_split_rows, symbol_gap_rows = validate_symbol(
            entry,
            daily_bars_dir=args.daily_bars_dir,
            market_calendar=market_calendar,
            split_rows=splits_by_symbol.get(entry.symbol, []),
            dividend_rows=dividends_by_symbol.get(entry.symbol, []),
            ticker_event_rows=ticker_events_by_symbol.get(entry.symbol, []),
            ticker_detail_rows=ticker_details_by_symbol.get(entry.symbol, []),
            known_exclusions=known_exclusions,
            event_window_days=args.event_window_days,
        )
        symbol_rows.append(row)
        split_rows.extend(symbol_split_rows)
        gap_rows.extend(symbol_gap_rows)
        if index % args.progress_every == 0 or index == len(entries):
            print_progress("validation_progress", symbols_done=index, symbols_total=len(entries))

    status_counts: dict[str, int] = defaultdict(int)
    for row in symbol_rows:
        status_counts[str(row["status"])] += 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    symbol_report = args.output_dir / "historical_bars_corporate_action_validation.csv"
    split_report = args.output_dir / "split_event_validation.csv"
    gap_report = args.output_dir / "suspicious_gap_validation.csv"
    summary_report = args.output_dir / "historical_bars_corporate_action_validation_report.json"

    write_csv_atomic(symbol_report, SYMBOL_REPORT_FIELDS, symbol_rows)
    write_csv_atomic(split_report, SPLIT_REPORT_FIELDS, split_rows)
    write_csv_atomic(gap_report, GAP_REPORT_FIELDS, gap_rows)

    failed_collection_symbols = collection_report.get("failed_symbols") or {}
    expected_excluded_failures = {
        symbol: failed_collection_symbols[symbol]
        for symbol in failed_collection_symbols
        if normalize_symbol(symbol) in known_exclusions
    }
    unexpected_collection_failures = {
        symbol: error
        for symbol, error in failed_collection_symbols.items()
        if normalize_symbol(symbol) not in known_exclusions
    }

    blocking_symbols = [row["symbol"] for row in symbol_rows if row["status"] == "failed"]
    review_symbols = [row["symbol"] for row in symbol_rows if row["status"] == "review_required"]
    report = {
        "updated_at_utc": utc_now_text(),
        "validator_version": "1",
        "universe_symbols": len(entries),
        "known_exclusions": known_exclusions,
        "collection_counts": collection_report.get("counts", {}),
        "collection_downloads_ohlcv": collection_report.get("downloads_ohlcv"),
        "collection_normal_operation_dependency": collection_report.get("normal_operation_dependency"),
        "expected_excluded_collection_failures": expected_excluded_failures,
        "unexpected_collection_failures": unexpected_collection_failures,
        "status_counts": dict(sorted(status_counts.items())),
        "blocking_symbol_count": len(blocking_symbols),
        "review_symbol_count": len(review_symbols),
        "blocking_symbols": blocking_symbols[:200],
        "review_symbols": review_symbols[:200],
        "outputs": {
            "symbol_report": str(symbol_report),
            "split_report": str(split_report),
            "gap_report": str(gap_report),
        },
        "ok": not blocking_symbols and not unexpected_collection_failures,
        "production_runtime_changed": False,
        "raw_data_modified": False,
        "corrected_dataset_written": False,
    }
    write_json_atomic(summary_report, report)
    print(json.dumps({"stage": "historical_bar_corporate_action_validation", "ok": report["ok"], "status_counts": report["status_counts"], "blocking_symbols": len(blocking_symbols), "review_symbols": len(review_symbols)}, indent=2))
    return 0 if report["ok"] else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate local historical bars against collected corporate actions")
    parser.add_argument("--universe-file", type=Path, default=DEFAULT_UNIVERSE_FILE)
    parser.add_argument("--daily-bars-dir", type=Path, default=DEFAULT_DAILY_BARS_DIR)
    parser.add_argument("--splits-file", type=Path, default=SPLITS_FILE)
    parser.add_argument("--dividends-file", type=Path, default=DIVIDENDS_FILE)
    parser.add_argument("--ticker-events-file", type=Path, default=TICKER_EVENTS_FILE)
    parser.add_argument("--ticker-details-file", type=Path, default=TICKER_DETAILS_FILE)
    parser.add_argument("--collection-report-file", type=Path, default=COLLECTION_REPORT_FILE)
    parser.add_argument("--symbol-compatibility-report", type=Path, default=SYMBOL_COMPATIBILITY_REPORT)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--symbols", help="comma-separated symbols for focused validation")
    parser.add_argument("--event-window-days", type=int, default=3)
    parser.add_argument("--progress-every", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.event_window_days < 0:
        raise DownloadError("--event-window-days cannot be negative")
    if args.progress_every < 1:
        raise DownloadError("--progress-every must be at least 1")
    return run_validation(args)


if __name__ == "__main__":
    raise SystemExit(main())

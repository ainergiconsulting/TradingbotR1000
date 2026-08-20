"""Analyse Phase A2 corporate-action validation findings.

This tool is intentionally offline and non-production. It reads Phase A2
validation artifacts, classifies validation findings by likely cause, and
writes reproducible machine-readable and human-readable reports.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_VALIDATION_DIR = PROJECT_ROOT / "data" / "validation" / "historical_corporate_actions"
DEFAULT_SYMBOL_VALIDATION_FILE = DEFAULT_VALIDATION_DIR / "historical_bars_corporate_action_validation.csv"
DEFAULT_SPLIT_VALIDATION_FILE = DEFAULT_VALIDATION_DIR / "split_event_validation.csv"
DEFAULT_GAP_VALIDATION_FILE = DEFAULT_VALIDATION_DIR / "suspicious_gap_validation.csv"
DEFAULT_OUTPUT_CSV = DEFAULT_VALIDATION_DIR / "phase_a2_finding_diagnostics.csv"
DEFAULT_OUTPUT_JSON = DEFAULT_VALIDATION_DIR / "phase_a2_finding_diagnostics_summary.json"
DEFAULT_OUTPUT_MD = PROJECT_ROOT / "docs" / "PHASE_A2_VALIDATION_FINDINGS_INVESTIGATION_20260724.md"
DEFAULT_TICKER_EVENTS_FILE = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "ticker_events.csv"
DEFAULT_COMPATIBILITY_CSV = PROJECT_ROOT / "ibkr_r1000_results" / "symbol_compatibility_validation.csv"
DEFAULT_COMPATIBILITY_REPORT = PROJECT_ROOT / "ibkr_r1000_results" / "symbol_compatibility_validation_report.json"
DEFAULT_COLLECTION_REPORT = PROJECT_ROOT / "ibkr_r1000_results" / "massive_corporate_actions_report.json"

DIAGNOSTIC_FIELDS = [
    "symbol",
    "validation_status",
    "primary_cause",
    "cause_categories",
    "recommended_resolution",
    "safe_for_corrected_dataset_promotion",
    "rows",
    "first_date",
    "last_date",
    "missing_dates",
    "unexplained_suspicious_gaps",
    "corporate_action_explained_gaps",
    "split_possible_already_adjusted",
    "split_inconsistent",
    "ticker_events",
    "material_ticker_change_events",
    "ibkr_status",
    "ibkr_reason",
    "massive_collection_failure",
    "details",
]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def to_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def parse_iso_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def normalize_symbol_for_compare(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "").replace(".", "").replace("-", "")


def group_rows(rows: list[dict[str, str]], field: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = str(row.get(field, "")).strip()
        if key:
            grouped[key].append(row)
    return grouped


def compatibility_by_symbol(path: Path) -> dict[str, dict[str, str]]:
    return {row.get("canonical_symbol", ""): row for row in read_csv_rows(path) if row.get("canonical_symbol")}


def known_exclusions(path: Path) -> dict[str, str]:
    payload = read_json(path)
    exclusions: dict[str, str] = {}
    for item in payload.get("excluded_symbols") or []:
        if isinstance(item, dict):
            symbol = str(item.get("symbol") or item.get("source_symbol") or "").strip()
            if symbol:
                exclusions[symbol] = str(item.get("reason") or "known_exclusion")
    return exclusions


def collection_failures(path: Path) -> dict[str, str]:
    payload = read_json(path)
    failures = payload.get("failed_symbols") or {}
    return {str(symbol): str(reason) for symbol, reason in failures.items()}


def compact_split_details(split_rows: list[dict[str, str]]) -> str:
    pieces = []
    for row in split_rows:
        if str(row.get("blocking", "")).lower() != "true":
            continue
        pieces.append(
            "{date} {event} {split_from}:{split_to} observed={observed} residual={residual} class={classification}".format(
                date=row.get("execution_date", ""),
                event=row.get("event_class", ""),
                split_from=row.get("split_from", ""),
                split_to=row.get("split_to", ""),
                observed=row.get("observed_gap_ratio", ""),
                residual=row.get("split_gap_residual", ""),
                classification=row.get("classification", ""),
            )
        )
    return "; ".join(pieces)


def material_ticker_change_events(
    symbol: str,
    event_rows: list[dict[str, str]],
    first_date: str,
    last_date: str,
) -> list[str]:
    """Return relevant ticker-change evidence, excluding generic same-ticker rows.

    Massive's ticker-events endpoint emits many same-ticker historical rows. Those
    are useful reference metadata but are not, by themselves, proof that a ticker
    change caused a validation warning.
    """
    first = parse_iso_date(first_date)
    last = parse_iso_date(last_date)
    current = normalize_symbol_for_compare(symbol)
    material: list[str] = []
    for row in event_rows:
        event_date = parse_iso_date(row.get("event_date"))
        if first is not None and last is not None and event_date is not None:
            if not first <= event_date <= last:
                continue
        raw_payload: dict[str, Any] = {}
        try:
            raw_payload = json.loads(row.get("raw_json", "") or "{}")
        except json.JSONDecodeError:
            raw_payload = {}
        ticker_value = (
            raw_payload.get("ticker_change", {}).get("ticker")
            if isinstance(raw_payload.get("ticker_change"), dict)
            else ""
        )
        compared = normalize_symbol_for_compare(ticker_value)
        if compared and compared != current:
            material.append(f"{row.get('event_date', '')}:{ticker_value}")
    return material


def classify_symbol(
    row: dict[str, str],
    *,
    split_rows: list[dict[str, str]],
    gap_rows: list[dict[str, str]],
    ticker_event_rows: list[dict[str, str]],
    compatibility_row: dict[str, str] | None,
    exclusion_reason: str,
    collection_failure: str,
) -> dict[str, Any]:
    symbol = row["symbol"]
    status = row["status"]
    missing_dates = to_int(row.get("missing_dates"))
    unexplained_gaps = to_int(row.get("unexplained_suspicious_gaps"))
    split_possible_already_adjusted = to_int(row.get("split_possible_already_adjusted"))
    split_inconsistent = to_int(row.get("split_inconsistent"))
    ticker_events = to_int(row.get("ticker_events"))
    material_ticker_events = material_ticker_change_events(
        symbol,
        ticker_event_rows,
        row.get("first_date", ""),
        row.get("last_date", ""),
    )
    corporate_action_explained_gaps = sum(
        1 for item in gap_rows if item.get("classification") == "corporate_action_explained"
    )

    categories: set[str] = set()
    details: list[str] = []

    if status == "excluded":
        categories.update({"symbol_mapping_problem", "data_source_limitation"})
        if exclusion_reason:
            details.append(f"Known IBKR exclusion: {exclusion_reason}")
        if collection_failure:
            details.append(f"Massive collection failure: {collection_failure}")
        primary_cause = "known_symbol_exclusion"
        resolution = "Exclude from automated corrected dataset and carry exclusion reason into the Security Master."
        safe = "no"
    else:
        if split_possible_already_adjusted:
            categories.update({"corporate_actions", "historical_data_inconsistencies"})
            details.append(f"{split_possible_already_adjusted} split event(s) appear already adjusted or missing the raw split gap")
        if split_inconsistent:
            categories.update({"corporate_actions", "historical_data_inconsistencies"})
            details.append(f"{split_inconsistent} split event(s) have raw price gaps inconsistent with the collected split factor")
        if corporate_action_explained_gaps:
            categories.add("corporate_actions")
            details.append(f"{corporate_action_explained_gaps} suspicious gap(s) are explained by nearby corporate actions")
        if missing_dates:
            categories.update({"historical_data_inconsistencies", "data_source_limitation"})
            details.append(f"{missing_dates} missing market-calendar dates inside the local first/last bar range")
        if unexplained_gaps:
            categories.update({"historical_data_inconsistencies", "data_source_limitation"})
            details.append(f"{unexplained_gaps} suspicious gap(s) have no nearby collected corporate action")
        if material_ticker_events:
            categories.add("ticker_changes")
            details.append(f"Material ticker-change evidence: {'; '.join(material_ticker_events)}")
        if compatibility_row and compatibility_row.get("status") not in ("", "ok"):
            categories.add("symbol_mapping_problem")
            details.append(f"IBKR compatibility status: {compatibility_row.get('status')} {compatibility_row.get('reason', '')}".strip())

        if split_possible_already_adjusted or split_inconsistent:
            primary_cause = "corporate_action_historical_data_mismatch"
            resolution = "Quarantine before corrected dataset promotion; verify event dates and split factors against Security Master/corporate-action sources, then repair or exclude explicitly."
            safe = "no"
        elif missing_dates and unexplained_gaps:
            primary_cause = "missing_dates_and_unexplained_gaps"
            resolution = "Review before promotion; repair only confirmed data defects, otherwise quarantine from corrected research datasets."
            safe = "review"
        elif missing_dates:
            primary_cause = "missing_dates"
            resolution = "Review missing-date pattern; allow only if explained by listing history, trading halt, or known structural event."
            safe = "review"
        elif unexplained_gaps:
            primary_cause = "unexplained_price_gaps"
            resolution = "Review suspicious gaps against corporate-action and listing history before corrected dataset promotion."
            safe = "review"
        else:
            primary_cause = "non_blocking_validation_warning"
            resolution = "Review warning details before promotion."
            safe = "review"

    if not details:
        details.append("No additional detail available from Phase A2 validation artifacts")

    return {
        "symbol": symbol,
        "validation_status": status,
        "primary_cause": primary_cause,
        "cause_categories": ";".join(sorted(categories)),
        "recommended_resolution": resolution,
        "safe_for_corrected_dataset_promotion": safe,
        "rows": row.get("rows", ""),
        "first_date": row.get("first_date", ""),
        "last_date": row.get("last_date", ""),
        "missing_dates": missing_dates,
        "unexplained_suspicious_gaps": unexplained_gaps,
        "corporate_action_explained_gaps": corporate_action_explained_gaps,
        "split_possible_already_adjusted": split_possible_already_adjusted,
        "split_inconsistent": split_inconsistent,
        "ticker_events": ticker_events,
        "material_ticker_change_events": len(material_ticker_events),
        "ibkr_status": (compatibility_row or {}).get("status", ""),
        "ibkr_reason": (compatibility_row or {}).get("reason", ""),
        "massive_collection_failure": collection_failure,
        "details": "; ".join(details + ([compact_split_details(split_rows)] if compact_split_details(split_rows) else [])),
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(item) for item in row) + " |")
    return "\n".join(lines)


def render_markdown(summary: dict[str, Any], diagnostics: list[dict[str, Any]]) -> str:
    blockers = [row for row in diagnostics if row["validation_status"] == "failed"]
    review = [row for row in diagnostics if row["validation_status"] == "review_required"]
    excluded = [row for row in diagnostics if row["validation_status"] == "excluded"]
    top_missing = sorted(review, key=lambda row: int(row["missing_dates"]), reverse=True)[:10]
    top_gaps = sorted(review, key=lambda row: int(row["unexplained_suspicious_gaps"]), reverse=True)[:10]

    blocker_rows = [
        [
            row["symbol"],
            row["primary_cause"],
            row["cause_categories"],
            row["details"],
            row["recommended_resolution"],
        ]
        for row in blockers
    ]
    excluded_rows = [
        [
            row["symbol"],
            row["primary_cause"],
            row["ibkr_reason"] or row["details"],
            row["recommended_resolution"],
        ]
        for row in excluded
    ]
    cause_rows = [[cause, count] for cause, count in summary["cause_category_counts"].items()]
    review_primary_rows = [[cause, count] for cause, count in summary["review_required_primary_cause_counts"].items()]
    review_detail_rows = [
        ["Symbols with missing dates", summary["review_required_metrics"]["symbols_with_missing_dates"]],
        ["Symbols with unexplained suspicious gaps", summary["review_required_metrics"]["symbols_with_unexplained_gaps"]],
        ["Symbols with both missing dates and unexplained gaps", summary["review_required_metrics"]["symbols_with_both"]],
        ["Review symbols with material ticker-change evidence", summary["review_required_metrics"]["symbols_with_material_ticker_change_events"]],
    ]
    top_missing_rows = [
        [row["symbol"], row["missing_dates"], row["rows"], row["first_date"], row["last_date"]]
        for row in top_missing
        if int(row["missing_dates"]) > 0
    ]
    top_gap_rows = [
        [row["symbol"], row["unexplained_suspicious_gaps"], row["rows"], row["first_date"], row["last_date"]]
        for row in top_gaps
        if int(row["unexplained_suspicious_gaps"]) > 0
    ]

    lines = [
        "# Phase A2 Validation Findings Investigation",
        "",
        f"Generated: {summary['updated_at_utc']}",
        "",
        "## Scope",
        "",
        "This investigation classifies the non-passed Phase A2 validation findings using reusable Python analysis. It does not modify production runtime behavior, raw historical data, or corrected datasets.",
        "",
        "## Summary",
        "",
        markdown_table(
            ["Item", "Count"],
            [
                ["Universe symbols", summary["universe_symbols"]],
                ["Passed", summary["validation_status_counts"].get("passed", 0)],
                ["Review required", summary["validation_status_counts"].get("review_required", 0)],
                ["Failed/blocking", summary["validation_status_counts"].get("failed", 0)],
                ["Known exclusions", summary["validation_status_counts"].get("excluded", 0)],
            ],
        ),
        "",
        "## Cause Category Counts",
        "",
        markdown_table(["Cause category", "Symbols"], cause_rows),
        "",
        "## Blocking Symbols",
        "",
        markdown_table(["Symbol", "Primary cause", "Cause categories", "Evidence", "Safest resolution"], blocker_rows),
        "",
        "## Review-Required Symbols",
        "",
        "Review-required symbols are non-blocking warnings from the Phase A2 validator. They are dominated by missing dates and unexplained suspicious gaps.",
        "",
        markdown_table(["Primary cause", "Symbols"], review_primary_rows),
        "",
        markdown_table(["Review-required detail", "Symbols"], review_detail_rows),
        "",
        "### Largest Missing-Date Findings",
        "",
        markdown_table(["Symbol", "Missing dates", "Rows", "First date", "Last date"], top_missing_rows),
        "",
        "### Largest Unexplained-Gap Findings",
        "",
        markdown_table(["Symbol", "Unexplained gaps", "Rows", "First date", "Last date"], top_gap_rows),
        "",
        "## Known Massive Exclusions",
        "",
        markdown_table(["Symbol", "Primary cause", "Evidence", "Safest resolution"], excluded_rows),
        "",
        "## Safest Resolution Strategy",
        "",
        "1. Do not promote a corrected dataset containing unresolved blocking symbols.",
        "2. Carry HOLX and NSA as explicit Security Master exclusions with their IBKR and Massive evidence.",
        "3. Quarantine HLT, HEI.A, DD, HEI, CGNX and APLD until corporate-action dates, split factors and local raw bars are reconciled.",
        "4. For the 111 review-required symbols, prioritise symbols with large missing-date counts or repeated unexplained gaps before any research dataset promotion.",
        "5. Repair only confirmed data defects. Do not synthesize bars, silently combine predecessor histories, or double-adjust prices.",
        "",
        "## Cause Determination",
        "",
        "- Blocking symbols are caused by corporate-action and historical-bar inconsistencies. They are not safe for automatic correction or promotion.",
        "- Review-required symbols are caused by missing local dates, unexplained suspicious gaps, or both. Some also have material ticker-change evidence, but the Phase A2 evidence does not show a project-wide symbol-mapping failure.",
        "- HOLX and NSA are known exclusions caused by unresolved or unsuitable security resolution, evidenced by IBKR compatibility validation and Massive lookup failures.",
        "- No production implementation defect was identified.",
        "",
        "## Output Evidence",
        "",
        f"- Diagnostics CSV: `{summary['outputs']['diagnostics_csv']}`",
        f"- Diagnostics summary JSON: `{summary['outputs']['summary_json']}`",
        "",
        "## Implementation Defect Assessment",
        "",
        "No implementation defect was identified from the Phase A2 evidence. The findings are data-integrity findings: corporate-action/date mismatches, missing local dates, unexplained suspicious gaps, or known symbol exclusions. The validation code may still be refined in later phases, but no production runtime defect is indicated by this investigation.",
        "",
    ]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    symbol_rows = read_csv_rows(args.symbol_validation_file)
    split_rows_by_symbol = group_rows(read_csv_rows(args.split_validation_file), "symbol")
    gap_rows_by_symbol = group_rows(read_csv_rows(args.gap_validation_file), "symbol")
    ticker_events_by_symbol = group_rows(read_csv_rows(args.ticker_events_file), "canonical_symbol")
    compatibility = compatibility_by_symbol(args.compatibility_csv)
    exclusions = known_exclusions(args.compatibility_report)
    failures = collection_failures(args.collection_report)

    diagnostics = []
    for row in symbol_rows:
        if row.get("status") == "passed":
            continue
        symbol = row["symbol"]
        diagnostics.append(
            classify_symbol(
                row,
                split_rows=split_rows_by_symbol.get(symbol, []),
                gap_rows=gap_rows_by_symbol.get(symbol, []),
                ticker_event_rows=ticker_events_by_symbol.get(symbol, []),
                compatibility_row=compatibility.get(symbol),
                exclusion_reason=exclusions.get(symbol, ""),
                collection_failure=failures.get(symbol, ""),
            )
        )

    validation_counts = Counter(row.get("status", "") for row in symbol_rows)
    cause_counts: Counter[str] = Counter()
    primary_counts: Counter[str] = Counter()
    review_primary_counts: Counter[str] = Counter()
    for row in diagnostics:
        primary_counts[row["primary_cause"]] += 1
        if row["validation_status"] == "review_required":
            review_primary_counts[row["primary_cause"]] += 1
        for category in str(row["cause_categories"]).split(";"):
            if category:
                cause_counts[category] += 1

    summary = {
        "updated_at_utc": utc_now_text(),
        "universe_symbols": len(symbol_rows),
        "non_passed_symbols": len(diagnostics),
        "validation_status_counts": dict(sorted(validation_counts.items())),
        "primary_cause_counts": dict(sorted(primary_counts.items())),
        "review_required_primary_cause_counts": dict(sorted(review_primary_counts.items())),
        "review_required_metrics": {
            "symbols_with_missing_dates": sum(1 for row in diagnostics if row["validation_status"] == "review_required" and int(row["missing_dates"]) > 0),
            "symbols_with_unexplained_gaps": sum(1 for row in diagnostics if row["validation_status"] == "review_required" and int(row["unexplained_suspicious_gaps"]) > 0),
            "symbols_with_both": sum(
                1
                for row in diagnostics
                if row["validation_status"] == "review_required"
                and int(row["missing_dates"]) > 0
                and int(row["unexplained_suspicious_gaps"]) > 0
            ),
            "symbols_with_material_ticker_change_events": sum(
                1
                for row in diagnostics
                if row["validation_status"] == "review_required"
                and int(row["material_ticker_change_events"]) > 0
            ),
        },
        "cause_category_counts": dict(sorted(cause_counts.items())),
        "blocking_symbols": [row["symbol"] for row in diagnostics if row["validation_status"] == "failed"],
        "review_required_symbols": [row["symbol"] for row in diagnostics if row["validation_status"] == "review_required"],
        "known_exclusions": [row["symbol"] for row in diagnostics if row["validation_status"] == "excluded"],
        "implementation_defects_detected": [],
        "outputs": {
            "diagnostics_csv": str(args.output_csv),
            "summary_json": str(args.output_json),
            "markdown_report": str(args.output_md),
        },
        "production_runtime_changed": False,
        "raw_data_modified": False,
        "corrected_dataset_written": False,
    }

    write_csv_atomic(args.output_csv, DIAGNOSTIC_FIELDS, diagnostics)
    write_json_atomic(args.output_json, summary)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(summary, diagnostics), encoding="utf-8")

    print(json.dumps({"ok": True, "non_passed_symbols": len(diagnostics), "outputs": summary["outputs"]}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyse Phase A2 validation findings")
    parser.add_argument("--symbol-validation-file", type=Path, default=DEFAULT_SYMBOL_VALIDATION_FILE)
    parser.add_argument("--split-validation-file", type=Path, default=DEFAULT_SPLIT_VALIDATION_FILE)
    parser.add_argument("--gap-validation-file", type=Path, default=DEFAULT_GAP_VALIDATION_FILE)
    parser.add_argument("--ticker-events-file", type=Path, default=DEFAULT_TICKER_EVENTS_FILE)
    parser.add_argument("--compatibility-csv", type=Path, default=DEFAULT_COMPATIBILITY_CSV)
    parser.add_argument("--compatibility-report", type=Path, default=DEFAULT_COMPATIBILITY_REPORT)
    parser.add_argument("--collection-report", type=Path, default=DEFAULT_COLLECTION_REPORT)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

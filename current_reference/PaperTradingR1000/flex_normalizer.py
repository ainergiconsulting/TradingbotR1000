"""
TradingbotR1000 read-only IBKR Flex XML normalizer.

This module converts selected, already-retrieved raw IBKR Flex XML sections into
stable CSV and JSON tables. It intentionally does not reconcile, compute final
P&L, place orders, or modify the raw XML inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "reports" / "flex_normalized"
METADATA_FIELDS = [
    "source_filename",
    "source_report_type",
    "source_section",
    "source_record_type",
    "extracted_at_utc",
]


ACTIVITY_TABLES = {
    "account_information": {
        "section": "AccountInformation",
        "record": "AccountInformation",
        "mode": "section",
    },
    "equity_summary_in_base": {
        "section": "EquitySummaryInBase",
        "record": "EquitySummaryByReportDateInBase",
        "mode": "children",
    },
    "change_in_nav": {
        "section": "ChangeInNAV",
        "record": "ChangeInNAV",
        "mode": "section",
    },
    "cash_report": {
        "section": "CashReport",
        "record": "CashReportCurrency",
        "mode": "children",
    },
    "net_stock_position_summary": {
        "section": "NetStockPositionSummary",
        "record": "NetStockPosition",
        "mode": "children",
    },
    "conversion_rates": {
        "section": "ConversionRates",
        "record": "ConversionRate",
        "mode": "children",
    },
}


TRADE_CONFIRMATION_TABLES = {
    "trades": {"section": "Trades", "record": "Trade", "mode": "children"},
    "orders": {"section": "Trades", "record": "Order", "mode": "children"},
    "lots": {"section": "Trades", "record": "Lot", "mode": "children"},
    "symbol_summary": {
        "section": "Trades",
        "record": "SymbolSummary",
        "mode": "children",
    },
    "asset_summary": {
        "section": "Trades",
        "record": "AssetSummary",
        "mode": "children",
    },
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _base_row(
    *,
    source_path: Path,
    source_report_type: str,
    source_section: str,
    source_record_type: str,
    extracted_at_utc: str,
) -> dict[str, str]:
    return {
        "source_filename": source_path.name,
        "source_report_type": source_report_type,
        "source_section": source_section,
        "source_record_type": source_record_type,
        "extracted_at_utc": extracted_at_utc,
    }


def _string_attrs(element: ET.Element) -> dict[str, str]:
    return {
        str(key): "" if value is None else str(value)
        for key, value in element.attrib.items()
    }


def extract_table(
    root: ET.Element,
    source_path: Path,
    source_report_type: str,
    table_spec: dict[str, str],
    extracted_at_utc: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    section_name = table_spec["section"]
    record_name = table_spec["record"]
    mode = table_spec["mode"]

    for section in root.findall(f".//{section_name}"):
        if mode == "section":
            candidates = [section]
        else:
            candidates = [child for child in list(section) if child.tag == record_name]

        for element in candidates:
            row = _base_row(
                source_path=source_path,
                source_report_type=source_report_type,
                source_section=section_name,
                source_record_type=record_name,
                extracted_at_utc=extracted_at_utc,
            )
            row.update(_string_attrs(element))
            rows.append(row)

    return rows


def normalize_report(
    xml_path: Path,
    source_report_type: str,
    table_specs: dict[str, dict[str, str]],
    extracted_at_utc: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    source_path = Path(xml_path)
    root = parse_xml(source_path)
    timestamp = extracted_at_utc or utc_timestamp()

    return {
        table_name: extract_table(
            root=root,
            source_path=source_path,
            source_report_type=source_report_type,
            table_spec=spec,
            extracted_at_utc=timestamp,
        )
        for table_name, spec in table_specs.items()
    }


def _fieldnames(rows: list[dict[str, str]]) -> list[str]:
    fields = set()
    for row in rows:
        fields.update(row.keys())

    non_metadata = sorted(field for field in fields if field not in METADATA_FIELDS)
    return [field for field in METADATA_FIELDS if field in fields] + non_metadata


def write_table(output_dir: Path, table_name: str, rows: list[dict[str, str]]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{table_name}.csv"
    json_path = output_dir / f"{table_name}.json"

    fieldnames = _fieldnames(rows)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return [csv_path, json_path]


def write_tables(
    output_dir: Path,
    normalized_tables: dict[str, list[dict[str, str]]],
) -> list[Path]:
    paths: list[Path] = []
    for table_name in sorted(normalized_tables):
        paths.extend(write_table(output_dir, table_name, normalized_tables[table_name]))
    return paths


def normalize_activity_report(
    activity_xml: Path,
    output_dir: Path,
    extracted_at_utc: str | None = None,
) -> list[Path]:
    tables = normalize_report(
        activity_xml,
        "activity",
        ACTIVITY_TABLES,
        extracted_at_utc=extracted_at_utc,
    )
    return write_tables(output_dir, tables)


def normalize_trade_confirmation_report(
    trade_confirmation_xml: Path,
    output_dir: Path,
    extracted_at_utc: str | None = None,
) -> list[Path]:
    tables = normalize_report(
        trade_confirmation_xml,
        "trade_confirmation",
        TRADE_CONFIRMATION_TABLES,
        extracted_at_utc=extracted_at_utc,
    )
    return write_tables(output_dir, tables)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize selected IBKR Flex XML sections to CSV/JSON."
    )
    parser.add_argument("--activity-xml", type=Path, required=True)
    parser.add_argument("--trade-confirmation-xml", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    extracted_at = utc_timestamp()
    written = []
    written.extend(
        normalize_activity_report(
            args.activity_xml,
            args.output_dir,
            extracted_at_utc=extracted_at,
        )
    )
    written.extend(
        normalize_trade_confirmation_report(
            args.trade_confirmation_xml,
            args.output_dir,
            extracted_at_utc=extracted_at,
        )
    )

    for path in written:
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

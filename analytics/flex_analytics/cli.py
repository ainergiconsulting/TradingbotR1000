"""Standalone daily Flex analytics CLI for TradingbotR1000."""

from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path

from .config import DEFAULT_DB_PATH, DEFAULT_REPORT_PATH, ensure_analytics_dirs, load_config
from .downloader import download_daily_activity
from .reporting import generate_excel_report
from .storage import connect, export_normalized_csv, ingest_new_raw_reports
from .validate_report import validate_report_accuracy


def run_daily(download: bool = False, raw_dir: Path | None = None) -> dict[str, object]:
    ensure_analytics_dirs()
    raw_count = 0
    if download:
        config = load_config()
        download_daily_activity(config)
    with closing(connect(DEFAULT_DB_PATH)) as conn:
        raw_count = ingest_new_raw_reports(conn, raw_dir or load_config().output_dir if download else Path("analytics/data/raw"))
        export_normalized_csv(conn)
        workbook = generate_excel_report(conn, DEFAULT_REPORT_PATH)
        validation = validate_report_accuracy(conn, workbook) if workbook.exists() else {"status": "SKIPPED"}
    return {
        "bot": "TradingbotR1000",
        "raw_reports_ingested": raw_count,
        "database": str(DEFAULT_DB_PATH),
        "workbook": str(DEFAULT_REPORT_PATH),
        "validation": validation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradingbotR1000 daily Flex analytics")
    parser.add_argument("command", nargs="?", default="run-daily", choices=["run-daily", "validate-only"])
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "validate-only":
        ensure_analytics_dirs()
        print(json.dumps({"status": "OK", "database": str(DEFAULT_DB_PATH)}, indent=2))
        return 0
    print(json.dumps(run_daily(download=args.download), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

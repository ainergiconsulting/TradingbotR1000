from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from r1000_data_integrity.security_master import (
    SecurityMasterPaths,
    build_security_master,
    canonical_symbol,
    validate_security_master,
)


class SecurityMasterTests(unittest.TestCase):
    def test_canonical_symbol_handles_share_class_aliases(self) -> None:
        self.assertEqual(canonical_symbol("BRKB"), "BRK.B")
        self.assertEqual(canonical_symbol("HEIA"), "HEI.A")
        self.assertEqual(canonical_symbol("UHAL B"), "UHAL.B")

    def test_build_preserves_ids_and_validates_core_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _write_fixture(root)

            first = build_security_master(paths)
            self.assertEqual(first.securities, 14)
            self.assertEqual(first.excluded, 2)
            self.assertEqual(first.blocked, 6)

            validation = validate_security_master(paths)
            self.assertTrue(validation["ok"], validation["checks"])

            conn = sqlite3.connect(paths.database)
            try:
                aapl_id = conn.execute(
                    "SELECT canonical_security_id FROM securities WHERE canonical_symbol='AAPL'"
                ).fetchone()[0]
                hei_ids = {
                    row[0]
                    for row in conn.execute(
                        "SELECT canonical_security_id FROM securities WHERE canonical_symbol IN ('HEI','HEI.A')"
                    ).fetchall()
                }
                excluded = {
                    row[0]
                    for row in conn.execute(
                        "SELECT canonical_symbol FROM securities WHERE trading_status='excluded'"
                    ).fetchall()
                }
            finally:
                conn.close()

            self.assertEqual(len(hei_ids), 2)
            self.assertEqual(excluded, {"HOLX", "NSA"})

            build_security_master(paths)
            conn = sqlite3.connect(paths.database)
            try:
                rebuilt_aapl_id = conn.execute(
                    "SELECT canonical_security_id FROM securities WHERE canonical_symbol='AAPL'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(rebuilt_aapl_id, aapl_id)


def _write_fixture(root: Path) -> SecurityMasterPaths:
    output_dir = root / "security_master"
    inputs = root / "inputs"
    inputs.mkdir()
    daily_bars = root / "daily_bars"
    daily_bars.mkdir()

    iwb = inputs / "IWB_holdings.csv"
    rows = [
        ["iShares Russell 1000 ETF"],
        ["Fund Holdings as of", "Jul 17, 2026"],
        [],
        [
            "Ticker",
            "Name",
            "Sector",
            "Asset Class",
            "Market Value",
            "Weight (%)",
            "Notional Value",
            "Quantity",
            "Price",
            "Location",
            "Exchange",
            "Currency",
            "FX Rate",
            "Market Currency",
            "Accrual Date",
        ],
    ]
    symbols = ["AAPL", "BRKB", "BFA", "BFB", "HEIA", "LENB", "UHALB", "HOLX", "NSA", "HLT", "DD", "HEI", "CGNX", "APLD"]
    for index, symbol in enumerate(symbols, start=1):
        rows.append([symbol, f"{symbol} INC", "Sector", "Equity", "1000", "0.1", "1000", "1", "10", "United States", "NYSE", "USD", "1", "USD", "-"])
    with iwb.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    compatibility = inputs / "symbol_compatibility_validation.csv"
    comp_fields = [
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
    comp_rows = []
    con_id = 1000
    for source_symbol in symbols:
        canonical = canonical_symbol(source_symbol)
        status = "excluded" if canonical in {"HOLX", "NSA"} else "ok"
        reason = "known_exclusion" if status == "excluded" else ""
        comp_rows.append(
            {
                "validator_version": "1",
                "validated_at_utc": "2026-07-24T00:00:00Z",
                "source_symbol": source_symbol,
                "canonical_symbol": canonical,
                "historical_file": str(daily_bars / f"{canonical}.csv"),
                "historical_file_exists": "true",
                "source_exchange": "NYSE",
                "expected_ibkr_primary_exchange": "NYSE",
                "ibkr_request_symbol": canonical.replace(".", " "),
                "ibkr_symbol": canonical.replace(".", " "),
                "ibkr_local_symbol": canonical.replace(".", " "),
                "ibkr_trading_class": canonical.replace(".", " "),
                "ibkr_sec_type": "STK",
                "ibkr_exchange": "SMART",
                "ibkr_primary_exchange": "NYSE",
                "ibkr_currency": "USD",
                "ibkr_con_id": "" if status == "excluded" else str(con_id),
                "status": status,
                "reason": reason,
                "attempts": "1",
            }
        )
        con_id += 1
    _write_dicts(compatibility, comp_fields, comp_rows)

    compatibility_report = inputs / "symbol_compatibility_validation_report.json"
    compatibility_report.write_text(
        '{"excluded_symbols":[{"symbol":"HOLX","reason":"known_exclusion"},{"symbol":"NSA","reason":"known_exclusion"}]}',
        encoding="utf-8",
    )

    details = inputs / "ticker_details.csv"
    detail_fields = [
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
    _write_dicts(
        details,
        detail_fields,
        [
            {
                "source_symbol": source_symbol,
                "canonical_symbol": canonical_symbol(source_symbol),
                "massive_ticker": canonical_symbol(source_symbol),
                "name": f"{source_symbol} INC",
                "market": "stocks",
                "locale": "us",
                "primary_exchange": "XNYS",
                "currency_name": "usd",
                "active": "True",
                "list_date": "2000-01-01",
                "delisted_utc": "",
                "cik": str(100000 + index),
                "composite_figi": f"FIGI{index}",
                "share_class_figi": f"SCFIGI{index}",
                "raw_json": "{}",
            }
            for index, source_symbol in enumerate(symbols, start=1)
            if canonical_symbol(source_symbol) not in {"HOLX", "NSA"}
        ],
    )

    ticker_events = inputs / "ticker_events.csv"
    _write_dicts(ticker_events, ["source_symbol", "canonical_symbol", "event_class", "event_date", "event_type", "ticker", "name", "composite_figi", "share_class_figi", "cik", "raw_json"], [])

    splits = inputs / "splits.csv"
    split_fields = ["source_symbol", "canonical_symbol", "event_class", "execution_date", "split_from", "split_to", "ratio", "adjustment_type", "historical_adjustment_factor", "raw_json"]
    _write_dicts(splits, split_fields, [{"source_symbol": "AAPL", "canonical_symbol": "AAPL", "event_class": "forward_split", "execution_date": "2020-08-31", "split_from": "1", "split_to": "4", "ratio": "4", "adjustment_type": "forward_split", "historical_adjustment_factor": "0.25", "raw_json": "{}"}])

    dividends = inputs / "dividends.csv"
    _write_dicts(dividends, ["source_symbol", "canonical_symbol", "event_class", "ex_dividend_date", "declaration_date", "record_date", "pay_date", "cash_amount", "split_adjusted_cash_amount", "currency", "dividend_type", "frequency", "historical_adjustment_factor", "raw_json"], [])

    capabilities = inputs / "event_capabilities.csv"
    _write_dicts(capabilities, ["event_class", "source", "initial_support", "notes"], [])

    diagnostics = inputs / "phase_a2_finding_diagnostics.csv"
    diag_fields = ["symbol", "validation_status", "primary_cause", "cause_categories", "recommended_resolution", "safe_for_corrected_dataset_promotion", "details"]
    _write_dicts(
        diagnostics,
        diag_fields,
        [
            {"symbol": symbol, "validation_status": "failed", "primary_cause": "corporate_action_historical_data_mismatch", "cause_categories": "corporate_actions", "recommended_resolution": "quarantine", "safe_for_corrected_dataset_promotion": "no", "details": "blocking"}
            for symbol in ["HLT", "HEI.A", "DD", "HEI", "CGNX", "APLD"]
        ]
        + [
            {"symbol": "HOLX", "validation_status": "excluded", "primary_cause": "known_symbol_exclusion", "cause_categories": "symbol_mapping_problem", "recommended_resolution": "exclude", "safe_for_corrected_dataset_promotion": "no", "details": "excluded"},
            {"symbol": "NSA", "validation_status": "excluded", "primary_cause": "known_symbol_exclusion", "cause_categories": "symbol_mapping_problem", "recommended_resolution": "exclude", "safe_for_corrected_dataset_promotion": "no", "details": "excluded"},
        ],
    )

    symbol_validation = inputs / "historical_bars_corporate_action_validation.csv"
    _write_dicts(symbol_validation, ["symbol", "status", "reason"], [])

    return SecurityMasterPaths(
        iwb_file=iwb,
        ibkr_compatibility_csv=compatibility,
        ibkr_compatibility_report=compatibility_report,
        massive_details_csv=details,
        ticker_events_csv=ticker_events,
        splits_csv=splits,
        dividends_csv=dividends,
        event_capabilities_csv=capabilities,
        phase_a2_diagnostics_csv=diagnostics,
        phase_a2_symbol_validation_csv=symbol_validation,
        daily_bars_dir=daily_bars,
        output_dir=output_dir,
        database=output_dir / "security_master.sqlite3",
        security_export=output_dir / "security_master_export.csv",
        identifiers_export=output_dir / "security_master_identifiers.csv",
        actions_export=output_dir / "security_master_corporate_actions.csv",
        manifest=output_dir / "security_master_manifest.json",
        validation_report=output_dir / "security_master_validation_report.json",
        validation_csv=output_dir / "security_master_validation_checks.csv",
    )


def _write_dicts(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    unittest.main()

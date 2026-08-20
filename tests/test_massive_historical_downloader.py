from __future__ import annotations

import csv
from datetime import date

from current_reference.PaperTradingR1000.massive_historical_downloader import (
    EXPECTED_SCHEMA,
    UniverseEntry,
    aggregate_to_schema_row,
    load_iwb_universe,
    merge_rows,
    normalize_symbol,
    validate_rows_against_schema,
)


def test_normalize_symbol_maps_iwb_share_classes() -> None:
    assert normalize_symbol("BRKB") == "BRK.B"
    assert normalize_symbol("BFB") == "BF.B"
    assert normalize_symbol("abc ") == "ABC"


def test_load_iwb_universe_skips_metadata_and_normalizes_symbols(tmp_path) -> None:
    path = tmp_path / "IWB_holdings.csv"
    rows = [
        ["metadata"],
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
        ["BRKB", "BERKSHIRE HATHAWAY INC CLASS B", "Financials", "Equity", "", "", "", "", "", "US", "NYSE", "USD", "", "USD", ""],
        ["CASH", "CASH", "Cash and/or Derivatives", "Cash", "", "", "", "", "", "US", "", "USD", "", "USD", ""],
        ["AAPL", "APPLE INC", "Information Technology", "Equity", "", "", "", "", "", "US", "NASDAQ", "USD", "", "USD", ""],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)

    entries = load_iwb_universe(path)

    assert [entry.symbol for entry in entries] == ["BRK.B", "AAPL"]
    assert entries[0].source_symbol == "BRKB"


def test_aggregate_to_schema_row_uses_historical_bars_contract() -> None:
    entry = UniverseEntry("AAPL", "AAPL", "APPLE INC", "NASDAQ", "USD", "Information Technology")
    row = aggregate_to_schema_row(
        {"t": 1719792000000, "o": 1.0, "h": 2.5, "l": 0.75, "c": 2.0, "v": 1234, "n": 12, "vw": 1.9},
        entry,
    )

    assert list(row) == EXPECTED_SCHEMA
    assert row["ticker"] == "AAPL"
    assert row["date"] == "20240701"
    assert row["close"] == "2"


def test_merge_rows_deduplicates_by_ticker_and_date_with_incoming_precedence() -> None:
    existing = [{"ticker": "AAPL", "date": "20240102", "close": "1"}, {"ticker": "MSFT", "date": "20240102", "close": "9"}]
    incoming = [{"ticker": "AAPL", "date": "20240102", "close": "2"}, {"ticker": "AAPL", "date": "20240103", "close": "3"}]

    rows = merge_rows(existing, incoming)

    assert [(row["ticker"], row["date"], row["close"]) for row in rows] == [
        ("AAPL", "20240102", "2"),
        ("AAPL", "20240103", "3"),
        ("MSFT", "20240102", "9"),
    ]


def test_validate_rows_against_schema_detects_clean_ordered_sample() -> None:
    entry = UniverseEntry("AAPL", "AAPL", "APPLE INC", "NASDAQ", "USD", "Information Technology")
    row = {
        "ticker": "AAPL",
        "name": "APPLE INC",
        "con_id": "",
        "local_symbol": "AAPL",
        "date": "20240102",
        "open": "1",
        "high": "2",
        "low": "1",
        "close": "2",
        "volume": "100",
        "bar_count": "10",
        "average": "1.5",
    }

    result = validate_rows_against_schema([row], EXPECTED_SCHEMA, [entry], date(2024, 1, 1), date(2024, 1, 31))

    assert result.passed
    assert result.duplicates == 0
    assert result.missing_fields == 0

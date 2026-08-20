from __future__ import annotations

import json
from pathlib import Path

from tools import collect_massive_corporate_actions as collector


def test_split_event_class_forward_and_reverse() -> None:
    assert collector.event_class_for_split({"split_from": 1, "split_to": 4}) == "forward_split"
    assert collector.event_class_for_split({"split_from": 5, "split_to": 1}) == "reverse_split"


def test_consolidate_payloads_dedupes_and_writes_expected_outputs(tmp_path: Path) -> None:
    payloads = [
        {
            "source_symbol": "ABC",
            "canonical_symbol": "ABC",
            "splits": [
                {
                    "execution_date": "2024-01-02",
                    "split_from": 1,
                    "split_to": 2,
                    "adjustment_type": "split",
                    "historical_adjustment_factor": 0.5,
                },
                {
                    "execution_date": "2024-01-02",
                    "split_from": 1,
                    "split_to": 2,
                    "adjustment_type": "split",
                    "historical_adjustment_factor": 0.5,
                },
            ],
            "dividends": [
                {
                    "ex_dividend_date": "2024-02-01",
                    "cash_amount": 0.25,
                    "split_adjusted_cash_amount": 0.25,
                    "dividend_type": "CD",
                    "currency": "USD",
                }
            ],
            "ticker_details": {
                "results": {
                    "ticker": "ABC",
                    "name": "ABC Corp",
                    "market": "stocks",
                    "locale": "us",
                    "primary_exchange": "XNYS",
                    "active": True,
                    "composite_figi": "BBG000ABC",
                }
            },
            "ticker_events": {
                "results": {
                    "events": [
                        {
                            "date": "2023-12-15",
                            "type": "ticker_change",
                            "ticker": "ABC",
                            "name": "ABC Corp",
                        }
                    ]
                }
            },
        }
    ]

    counts = collector.consolidate_payloads(payloads, tmp_path)
    ok, checks = collector.validate_outputs(tmp_path)

    assert counts == {
        "symbols": 1,
        "splits": 1,
        "dividends": 1,
        "ticker_details": 1,
        "ticker_events": 1,
    }
    assert ok
    assert checks["splits"]["duplicates"] == 0
    assert (tmp_path / "corporate_actions" / "event_capabilities.csv").exists()


def test_dry_run_does_not_require_api_key(monkeypatch, tmp_path: Path, capsys) -> None:
    universe = tmp_path / "IWB_holdings.csv"
    universe.write_text(
        "\n".join(
            [
                "iShares Russell 1000 ETF",
                "Fund Holdings as of,\"Jul 17, 2026\"",
                "Ticker,Name,Asset Class,Currency,Market Currency,Exchange,Sector",
                "AAPL,APPLE INC,Equity,USD,USD,NASDAQ,Information Technology",
                "MSFT,MICROSOFT CORP,Equity,USD,USD,NASDAQ,Information Technology",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)

    code = collector.main(
        [
            "--dry-run",
            "--universe-file",
            str(universe),
            "--output-root",
            str(tmp_path / "out"),
            "--sample-size",
            "1",
            "--max-symbols",
            "1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["massive_api_key_present"] is False
    assert output["downloads_ohlcv"] is False
    assert output["target_symbols"] == ["AAPL"]

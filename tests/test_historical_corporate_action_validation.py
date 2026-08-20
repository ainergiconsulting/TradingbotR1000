from __future__ import annotations

from datetime import date

from tools import validate_historical_bars_against_corporate_actions as validator


def _bar(day: date, open_: float, high: float, low: float, close: float) -> validator.Bar:
    text = day.strftime("%Y%m%d")
    return validator.Bar(
        date_text=text,
        day=day,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000,
        ticker="ABC",
        local_symbol="ABC",
        raw={},
    )


def test_split_classification_detects_raw_forward_split() -> None:
    bars = [
        _bar(date(2024, 1, 2), 100, 102, 99, 100),
        _bar(date(2024, 1, 3), 25, 26, 24, 25),
    ]
    event = {"execution_date": "2024-01-03", "split_from": "1", "split_to": "4"}

    result = validator.classify_split_event(bars, event)

    assert result["classification"] == "raw_split_consistent"
    assert result["blocking"] is False


def test_split_classification_detects_possible_already_adjusted() -> None:
    bars = [
        _bar(date(2024, 1, 2), 25, 26, 24, 25),
        _bar(date(2024, 1, 3), 25, 26, 24, 25),
    ]
    event = {"execution_date": "2024-01-03", "split_from": "1", "split_to": "4"}

    result = validator.classify_split_event(bars, event)

    assert result["classification"] == "possible_already_adjusted"
    assert result["blocking"] is True


def test_suspicious_gap_marks_corporate_action_explained() -> None:
    bars = [
        _bar(date(2024, 1, 2), 100, 102, 99, 100),
        _bar(date(2024, 1, 3), 25, 26, 24, 25),
    ]

    rows = validator.suspicious_gap_rows(bars, [(date(2024, 1, 3), "forward_split")], 3)

    assert rows[0]["classification"] == "corporate_action_explained"

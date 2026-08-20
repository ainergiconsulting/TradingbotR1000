# Phase A2 - Corporate-Action Collection And Historical Validation

Date: 2026-07-24

Programme: Program A - Production & Data Integrity

Status: collection complete; historical validation complete with data-quality blockers.

## Scope

This milestone resumed Phase A2 after the approved Phase A2.5 design gate. It performed the one-time Massive corporate-action collection for the current TradingbotR1000 universe and validated the existing local historical bars against the collected corporate actions.

No production runtime behavior was changed.

No OHLCV bars were downloaded from Massive.

No raw historical data files were modified.

No corrected dataset was generated or promoted.

## Collection Summary

Source universe:

`C:\TradingbotR1000\IWB_holdings.csv`

Collection output:

`C:\TradingbotR1000\data\source\massive\corporate_actions`

Collection report:

`C:\TradingbotR1000\ibkr_r1000_results\massive_corporate_actions_report.json`

Collected records:

| Item | Count |
|---|---:|
| Symbols with collected Massive reference data | 1022 |
| Splits | 180 |
| Dividends | 24333 |
| Ticker details | 1022 |
| Ticker events | 1131 |

Known collection failures:

| Symbol | Treatment |
|---|---|
| HOLX | Known IBKR exclusion: `ibkr_unresolved_no_market_universe_symbol` |
| NSA | Known IBKR exclusion: `ibkr_value_only_no_smart_or_nyse_stock_contract` |

These failures are expected exclusions and are not unexpected Massive collection failures.

## Historical Validation Summary

Validation output:

`C:\TradingbotR1000\data\validation\historical_corporate_actions`

Validation report:

`C:\TradingbotR1000\data\validation\historical_corporate_actions\historical_bars_corporate_action_validation_report.json`

Validation results:

| Status | Symbols |
|---|---:|
| Passed | 905 |
| Review required | 111 |
| Failed | 6 |
| Excluded | 2 |
| Total universe symbols validated | 1024 |

Blocking symbols:

| Symbol | Blocking issue |
|---|---|
| HLT | Split gap inconsistent around the collected reverse split event. |
| HEI.A | Possible already-adjusted split gap detected. |
| DD | Split gap inconsistent and 438 missing local dates. |
| HEI | Possible already-adjusted split gap detected. |
| CGNX | Possible already-adjusted split gap and one suspicious unexplained gap. |
| APLD | Split gap inconsistent and two suspicious unexplained gaps. |

The 111 review-required symbols contain non-blocking validation warnings such as missing dates or suspicious gaps requiring review before any corrected dataset is promoted.

## Evidence

Generated validation files:

- `C:\TradingbotR1000\data\validation\historical_corporate_actions\historical_bars_corporate_action_validation.csv`
- `C:\TradingbotR1000\data\validation\historical_corporate_actions\split_event_validation.csv`
- `C:\TradingbotR1000\data\validation\historical_corporate_actions\suspicious_gap_validation.csv`
- `C:\TradingbotR1000\data\validation\historical_corporate_actions\historical_bars_corporate_action_validation_report.json`

## Result

Phase A2 collection and validation are complete, but the historical dataset is not yet clean enough for automatic correction or promotion. The next Program A implementation phase must preserve these findings and either repair, quarantine, or explicitly exclude the six blocking symbols before a corrected dataset is used.

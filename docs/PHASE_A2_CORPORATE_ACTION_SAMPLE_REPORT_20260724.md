# Phase A2 Corporate-Action Sample Report

Date: 2026-07-24

Scope: one-time Massive historical correction input workflow. No OHLCV bars were requested and no production runtime behavior was changed.

## Tool

`C:\TradingbotR1000\tools\collect_massive_corporate_actions.py`

## Live Sample Command

```powershell
python -B tools\collect_massive_corporate_actions.py --sample --symbols AAPL --skip-ticker-events --max-retries 1 --timeout-seconds 20 --rate-limit-pause-seconds 0.25 --force
```

## Result

Status: passed

Massive API key: present in process, not printed.

Sample symbol: `AAPL`

Counts:

- Splits: `1`
- Dividends: `40`
- Ticker details: `1`
- Ticker events: `0` because the experimental ticker-events endpoint was skipped for the first connectivity sample.

## Output Files

- `C:\TradingbotR1000\data\source\massive\corporate_actions\by_symbol\AAPL.json`
- `C:\TradingbotR1000\data\source\massive\corporate_actions\splits.csv`
- `C:\TradingbotR1000\data\source\massive\corporate_actions\dividends.csv`
- `C:\TradingbotR1000\data\source\massive\corporate_actions\ticker_events.csv`
- `C:\TradingbotR1000\data\source\massive\corporate_actions\event_capabilities.csv`
- `C:\TradingbotR1000\data\source\massive\reference\ticker_details.csv`
- `C:\TradingbotR1000\ibkr_r1000_results\massive_corporate_actions_checkpoint.json`
- `C:\TradingbotR1000\ibkr_r1000_results\massive_corporate_actions_report.json`
- `C:\TradingbotR1000\ibkr_r1000_results\massive_corporate_actions_failed_symbols.csv`
- `C:\TradingbotR1000\ibkr_r1000_results\massive_corporate_actions.log`

## Validation

- Consolidated CSV schemas validated.
- Duplicate event keys validated.
- Failed-symbol report written.
- Checkpoint written.
- `downloads_ohlcv` reported as `false`.
- `normal_operation_dependency` reported as `false`.

## Remaining Phase A2 Work

- Run full current-universe corporate-action collection with checkpoints.
- Validate ticker-events endpoint entitlement and reliability.
- Validate existing local historical bars against collected corporate actions.


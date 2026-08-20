# TradingbotR1000 Current State Audit

Date: 2026-07-24

Scope: planning-only audit. No production trading logic, launchers, scheduled tasks, databases, runtime behavior, or strategy parameters were changed.

## Verified Repository State

Project root:

`C:\TradingbotR1000`

Authoritative strategy document:

`C:\TradingbotR1000\docs\TradingbotR1000_Strategy_Specification_FINAL_v1.1.docx`

Primary project specification:

`C:\TradingbotR1000\docs\PROJECT_SPECIFICATION.md`

Migration roadmap:

`C:\TradingbotR1000\docs\MIGRATION_MATRIX.md`

Production runtime package:

`C:\TradingbotR1000\current_reference\PaperTradingR1000`

Research package:

`C:\TradingbotR1000\backtests\r1000_max_positions_corrected`

## Production Architecture Observed

```text
TradingbotControl shortcuts
  -> run/start_trading_system.bat
      -> current_reference/PaperTradingR1000/operational_controller.py
          -> strategy_scheduler.py
          -> trading_engine.py --scan-once
              -> config_loader.py
              -> IWB_holdings.csv
              -> data/daily_bars/*.csv
              -> strategy.py
              -> automated_broker.py
                  -> IBKR Paper account
              -> automated_order_store.py
              -> reconciliation.py
              -> quality_monitor.py
          -> runtime_health.py / heartbeat.json / bot_status.json
  -> run/stop_trading_system.bat
  -> run/control_console.bat
      -> manual_control_console.py
      -> gateway_status.py
      -> live_account.py / broker_snapshot.json / runtime state

Telegram reporting
  -> telegram_commands.py
  -> monitoring_core.py
  -> same runtime state, broker snapshot, scan report, order plan, reconciliation reports
```

The active architecture reuses the Tradingbot2607 operational pattern: a background controller, explicit start/stop entry points, a separate manual console, runtime JSON state, broker snapshots, scan reports, order plans, reconciliation reports, and Telegram-readable monitoring state.

## Active Production Runtime

Main runtime process:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\operational_controller.py`

Strategy entry point used by the controller:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\trading_engine.py --scan-once`

Scheduling component:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\strategy_scheduler.py`

Default strategy cycle:

`09:35 America/New_York`, one eligible US trading session at most once per day.

IBKR Paper Trading configuration:

- Host: `127.0.0.1` by default.
- Port: `4002` by default.
- Automated trading client ID: `1000`.
- Manual console client ID: `1001`.
- Reconciliation client ID: `1002`.
- Remote control client ID: `1003`.
- Telegram client ID: `1004`.

Automated PAPER execution switch:

`TRADINGBOTR1000_ENABLE_AUTOMATED_PAPER_EXECUTION`

## Runtime State And Evidence Files

Runtime state directory:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\state`

Key observed files:

- `bot_status.json`
- `heartbeat.json`
- `runtime_health.json`
- `controller_status.json`
- `broker_snapshot.json`
- `automated_orders.json`
- `scheduler_state.json`
- `investable_capital_control.json`

Report directory:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\reports`

Key report files:

- `scan_report.json`
- `order_plan.json`
- `reconciliation_report.json`
- `automated_execution_report.json`
- `quality_monitoring/*`

The Control Console and Telegram reporting read these same files rather than maintaining a separate operational state store.

## Universe Flow

Current universe source:

`C:\TradingbotR1000\IWB_holdings.csv`

Runtime universe configuration:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\config_files\universe_config.json`

Observed behavior:

- The active source is a static local IWB holdings CSV.
- The file identifies iShares Russell 1000 ETF holdings as of `Jul 17, 2026`.
- The runtime scans for the holdings header and uses the `Ticker` column.
- Non-equity and non-USD rows are filtered by the loader.
- Symbol normalization is currently handled by `symbol_mapping.py`.
- The active implementation does not yet include an automated daily IWB holdings update workflow.

## Historical Data Flow

Primary per-symbol bar database:

`C:\TradingbotR1000\data\daily_bars`

Consolidated Massive checkpoint:

`C:\TradingbotR1000\ibkr_r1000_results\historical_bars.massive_checkpoint.csv`

Schema reference:

`C:\TradingbotR1000\ibkr_r1000_results\historical_bars.csv`

Primary schema:

`ticker,name,con_id,local_symbol,date,open,high,low,close,volume,bar_count,average`

Observed data state from the approved data-readiness audit:

- Active normalized universe: `1,024` current IWB equity symbols.
- Active tradable universe after IBKR exclusions: `1,022` symbols.
- Daily bar files: `1,025`.
- Extra stale local file: `UHALB.csv`; canonical file exists as `UHAL.B.csv`.
- Symbols with at least 200 observations: `1,013`.
- Active tradable symbols latest date at audit time: `2026-07-21`.
- The Massive progress metadata shows `adjusted: false`.
- No local dividend or split-factor fields exist in the current bar schema.

## Massive Data Capabilities Checked

Massive currently documents stock corporate-action endpoints that are relevant to this project:

- Splits: `GET /stocks/v1/splits`, including split execution date, split ratio, adjustment type, and `historical_adjustment_factor`.
- Dividends: `GET /stocks/v1/dividends`, including ex-dividend date, cash amount, split-adjusted cash amount, distribution type, and `historical_adjustment_factor`.
- Ticker overview and all-tickers endpoints include active status, identifiers such as CIK and FIGI, primary exchange, listing date, and delisting information.
- Ticker events are documented as an experimental endpoint for ticker changes and related entity events.
- ETF Global constituents are documented as a separate partner dataset with ETF holdings, weights, effective dates, processed dates, and identifiers such as ISIN, FIGI, SEDOL, and US code.

Planning implication: Massive appears suitable for split, dividend, ticker-status, ticker-format, and possibly ETF holdings validation, subject to the user's subscription entitlements. The current repository does not yet ingest or persist those corporate-action datasets.

## Symbol Compatibility Flow

Current mapping module:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\symbol_mapping.py`

Current validation tool:

`C:\TradingbotR1000\tools\validate_symbol_compatibility.py`

Current validation outputs:

- `C:\TradingbotR1000\ibkr_r1000_results\symbol_compatibility_validation.csv`
- `C:\TradingbotR1000\ibkr_r1000_results\symbol_compatibility_validation_report.json`

Observed validation evidence:

- Total symbols checked: `1,024`.
- Resolved in IBKR: `1,022`.
- Explicitly excluded: `2`.
- Unresolved symbols: `0`.
- Excluded symbols:
  - `HOLX`: `ibkr_unresolved_no_market_universe_symbol`
  - `NSA`: `ibkr_value_only_no_smart_or_nyse_stock_contract`
- Confirmed ticker-format mappings:
  - `BRKB -> BRK.B -> BRK B`
  - `BFA -> BF.A -> BF A`
  - `BFB -> BF.B -> BF B`
  - `HEIA -> HEI.A -> HEI A`
  - `LENB -> LEN.B -> LEN B`
  - `UHALB -> UHAL.B -> UHAL B`

Limitation:

The project has ticker normalization and a compatibility cache, but it does not yet have a central Security Master that owns canonical security identity across historical data, strategy signals, portfolio positions, pending orders, reconciliation, and order submission. The automated broker still qualifies a stock contract from the symbol at submission time instead of consistently using a previously validated contract identity.

## Order And Reconciliation Flow

Order planning:

`trading_engine.py` builds BUY and SELL order plans from the production strategy scan and live broker account context.

Automated order submission:

`automated_broker.py` uses the order plan, duplicate checks, live broker positions, open orders, and persisted automated orders. Automated execution remains governed by the explicit PAPER execution switch.

Order persistence:

`automated_order_store.py` stores every automated order identity, broker status, quantities, prices, timestamps, order IDs, perm IDs, and status history in `automated_orders.json`.

Reconciliation:

`reconciliation.py` rebuilds local state from IBKR positions, open orders, and executions. IBKR remains the source of truth.

Known constraint:

The current order flow is operationally aligned with the paper-trading design, but identifier integrity still depends on ticker-based contract resolution at order time. The next phase should move this to a central verified contract identity without changing strategy rules.

## Control Console And Operator Interface

Primary operator folder:

`C:\TradingbotR1000\TradingbotControl`

User-facing applications:

- Start Trading System
- Stop Trading System
- Control Console

Manual console implementation:

`C:\TradingbotR1000\current_reference\PaperTradingR1000\manual_control_console.py`

Launcher:

`C:\TradingbotR1000\run\control_console.bat`

The Control Console displays the R1000 preflight, runtime status, account status, portfolio summary, open orders, reconciliation, manual trading options, emergency controls, and investable-capital option 13.

## Research Architecture Observed

Research root:

`C:\TradingbotR1000\backtests\r1000_max_positions_corrected`

Research documentation root:

`C:\TradingbotR1000\backtests\r1000_max_positions_corrected\strategy_analysis`

Research completed since the corrected baseline:

- Corrected backtest framework with dynamic sizing and no negative cash.
- Max-positions sensitivity.
- Unused capital diagnostic.
- Opportunity cost analysis of the 97% entry limit.
- Portfolio entry-price sensitivity.
- Holding-period sensitivity.
- Exit diagnostics.
- RSI exit sensitivity.
- RSI exit robustness validation.
- Trade distribution and performance attribution.

Important research state:

- Production remains unchanged at RSI > 50.
- RSI > 60 is the current research baseline, not production logic.
- The next research direction should be market-regime analysis and data integrity rather than further simple parameter optimization.

## Current Data Integrity Risks

1. Historical OHLCV data was downloaded with `adjusted: false`, so split events can distort indicators, ranking, returns, and backtest comparability.
2. The current schema does not contain adjusted close, dividends, split factors, or corporate-action metadata.
3. The current universe is the current IWB holdings only, not historical Russell 1000 membership.
4. The universe source is static; no safe daily holdings update workflow is implemented yet.
5. Tickers are treated as the practical identifier in multiple places. This is not stable enough for long-running production operations.
6. Confirmed IBKR compatibility exists, but the validated contract identity is not yet the central runtime authority.
7. Sector and industry classifications are not historically dated in the current local dataset.
8. Delistings, mergers, ticker changes, and share-class changes are not represented as first-class datasets.
9. Research outputs are useful for sensitivity comparison, but they inherit survivorship, unadjusted-price, missing-dividend, missing-delisting, and current-universe biases already documented in the data-readiness audit.

## Main Conflicts Or Gaps

No direct contradiction was found between the current production architecture and `PROJECT_SPECIFICATION.md`.

The main gaps are implementation-readiness gaps for the next phase:

- No central Security Master.
- No automated IWB holdings refresh and validation workflow.
- No corporate-action ingestion and adjustment pipeline.
- No production-grade security identifier migration from ticker strings to verified IBKR contract identity.
- No regime-feature dataset or market-regime research framework.
- No approved rule for how future regime findings could influence live trading.

## Approved Programme Split

Program A - Production & Data Integrity:

Build a robust, autonomous, production-ready trading system using daily IWB holdings updates, IBKR contract/account/market-data services, a central Security Master, data-quality validation, and safe shadow promotion.

Program B - Scientific Research:

Determine under which market conditions the strategy generates alpha and when it should reduce exposure or remain inactive. Program B consumes validated research data but must not modify production behavior.

## Refined Data-Dependency Direction

Massive is not planned as a permanent production dependency. The already downloaded approximately ten-year historical dataset should be preserved. Massive should be used only during the initial historical correction phase for corporate actions, historical validation, split adjustments, and dividend-adjustment evaluation.

After migration, normal production operation should use:

- IWB for daily holdings downloads, dated snapshots, and additions/removals detection;
- IBKR for daily OHLCV updates, contract resolution, broker/account data, and minimum warm-up history for genuinely new constituents.

## Recommended Next Initialization Step

Begin with a data-integrity and identifier-foundation phase before any further strategy optimization:

1. Preserve all current raw data.
2. Add one-time Massive corporate-action ingestion for historical correction.
3. Create a central Security Master with permanent Canonical Security IDs.
4. Add a safe daily IWB holdings update workflow.
5. Add IBKR daily OHLCV update workflow for incremental operation.
6. Rebuild adjusted research datasets without altering production trading behavior.
7. Build a market-state dataset before defining market regimes.

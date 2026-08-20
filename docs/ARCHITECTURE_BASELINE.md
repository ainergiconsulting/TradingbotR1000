# TradingbotR1000 Architecture Baseline

Date: 2026-07-21

Purpose: document the latest local Tradingbot2607 project as an architectural reference only. No Tradingbot2607 files were modified, and no Tradingbot2607 code was copied into this project.

## Source Project Identification

Reference project root:

```text
C:\Tradingbot2607
```

Latest-version assessment:

- `C:\Tradingbot2607` is the latest active/restored local project found by timestamp and restore metadata.
- `C:\Tradingbot2607\RESTORE_INSTRUCTIONS.txt` identifies a verified backup archive named `Tradingbot2607_20260720_104722.zip` with checksum instructions, indicating this tree is the current restored operational workspace.
- `C:\Tradingbot2607\docs\PROJECT_STATE.md` states the active implementation release is Release 5, the configurable strategy engine.
- Release 5 evidence exists in `docs\release5_codex_conversation.md`, `tests\test_release5_strategy_config.py`, `current_reference\PaperTradingv2\strategy.py`, and `current_reference\PaperTradingv2\config_files\strategy_config.json`.
- `C:\TradingBot_Project` also exists, but it is older on disk and appears to be the prior Git-backed source copy. It should be treated as historical/reference only unless explicitly needed.

Note: `C:\Tradingbot2607` contains a `.git` folder name, but Git did not recognize it as a valid repository during this audit. Do not rely on it for source-history evidence.

## Project Overview

Tradingbot2607 is a Windows-oriented IBKR paper-trading system for US-listed stocks/ETFs. Its current active design centers on:

- an IBKR paper trading engine;
- a configurable long-only trailing-sell and rebuy strategy;
- local start/stop/session authorization scripts;
- an operational controller and health supervisor;
- Telegram monitoring commands and alerting;
- IBKR/Flex reconciliation and reporting;
- a separate daily Flex analytics subsystem;
- tests covering release milestones and safety hardening.

For TradingbotR1000, this project should be used as an architectural reference and source of proven operational patterns, not as a code source. The Russell 1000 strategy changes the scale, universe-management problem, screening/rebalancing rules, and reporting requirements enough that strategy and universe layers must be redesigned.

## Folder Structure Inventory

Top-level folders in `C:\Tradingbot2607`:

```text
.agents
.git
.tools
.venv
analytics
archive
config
current_reference
docs
run
tests
TradingBot_Control
```

Important subtrees:

```text
current_reference\PaperTradingv2
current_reference\SummaryBot
current_reference\PaperTradingv2\config_files
current_reference\PaperTradingv2\Alerts
current_reference\PaperTradingv2\logs
current_reference\PaperTradingv2\reports
current_reference\PaperTradingv2\state
analytics\flex_analytics
analytics\tests
analytics\data
analytics\database
analytics\reports
archive\release3_retired
archive\restore_points
archive\execution_history_fix_20260715_004520
archive\reconciliation_reset_20260708_154447
```

## Major Modules

Primary runtime:

- `current_reference\PaperTradingv2\PaperTradingBot_v2.py`: main bot process, IBKR connection lifecycle, cycle loop, position processing, rebuy watchlist, safety-blocked status, heartbeat, and stop handling.
- `current_reference\PaperTradingv2\strategy.py`: current Release 5 strategy implementation, configurable trailing sell, discount/recovery rebuy logic, limit price calculation, order placement, fills persistence, and order alerts.
- `current_reference\PaperTradingv2\config.py`: core runtime constants and environment/account configuration.
- `current_reference\PaperTradingv2\config_loader.py`: loads and validates strategy and symbol configuration files.
- `current_reference\PaperTradingv2\state_store.py`: atomic local state handling.
- `current_reference\PaperTradingv2\startup_validation.py`: startup preflight checks.
- `current_reference\PaperTradingv2\startup_rebuild.py`: runtime state rebuild support.
- `current_reference\PaperTradingv2\runtime_health.py`: machine-readable runtime health output.
- `current_reference\PaperTradingv2\runtime_version.py`: runtime version/status metadata.

Safety and execution:

- `current_reference\PaperTradingv2\order_safety.py`: long-only order guard, duplicate-intent handling, broker-evidence refresh, and rejection reasons.
- `current_reference\PaperTradingv2\ibkr_utils.py`: IBKR connection helpers, market data, contract state conversion, account summary, positions, open-order checks, and liquid-hours helpers.
- `current_reference\PaperTradingv2\gateway_status.py`: IB Gateway/API readiness and live operational evidence.

Controller and supervision:

- `current_reference\PaperTradingv2\operational_controller.py`: boot-session authorization, desired-running state, bounded restart behavior, reconciliation request after unexpected exits, supervisor task handling, and controller lock.
- `current_reference\PaperTradingv2\health_supervisor.py`: independent health supervision.
- `current_reference\PaperTradingv2\heartbeat_utils.py`: heartbeat publishing and freshness utilities.
- `current_reference\PaperTradingv2\control_utils.py`: control-file utilities.
- `current_reference\PaperTradingv2\monitoring_core.py`, `monitoring_io.py`, `monitoring.py`: monitoring state helpers.
- `current_reference\PaperTradingv2\logger_utils.py`: logging and scheduler log helpers.

Operator control:

- `current_reference\PaperTradingv2\manual_control_console.py`: historical operator-console reference for account/position/order views and manual actions.
- `current_reference\PaperTradingv2\manual_controls.py`: supporting control-action helpers; not transferred because the migrated manual console contains the required operator actions.

Telegram:

- `current_reference\PaperTradingv2\telegram_alerts.py`: outbound operational alerts.
- `current_reference\PaperTradingv2\telegram_commands.py`: read-only command renderers for status, health, portfolio, executions, and reconciliation.
- `current_reference\PaperTradingv2\telegram_listener.py`: Telegram listener entry point and authorization checks.
- `current_reference\PaperTradingv2\telegram_ibkr_session.py`: Telegram-specific IBKR session handling.

Reconciliation and reporting:

- `current_reference\PaperTradingv2\ibkr_flex_client.py`: IBKR Flex download client.
- `current_reference\PaperTradingv2\flex_normalizer.py`: Flex report normalization.
- `current_reference\PaperTradingv2\ibkr_reconciliation.py`: IBKR execution export/reconciliation entry point.
- `current_reference\PaperTradingv2\release3_reporter.py`: Release 3 report generator and broker/local comparison logic.
- `current_reference\PaperTradingv2\release3_api_snapshot.py`: API snapshot utility, now retired for live operational truth.
- `current_reference\PaperTradingv2\reconciliation.py`: placeholder/lightweight local reconciliation entry point.
- `current_reference\PaperTradingv2\trade_logger.py`: trade CSV/spool logging.
- `current_reference\PaperTradingv2\execution_history.py`: analytics execution history support.
- `analytics\flex_analytics\cli.py`: standalone daily Flex analytics CLI.
- `analytics\flex_analytics\downloader.py`, `normalize.py`, `storage.py`, `reporting.py`, `excel_feeds.py`, `validate_report.py`: analytics ingestion, storage, reporting, Excel feed, and validation modules.

Configuration and UI helpers:

- `current_reference\PaperTradingv2\config_editor.py`: local config editor.
- `current_reference\PaperTradingv2\dashboard_basic.py`, `dashboard_v2_utils.py`: dashboard utilities.
- `current_reference\PaperTradingv2\alert_utils.py`: alert file helpers.

## Startup Scripts

Primary scripts under `run`:

- `start_system.bat`: hidden desktop launcher for the full system.
- `start_system_desktop.pyw`: no-console system launcher.
- `start_bot.bat`: validates paper-mode environment, runs startup validation, prompts owner confirmation, authorizes current boot, then starts detached controller.
- `start_bot_desktop.pyw`: desktop bot launcher.
- `start_detached_controller.py`: starts controller detached.
- `operational_controller.bat`: controller batch wrapper.
- `health_supervisor.bat`: supervisor batch wrapper.
- `stop_system.bat`: graceful system stop, revokes authorization, creates stop files, stops Telegram listener, and does not close positions or cancel broker orders.
- `stop_bot.bat`: bot stop helper.
- `status_bot.bat`, `system_status.bat`, `system_status.ps1`: status tools.
- `control_console.bat`: manual control console launcher.
- `telegram_listener.bat`, `start_telegram_listener.pyw`, `stop_telegram_listener.bat`: Telegram listener lifecycle.
- `ibkr_reconciliation.bat`, `reconciliation.bat`: reconciliation launchers.
- `dashboard.bat`, `edit_config.bat`, `open_reports_logs.bat`: operator utilities.
- `install_scheduled_tasks.ps1`, `validate_scheduled_tasks.ps1`: Windows scheduled-task setup/validation.
- `gateway_recovery_test.py`, `check_ibkr_api_port.py`: IBKR/Gateway diagnostics.
- `reset_paper_validation.ps1`, `release1_smoke_test.ps1`: release validation helpers.

## Configuration Files

Project-level:

- `requirements.txt`
- `requirements-lock.txt`
- `.gitignore`
- `.gitattributes`
- `STARTBOT.txt`
- `RESTORE_INSTRUCTIONS.txt`

Runtime/config:

- `current_reference\PaperTradingv2\config.py`
- `current_reference\PaperTradingv2\config_files\strategy_config.json`
- `current_reference\PaperTradingv2\config_files\symbol_config.json`
- `current_reference\PaperTradingv2\config_files\order_execution_config.json`
- `current_reference\PaperTradingv2\telegram_config.example.json`
- `config\manual_trading_watchlist.xlsx`

Sensitive local files seen by name and not read:

- `current_reference\PaperTradingv2\telegram_config.json`
- `current_reference\PaperTradingv2\telegramtoken.txt`
- `current_reference\PaperTradingv2\flex_config.json`

## Tests

Top-level test suite:

- `test_execution_history_refresh.py`
- `test_ibkr_api_port_preflight.py`
- `test_long_only_order_safety.py`
- `test_p0_gateway_status.py`
- `test_release2_manual_console.py`
- `test_release3_api_snapshot.py`
- `test_release3_flex_client.py`
- `test_release3_flex_normalizer.py`
- `test_release3_reporter.py`
- `test_release4_telegram_alerts.py`
- `test_release4_telegram_monitoring.py`
- `test_release5_strategy_config.py`
- `test_runtime_restart_hardening.py`

Analytics tests:

- `analytics\tests\test_daily_flex_analytics.py`

## Architecture Diagram

```text
Owner / Operator
    |
    v
Local launchers and control shortcuts
    |
    v
Operational Control Layer
    - start/stop authorization
    - boot-session desired-running state
    - bounded restart and escalation
    |
    +--------------------------+
    |                          |
    v                          v
Health Supervisor          Telegram Monitoring
    |                          |
    v                          v
Runtime health/state       Read-only status, health,
heartbeat, logs            portfolio, executions,
                           reconciliation messages
    |
    v
Trading Engine
    - IBKR session
    - cycle scheduler
    - positions and tickers
    - stop handling
    |
    v
Strategy Layer
    - trailing sell
    - rebuy rules
    - configurable parameters
    |
    v
Order Safety and IBKR Integration
    - long-only guard
    - duplicate-intent guard
    - contract and market-hours checks
    - paper order submission
    |
    v
IBKR Paper Account

Broker/Flex evidence
    |
    v
Reconciliation and Reporting
    - Flex download/normalization
    - API snapshots
    - local trade logs
    - execution history
    - daily analytics workbook feeds
```

## Obsolete or Duplicated Files

Treat these as non-active architectural history unless explicitly needed:

- `C:\TradingBot_Project`: older local project copy with Git history; not the latest active restored codebase.
- `C:\Tradingbot2607\archive\release3_retired`: retired Release 3 active reports and snapshots; audit-only, not current operational truth.
- `C:\Tradingbot2607\archive\restore_points`: recovery snapshots; useful for provenance but duplicated source material.
- `C:\Tradingbot2607\archive\execution_history_fix_20260715_004520`: point-in-time fix archive.
- `C:\Tradingbot2607\archive\reconciliation_reset_20260708_154447`: point-in-time reconciliation reset archive.
- `C:\Tradingbot2607\.venv`: local environment; do not copy or vendor into R1000.
- `C:\Tradingbot2607\.tools`: local diagnostic tooling; do not copy unless separately approved.
- `current_reference\PaperTradingv2\__pycache__`, `logs`, `state`, `Alerts`, `reports`, and root runtime files such as `bot_log.txt` and `bot_state.json`: generated runtime evidence, not reusable source.
- Shortcut files under `TradingBot_Control`: owner convenience shortcuts tied to local paths; recreate for R1000 only after final runtime paths exist.

## Reusable Components

Components that should be reused unchanged as architecture/patterns, or copied later only after explicit approval and review:

1. Git/project governance pattern: release plans, status documents, changelog, restore instructions, and migration checklist style.
2. Windows local launch model: explicit owner start/stop, no automatic trading on reboot/logon, and desktop shortcuts as thin wrappers.
3. Operational controller design: boot-session authorization, desired-running state, bounded restart escalation, and manual-intervention lockout.
4. Health supervision pattern: independent health process, heartbeat freshness, status JSON files, and visible fail-closed reasons.
5. IBKR Gateway/API readiness state model: distinguish port/process/socket/auth/reconciled states before trading.
6. IBKR utility patterns: scoped request timeouts, deterministic client IDs, contract serialization, account/position/open-order read helpers, and liquid-hours checks.
7. Long-only order safety concepts: duplicate-intent guard, broker evidence refresh, no shorts, no unsupported instruments, and explicit rejection reasons.
8. Telegram monitoring architecture: read-only status/health/portfolio/execution/reconciliation commands and outbound alerts decoupled from strategy decisions.
9. Reconciliation/reporting principles: broker-authoritative Flex evidence, normalized tables, stale-evidence labeling, and audit-only retired reports.
10. Standalone daily analytics separation: Flex analytics must remain independent from trading runtime and must not affect orders, state, or supervision.
11. Test strategy: release-scoped tests for gateway status, Telegram rendering, long-only safety, runtime restart hardening, Flex normalization, reporter behavior, and strategy config equivalence.
12. Security posture: secrets remain local/ignored; repository stores templates and non-secret configuration only.

Reusable component count: 12

## Components To Redesign For TradingbotR1000

1. Russell 1000 universe management: ingestion, validation, symbol lifecycle, corporate-action handling, index/ETF source governance, and regular refresh policy.
2. Strategy decision layer: replace concentrated position trailing/rebuy logic with the approved Russell 1000 daily mean-reversion model: candidate ranking, selection, 70%-of-NLV investable capital, 30%-of-NLV liquidity reserve, and 20%-of-investable-capital sizing.
3. Portfolio construction and risk limits: enforce maximum five simultaneous positions, pending-BUY slot reservation, partial-fill slot handling, no leverage, and no additional filters beyond the approved strategy.
4. Data pipeline: historical bars, fundamentals or ranking inputs if used, data freshness checks, missing-symbol handling, and backfill/retry behavior.
5. Order planning/execution workflow: batch order generation, throttling, partial-fill handling, next-trading-day BUY limit plans at 97% of signal-day close, and idempotent order evidence.
6. State model: track universe membership, candidate scores, pending BUY orders, active positions, filled entry date, holding-day count, RSI exit state, and time-exit state.
7. Reporting and reconciliation outputs: add universe coverage, selected and skipped candidates, failed orders, entry/fill outcomes, exit reasons, holding period, slot usage, and capital allocation.
8. Configuration schema: replace single/default symbol strategy config with explicit R1000 universe, data-source, broker/environment, schedule, safety, logging, and reporting config files.
9. Test fixtures and simulation: create deterministic Russell 1000-scale fixtures for universe refresh, ranking, portfolio construction, and batched order planning.

Components requiring redesign count: 9

## Risks

- The latest active Tradingbot2607 folder is not a valid Git repository, despite containing a `.git` folder name. Use the July 20 restore metadata and active files as reference, not local Git history.
- Release 5 is identified as active but not fully accepted in `PROJECT_STATE.md`; do not assume all strategy/config metadata is complete.
- Secrets and local runtime config files exist by name in the reference tree. They must not be opened, copied, committed, or summarized by value.
- Runtime logs and Telegram alert logs may contain sensitive historical information.
- Archive and restore-point folders contain duplicated historical source; using them without context can reintroduce retired behavior.
- The old strategy was designed for a small active position set, not Russell 1000-scale universe selection or rebalancing.
- Existing reporting/reconciliation has useful principles but must be expanded only to the approved R1000 evidence: scan results, selected/skipped candidates, entry and fill outcomes, exit reasons, holding period, slot usage, capital allocation, and reconciliation status.
- IBKR rate limits, market-data subscriptions, and connection behavior may become materially more important with Russell 1000 coverage.
- Current startup scripts are path-specific to `C:\Tradingbot2607`; R1000 launchers must be generated for `C:\TradingbotR1000` rather than copied blindly.

## Migration Recommendations

1. Keep Tradingbot2607 read-only and reference it through this baseline plus targeted future inspections.
2. Use `docs\TradingbotR1000_Strategy_Specification_FINAL_v1.1.docx` as the trading-strategy authority and document implementation choices separately from strategy rules.
3. Build R1000 in layers: configuration schema, universe ingestion, data validation, strategy simulation, order planning, IBKR adapter, reconciliation/reporting, then operator controls.
4. Reuse the operational-control, health, IBKR-readiness, Telegram-monitoring, safety, and analytics-separation patterns as architecture, but reimplement them in clean R1000 modules with tests.
5. Keep secrets and runtime state out of Git from the start.
6. Do not connect to IBKR or start trading processes until offline tests, config validation, and dry-run order planning are complete.
7. Create a formal R1000 paper-validation gate before any live-account discussion.
8. Treat generated outputs and archived Tradingbot2607 artifacts as evidence only; do not import them into R1000 source.

# TradingbotR1000 Migration Matrix

Date: 2026-07-21

Purpose: final module-level implementation roadmap for migrating the active
Tradingbot2607 Release 5 architecture into TradingbotR1000 without changing the
approved TradingbotR1000 strategy.

Source root:

```text
C:\Tradingbot2607
```

Destination root:

```text
C:\TradingbotR1000
```

Rules:

- The approved strategy source is now `docs/TradingbotR1000_Strategy_Specification_FINAL_v1.1.docx`.
- `docs/PROJECT_SPECIFICATION.md` remains the project implementation authority.
- "Reuse unchanged" means the component may be copied with no behavior change except packaging/import mechanics required to run under TradingbotR1000.
- "Adapt" means preserve the Tradingbot2607 architectural behavior while updating names, paths, schemas, reports, or integration points for TradingbotR1000.
- "Replace" means keep the architectural responsibility but implement new R1000 behavior because the Tradingbot2607 component contains old strategy assumptions.
- "Do not transfer" means do not copy source content into TradingbotR1000; use only as historical or operational reference when needed.

## Package And Operational Component Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `.agents/` | `.agents/` | Do not transfer | Local Codex/session metadata is not application source. | None |
| `.git/` | `.git/` | Do not transfer | Repository metadata must remain specific to each project. | None |
| `.tools/` | `.tools/` | Do not transfer | Local diagnostic tooling is environment-specific and not part of the R1000 runtime. | None |
| `.venv/` | `.venv/` | Do not transfer | Virtual environments must be recreated locally, never migrated. | `requirements*.txt` |
| `archive/` | `archive/` | Do not transfer | Historical snapshots can reintroduce retired behavior and should remain reference-only. | `docs/ARCHITECTURE_BASELINE.md` |
| `current_reference/PaperTradingv2/` | `current_reference/PaperTradingR1000/` | Adapt | Keep the runtime package shape but update package identity and strategy-specific boundaries. | `docs/PROJECT_SPECIFICATION.md` |
| `current_reference/PaperTradingv2/config_files/` | `current_reference/PaperTradingR1000/config_files/` | Replace | Old config schema is trailing-sell/rebuy-specific and must become R1000 universe/data/runtime config. | `config.py`, `config_loader.py` |
| `current_reference/PaperTradingv2/Alerts/` | `current_reference/PaperTradingR1000/Alerts/` | Do not transfer | Existing alert files are generated runtime evidence, not source. | `telegram_alerts.py` |
| `current_reference/PaperTradingv2/logs/` | `current_reference/PaperTradingR1000/logs/` | Do not transfer | Logs are generated runtime evidence and may contain sensitive operational details. | `logger_utils.py` |
| `current_reference/PaperTradingv2/reports/` | `current_reference/PaperTradingR1000/reports/` | Do not transfer | Reports are generated historical evidence and must not seed R1000 source state. | Reporting modules |
| `current_reference/PaperTradingv2/state/` | `current_reference/PaperTradingR1000/state/` | Do not transfer | Runtime state belongs to the old bot and conflicts with R1000 state schema. | `state_store.py` |
| `current_reference/PaperTradingv2/__pycache__/` | None | Do not transfer | Python bytecode caches are generated artifacts. | None |
| `current_reference/SummaryBot/` | None | Do not transfer | SummaryBot is historical reporting data, not part of the approved R1000 architecture. | None |
| `analytics/` | `analytics/` | Adapt | Preserve standalone analytics separation while updating paths, names, and R1000 reporting feeds. | Flex config, reporting paths |
| `analytics/data/` | `analytics/data/` | Do not transfer | Old raw and normalized analytics data is generated evidence. | `analytics/flex_analytics/storage.py` |
| `analytics/database/` | `analytics/database/` | Do not transfer | Old analytics databases are generated state. | `analytics/flex_analytics/storage.py` |
| `analytics/logs/` | `analytics/logs/` | Do not transfer | Analytics logs are generated evidence. | `analytics/flex_analytics/cli.py` |
| `analytics/reports/` | `analytics/reports/` | Do not transfer | Old workbooks and reports are historical output, not source. | `analytics/flex_analytics/reporting.py` |
| `analytics/tests/` | `tests/analytics/` | Adapt | Preserve analytics coverage but update fixtures and paths for R1000. | Analytics package |
| `config/` | `config/` | Replace | The destination config folder must contain R1000 runtime/operator config only. | `config.py` |
| `TradingBot_Control/` | `TradingbotControl/` | Replace | Shortcuts are path-specific and must be recreated as the simplified R1000 operator folder. | `run/*.bat`, `run/*.pyw` |
| `run/` | `run/` | Adapt | Preserve owner-control scripts while updating paths, names, and R1000 entry points. | Runtime package |
| `tests/` | `tests/` | Adapt | Preserve safety and operational test intent while replacing old strategy expectations. | Runtime modules |

## Runtime Module Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `current_reference/PaperTradingv2/alert_utils.py` | `current_reference/PaperTradingR1000/alert_utils.py` | Adapt | Keep alert delivery helpers but update R1000 config paths and message labels. | `config.py`, `logger_utils.py` |
| `current_reference/PaperTradingv2/config.py` | `current_reference/PaperTradingR1000/config.py` | Replace | Old constants include trailing/rebuy settings and must be replaced by R1000 runtime constants. | Approved strategy, project spec |
| `current_reference/PaperTradingv2/config_editor.py` | `current_reference/PaperTradingR1000/config_editor.py` | Replace | Old editor targets trailing/rebuy strategy config and must become an R1000 config editor or be omitted. | New config schema |
| `current_reference/PaperTradingv2/config_loader.py` | `current_reference/PaperTradingR1000/config_loader.py` | Replace | Old loader validates trailing/rebuy and symbol weight settings that are not R1000 strategy rules. | New config files |
| `current_reference/PaperTradingv2/control_utils.py` | `current_reference/PaperTradingR1000/control_utils.py` | Adapt | Preserve stop-file and control-file utilities while removing rebuy-specific labels. | `config.py`, `logger_utils.py` |
| `current_reference/PaperTradingv2/dashboard_basic.py` | `current_reference/PaperTradingR1000/dashboard_basic.py` | Adapt | Preserve the lightweight dashboard pattern but show R1000 scan, positions, health, and config evidence. | `dashboard_v2_utils.py` |
| `current_reference/PaperTradingv2/dashboard_v2_utils.py` | `current_reference/PaperTradingR1000/dashboard_v2_utils.py` | Adapt | Preserve dashboard section helpers while replacing old config/state fields. | `config.py` |
| `current_reference/PaperTradingv2/execution_history.py` | `current_reference/PaperTradingR1000/execution_history.py` | Adapt | Preserve execution-history storage but add R1000 order-plan and exit-reason fields. | `trade_logger.py`, reporting |
| `current_reference/PaperTradingv2/flex_normalizer.py` | `current_reference/PaperTradingR1000/flex_normalizer.py` | Reuse unchanged | Flex XML normalization is broker-evidence handling and not strategy-specific. | `ibkr_flex_client.py` |
| `current_reference/PaperTradingv2/gateway_status.py` | `current_reference/PaperTradingR1000/gateway_status.py` | Adapt | Preserve layered IBKR/Gateway readiness while updating project paths and R1000 status fields. | `ibkr_utils.py`, `operational_api_snapshot.py` |
| `current_reference/PaperTradingv2/health_supervisor.py` | `current_reference/PaperTradingR1000/health_supervisor.py` | Adapt | Preserve independent health supervision while updating process names and status paths. | `runtime_health.py`, `monitoring_io.py` |
| `current_reference/PaperTradingv2/heartbeat_utils.py` | `current_reference/PaperTradingR1000/heartbeat_utils.py` | Reuse unchanged | Heartbeat writing is generic if R1000 exposes compatible config paths. | `config.py`, `logger_utils.py` |
| `current_reference/PaperTradingv2/ibkr_flex_client.py` | `current_reference/PaperTradingR1000/ibkr_flex_client.py` | Reuse unchanged | IBKR Flex download mechanics are independent of the trading strategy. | Local Flex config template |
| `current_reference/PaperTradingv2/ibkr_reconciliation.py` | `current_reference/PaperTradingR1000/ibkr_reconciliation.py` | Adapt | Preserve IBKR execution reconciliation while writing R1000 report paths and labels. | `ibkr_utils.py`, `flex_normalizer.py` |
| `current_reference/PaperTradingv2/ibkr_utils.py` | `current_reference/PaperTradingR1000/ibkr_utils.py` | Adapt | Preserve IBKR connection/account/order helpers while adding daily-bar support for R1000 scans. | `config.py`, `ib_insync` |
| `current_reference/PaperTradingv2/logger_utils.py` | `current_reference/PaperTradingR1000/logger_utils.py` | Adapt | Preserve logging discipline while updating file names, runtime directories, and R1000 labels. | `config.py`, `monitoring_io.py` |
| `current_reference/PaperTradingv2/manual_control_console.py` | `current_reference/PaperTradingR1000/manual_control_console.py` | Adapt | Preserve the working owner console menu and safety controls while updating paths and R1000 configuration. | `ibkr_utils.py`, `order_safety.py` |
| `current_reference/PaperTradingv2/manual_controls.py` | None | Do not transfer | The migrated manual console is self-contained and the separate R1000 helper became duplicate control logic. | `manual_control_console.py` |
| `current_reference/PaperTradingv2/monitoring.py` | `current_reference/PaperTradingR1000/monitoring.py` | Reuse unchanged | This compatibility wrapper is not strategy-specific. | `monitoring_core.py` |
| `current_reference/PaperTradingv2/monitoring_core.py` | `current_reference/PaperTradingR1000/monitoring_core.py` | Adapt | Preserve status and disk checks while updating R1000 status schema. | `config.py`, `monitoring_io.py` |
| `current_reference/PaperTradingv2/monitoring_io.py` | `current_reference/PaperTradingR1000/monitoring_io.py` | Reuse unchanged | Atomic JSON writing and UTC timestamps are generic utilities. | None |
| `current_reference/PaperTradingv2/operational_api_snapshot.py` | `current_reference/PaperTradingR1000/operational_api_snapshot.py` | Reuse unchanged | Read-only account, position, and open-order snapshots are strategy-independent. | `ib_insync` |
| `current_reference/PaperTradingv2/operational_controller.py` | `current_reference/PaperTradingR1000/operational_controller.py` | Adapt | Preserve boot authorization and bounded restart while launching the R1000 engine entry point. | `config.py`, engine entry point |
| `current_reference/PaperTradingv2/order_safety.py` | `current_reference/PaperTradingR1000/order_safety.py` | Adapt | Preserve long-only and duplicate-intent guards while aligning order context names to R1000. | `config.py`, `ibkr_utils.py` |
| `current_reference/PaperTradingv2/PaperTradingBot_v2.py` | `current_reference/PaperTradingR1000/trading_engine.py` | Replace | The old engine loops through current holdings and rebuy watchlists, so the R1000 engine must implement daily universe scanning and order planning. | `strategy.py`, `ibkr_utils.py`, `state_store.py` |
| `current_reference/PaperTradingv2/reconciliation.py` | `current_reference/PaperTradingR1000/reconciliation.py` | Replace | The lightweight old reconciliation entry point should be replaced by R1000 scan/order/fill reconciliation. | `ibkr_reconciliation.py`, reporting |
| `current_reference/PaperTradingv2/release3_api_snapshot.py` | None | Do not transfer | Release 3 API snapshots are retired and superseded by operational API snapshots. | None |
| `current_reference/PaperTradingv2/release3_reporter.py` | `current_reference/PaperTradingR1000/reporter.py` | Adapt | Preserve broker-authoritative reporting patterns while adding R1000 scan, selection, slot, and exit evidence. | `flex_normalizer.py`, `execution_history.py` |
| `current_reference/PaperTradingv2/runtime_health.py` | `current_reference/PaperTradingR1000/runtime_health.py` | Adapt | Preserve machine-readable health records while updating strategy-state fields for R1000. | `config.py`, `monitoring_io.py` |
| `current_reference/PaperTradingv2/runtime_version.py` | `current_reference/PaperTradingR1000/runtime_version.py` | Adapt | Preserve version/hash evidence while tracking R1000 config and approved strategy version. | New config files |
| `current_reference/PaperTradingv2/startup_rebuild.py` | `current_reference/PaperTradingR1000/startup_rebuild.py` | Replace | Old rebuild logic reconstructs trailing/rebuy state and must become R1000 position/order/state reconstruction. | `state_store.py`, `ibkr_utils.py` |
| `current_reference/PaperTradingv2/startup_validation.py` | `current_reference/PaperTradingR1000/startup_validation.py` | Adapt | Preserve startup preflight checks while validating R1000 config, universe source, data source, and paper/live safety. | `config_loader.py`, `monitoring_io.py` |
| `current_reference/PaperTradingv2/state_store.py` | `current_reference/PaperTradingR1000/state_store.py` | Adapt | Preserve atomic state handling while changing state schema to candidates, pending buys, fills, holding days, and exits. | `config.py`, `logger_utils.py` |
| `current_reference/PaperTradingv2/strategy.py` | `current_reference/PaperTradingR1000/strategy.py` | Replace | Old strategy contains trailing-sell/rebuy rules and must not be transferred into R1000. | Approved strategy DOCX |
| `current_reference/PaperTradingv2/telegram_alerts.py` | `current_reference/PaperTradingR1000/telegram_alerts.py` | Adapt | Preserve operational alerts while replacing old strategy terms with R1000 scan/order/exit events. | `telegram_commands.py`, `gateway_status.py` |
| `current_reference/PaperTradingv2/telegram_commands.py` | `current_reference/PaperTradingR1000/telegram_commands.py` | Adapt | Preserve read-only commands while rendering R1000 status, candidates, orders, positions, and reconciliation. | `execution_history.py`, `gateway_status.py` |
| `current_reference/PaperTradingv2/telegram_ibkr_session.py` | `current_reference/PaperTradingR1000/telegram_ibkr_session.py` | Adapt | Preserve read-only Telegram IBKR session management while updating project imports. | `ibkr_utils.py`, `gateway_status.py` |
| `current_reference/PaperTradingv2/telegram_listener.py` | `current_reference/PaperTradingR1000/telegram_listener.py` | Adapt | Preserve listener authorization and routing while updating command set labels and paths. | `telegram_commands.py`, `telegram_alerts.py` |
| `current_reference/PaperTradingv2/trade_logger.py` | `current_reference/PaperTradingR1000/trade_logger.py` | Adapt | Preserve durable trade logging and spool behavior while adding R1000 decision context fields. | `logger_utils.py`, `monitoring_io.py` |
| `current_reference/PaperTradingv2/README.txt` | `current_reference/PaperTradingR1000/README.txt` | Replace | Old runtime notes describe the 2607 bot and must be rewritten for R1000. | Runtime modules |

## Runtime Configuration And Local File Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `current_reference/PaperTradingv2/config_files/strategy_config.json` | `current_reference/PaperTradingR1000/config_files/strategy_constants.json` | Replace | Old strategy config exposes trailing/rebuy rules; R1000 strategy constants must mirror the approved specification only. | `config_loader.py`, approved strategy |
| `current_reference/PaperTradingv2/config_files/symbol_config.json` | `current_reference/PaperTradingR1000/config_files/universe_config.json` | Replace | Old symbol-level target/trailing/rebuy settings must become configurable Russell 1000 universe-source settings. | Universe loader |
| `current_reference/PaperTradingv2/config_files/order_execution_config.json` | `current_reference/PaperTradingR1000/config_files/order_execution_config.json` | Adapt | Preserve broker safety settings but avoid adding order type or time-in-force as strategy rules. | Order planner, IBKR adapter |
| `current_reference/PaperTradingv2/telegram_config.example.json` | `current_reference/PaperTradingR1000/telegram_config.example.json` | Adapt | Keep a non-secret template while updating bot names, paths, and allowed commands. | Telegram modules |
| `current_reference/PaperTradingv2/telegram_config.json` | None | Do not transfer | Local Telegram config may contain sensitive identifiers. | User-provided local config |
| `current_reference/PaperTradingv2/telegramtoken.txt` | None | Do not transfer | Secret token must never be copied into R1000 source. | User-provided local secret |
| `current_reference/PaperTradingv2/flex_config.json` | None | Do not transfer | IBKR Flex credentials/config are local secrets. | User-provided local secret |
| `current_reference/PaperTradingv2/bot_state.json` | None | Do not transfer | Old live state conflicts with R1000 runtime state. | `state_store.py` |
| `current_reference/PaperTradingv2/bot_log.txt` | None | Do not transfer | Old runtime log is generated operational evidence. | `logger_utils.py` |
| `config/manual_trading_watchlist.xlsx` | `config/manual_trading_watchlist.xlsx` | Adapt | The owner-approved 2607 manual watchlist is reused for migrated R1000 BUY Limit and BUY Market options. | `manual_control_console.py` |

## Launcher And Script Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `run/start_system.bat` | `run/start_system.bat` | Adapt | Preserve full-system launch behavior while changing paths and process names to R1000. | `start_bot.bat`, Telegram launcher |
| `run/start_system_desktop.pyw` | `run/start_system_desktop.pyw` | Adapt | Preserve no-console desktop launch UX while pointing to R1000 files. | `start_system.bat` |
| `run/stop_system.bat` | `run/stop_system.bat` | Adapt | Preserve graceful stop behavior while targeting R1000 controller and listener. | Control files |
| `run/start_bot.bat` | `run/start_bot.bat` | Adapt | Preserve owner confirmation and paper-safety preflight while launching R1000 controller. | `startup_validation.py` |
| `run/start_bot_desktop.pyw` | `run/start_bot_desktop.pyw` | Adapt | Preserve desktop bot launcher while changing R1000 paths and entry-point checks. | `start_bot.bat` |
| `run/stop_bot.bat` | `run/stop_bot.bat` | Adapt | Preserve bot stop request behavior while changing R1000 paths. | `control_utils.py` |
| `run/start_detached_controller.py` | `run/start_detached_controller.py` | Adapt | Preserve detached controller startup while pointing to R1000 package and controller. | `operational_controller.py` |
| `run/operational_controller.bat` | `run/operational_controller.bat` | Adapt | Preserve controller wrapper while changing package path. | `operational_controller.py` |
| `run/health_supervisor.bat` | `run/health_supervisor.bat` | Adapt | Preserve health supervisor wrapper while changing package path. | `health_supervisor.py` |
| `run/status_bot.bat` | `run/status_bot.bat` | Adapt | Preserve quick status output while reading R1000 health/status files. | `system_status.ps1` |
| `run/system_status.bat` | `run/system_status.bat` | Adapt | Preserve status wrapper while using R1000 status script. | `system_status.ps1` |
| `run/system_status.ps1` | `run/system_status.ps1` | Adapt | Preserve system status checks while changing bot process and paths. | Runtime status files |
| `run/control_console.bat` | `run/control_console.bat` | Adapt | Preserve manual console launcher while pointing to R1000 console. | `manual_control_console.py` |
| `run/telegram_listener.bat` | `run/telegram_listener.bat` | Adapt | Preserve Telegram listener wrapper while changing package path. | `telegram_listener.py` |
| `run/start_telegram_listener.pyw` | `run/start_telegram_listener.pyw` | Adapt | Preserve no-console listener startup while changing R1000 paths. | `telegram_listener.bat` |
| `run/stop_telegram_listener.bat` | `run/stop_telegram_listener.bat` | Adapt | Preserve listener stop behavior while targeting R1000 pid/control files. | Telegram runtime state |
| `run/ibkr_reconciliation.bat` | `run/ibkr_reconciliation.bat` | Adapt | Preserve IBKR reconciliation launcher while writing R1000 reports. | `ibkr_reconciliation.py` |
| `run/reconciliation.bat` | `run/reconciliation.bat` | Adapt | Preserve reconciliation wrapper while targeting R1000 reconciliation. | `reconciliation.py` |
| `run/dashboard.bat` | `run/dashboard.bat` | Adapt | Preserve dashboard launcher while showing R1000 status. | `dashboard_basic.py` |
| `run/edit_config.bat` | `run/edit_config.bat` | Replace | Old config editor launcher targets retired strategy config. | New config editor or docs |
| `run/open_reports_logs.bat` | `run/open_reports_logs.bat` | Adapt | Preserve operator shortcut while changing report/log locations. | Runtime dirs |
| `run/check_ibkr_api_port.py` | `run/check_ibkr_api_port.py` | Adapt | Preserve IBKR API-port diagnostic while changing package path. | `gateway_status.py` |
| `run/gateway_recovery_test.py` | `run/gateway_recovery_test.py` | Adapt | Preserve gateway recovery diagnostics while updating package path and labels. | `gateway_status.py` |
| `run/install_scheduled_tasks.ps1` | `run/install_scheduled_tasks.ps1` | Adapt | Preserve validation/install tooling only for approved manual-control tasks and never for automatic trading start. | Owner approval |
| `run/validate_scheduled_tasks.ps1` | `run/validate_scheduled_tasks.ps1` | Adapt | Preserve scheduled-task validation while checking R1000 task names and non-auto-start policy. | `install_scheduled_tasks.ps1` |
| `run/reset_paper_validation.ps1` | `run/reset_paper_validation.ps1` | Adapt | Preserve paper-validation reset pattern while clearing only R1000 generated evidence. | Runtime dirs |
| `run/release1_smoke_test.ps1` | `run/release1_smoke_test.ps1` | Replace | Old release smoke test does not represent R1000 acceptance criteria. | R1000 tests |
| `run/archive_project_conversations.bat` | None | Do not transfer | Conversation archival is not part of the trading runtime migration. | None |

## Analytics Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `analytics/__init__.py` | `analytics/__init__.py` | Reuse unchanged | Package marker has no strategy behavior. | None |
| `analytics/flex_analytics/__init__.py` | `analytics/flex_analytics/__init__.py` | Reuse unchanged | Package marker has no strategy behavior. | None |
| `analytics/flex_analytics/cli.py` | `analytics/flex_analytics/cli.py` | Adapt | Preserve CLI flow while updating project names, paths, and report labels. | Analytics config |
| `analytics/flex_analytics/config.py` | `analytics/flex_analytics/config.py` | Adapt | Preserve analytics directory conventions while updating R1000 roots and local Flex config lookup. | Local Flex config |
| `analytics/flex_analytics/downloader.py` | `analytics/flex_analytics/downloader.py` | Reuse unchanged | Flex download behavior is broker-reporting logic, not strategy logic. | Analytics config |
| `analytics/flex_analytics/normalize.py` | `analytics/flex_analytics/normalize.py` | Reuse unchanged | Flex normalization is independent of Tradingbot2607 strategy. | None |
| `analytics/flex_analytics/storage.py` | `analytics/flex_analytics/storage.py` | Adapt | Preserve storage model while ensuring R1000 report identities and schemas are compatible. | Normalizer |
| `analytics/flex_analytics/reporting.py` | `analytics/flex_analytics/reporting.py` | Adapt | Preserve workbook/report generation while updating titles and R1000-specific evidence. | Storage, Excel feeds |
| `analytics/flex_analytics/excel_feeds.py` | `analytics/flex_analytics/excel_feeds.py` | Adapt | Preserve feed generation while updating workbook names and R1000 feed labels. | Storage |
| `analytics/flex_analytics/validate_report.py` | `analytics/flex_analytics/validate_report.py` | Reuse unchanged | Report accuracy validation is independent of strategy if workbook schemas remain compatible. | Reporting |
| `analytics/run_daily_flex_analytics.bat` | `analytics/run_daily_flex_analytics.bat` | Adapt | Preserve scheduled/manual analytics launcher while changing project paths. | Analytics CLI |
| `analytics/schedule_daily_flex_analytics.ps1` | `analytics/schedule_daily_flex_analytics.ps1` | Adapt | Preserve analytics scheduling only as standalone reporting, not trading runtime control. | Analytics launcher |
| `analytics/create_trading_performance_workbook.ps1` | `analytics/create_trading_performance_workbook.ps1` | Adapt | Preserve workbook creation utility while changing R1000 paths and titles. | Reporting module |
| `analytics/tests/test_daily_flex_analytics.py` | `tests/analytics/test_daily_flex_analytics.py` | Adapt | Preserve analytics coverage while updating paths and expected report labels. | Analytics package |
| `analytics/data/**/.gitkeep` | `analytics/data/**/.gitkeep` | Replace | Directory placeholders may be recreated, but old data must not be transferred. | Analytics config |
| `analytics/database/.gitkeep` | `analytics/database/.gitkeep` | Replace | Placeholder may be recreated, but old databases must not be transferred. | Analytics config |

## Test Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `tests/test_execution_history_refresh.py` | `tests/test_execution_history_refresh.py` | Adapt | Preserve execution-history refresh guarantees with R1000 report schemas. | `execution_history.py` |
| `tests/test_ibkr_api_port_preflight.py` | `tests/test_ibkr_api_port_preflight.py` | Adapt | Preserve IBKR API preflight coverage with R1000 paths. | `startup_validation.py` |
| `tests/test_long_only_order_safety.py` | `tests/test_long_only_order_safety.py` | Adapt | Preserve long-only and duplicate-order safety coverage. | `order_safety.py` |
| `tests/test_p0_gateway_status.py` | `tests/test_p0_gateway_status.py` | Adapt | Preserve gateway readiness coverage with R1000 status fields. | `gateway_status.py` |
| `tests/test_release2_manual_console.py` | `tests/test_manual_console.py` | Adapt | Preserve operator-control safety tests while removing old watchlist assumptions where needed. | `manual_control_console.py` |
| `tests/test_release3_api_snapshot.py` | `tests/test_operational_api_snapshot.py` | Replace | Retired Release 3 snapshot tests should target current operational snapshot behavior. | `operational_api_snapshot.py` |
| `tests/test_release3_flex_client.py` | `tests/test_flex_client.py` | Adapt | Preserve Flex client tests with R1000 paths. | `ibkr_flex_client.py` |
| `tests/test_release3_flex_normalizer.py` | `tests/test_flex_normalizer.py` | Adapt | Preserve Flex normalization tests. | `flex_normalizer.py` |
| `tests/test_release3_reporter.py` | `tests/test_reporter.py` | Adapt | Preserve broker-authoritative reporting tests while adding R1000 evidence expectations. | `reporter.py` |
| `tests/test_release4_telegram_alerts.py` | `tests/test_telegram_alerts.py` | Adapt | Preserve Telegram alert rendering tests with R1000 event names. | `telegram_alerts.py` |
| `tests/test_release4_telegram_monitoring.py` | `tests/test_telegram_monitoring.py` | Adapt | Preserve read-only Telegram monitoring tests with R1000 status content. | `telegram_commands.py` |
| `tests/test_release5_strategy_config.py` | `tests/test_strategy_configuration.py` | Replace | Old configurable trailing/rebuy strategy tests conflict with fixed R1000 strategy constants. | `config_loader.py`, `strategy.py` |
| `tests/test_runtime_restart_hardening.py` | `tests/test_runtime_restart_hardening.py` | Adapt | Preserve restart-hardening tests while targeting R1000 process names. | `operational_controller.py` |

## Documentation And Top-Level File Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `.gitattributes` | `.gitattributes` | Adapt | Preserve line-ending policy only if compatible with current R1000 Git settings. | Git repo |
| `.gitignore` | `.gitignore` | Do not transfer | R1000 already has a project-specific `.gitignore`. | Current repo |
| `README.md` | `README.md` | Replace | Old README is not meaningful for R1000. | Project spec |
| `requirements.txt` | `requirements.txt` | Adapt | Preserve needed runtime dependencies while removing unused old-project packages. | Runtime modules |
| `requirements-lock.txt` | `requirements-lock.txt` | Adapt | Regenerate only after R1000 dependencies are confirmed. | `requirements.txt` |
| `STARTBOT.txt` | `STARTBOT.txt` | Adapt | Preserve operator-start instructions while changing commands and paths. | Run scripts |
| `RESTORE_INSTRUCTIONS.txt` | `RESTORE_INSTRUCTIONS.txt` | Replace | Restore instructions must describe R1000 backups and release evidence, not 2607. | Release process |
| `docs/Architecture_v1.md` | `docs/ARCHITECTURE_BASELINE.md` | Do not transfer | R1000 already has an architecture baseline derived from the current audit. | Current docs |
| `docs/Target_Architecture.md` | `docs/TARGET_ARCHITECTURE.md` | Adapt | Preserve target-architecture style only after R1000 modules exist. | Migration completion |
| `docs/Runbook_v1.md` | `docs/RUNBOOK.md` | Adapt | Preserve operational runbook structure while changing commands and health files. | Run scripts |
| `docs/IBKR_Operations.md` | `docs/IBKR_OPERATIONS.md` | Adapt | Preserve IBKR operational guidance while removing 2607-specific paths. | IBKR modules |
| `docs/Manual_Control_Console_Guide.md` | None | Do not transfer | The old separate operator guide is replaced by the single R1000 operating manual. | `docs/OPERATING_MANUAL.md` |
| `docs/Release_Plan.md` | `docs/RELEASE_PLAN.md` | Adapt | Preserve release discipline while defining R1000 validation gates. | Tests |
| `docs/Migration_Checklist_v1.md` | `docs/MIGRATION_MATRIX.md` | Do not transfer | This matrix supersedes the old migration checklist. | None |
| `docs/PROJECT_STATE.md` | None | Do not transfer | Old project state is historical and not R1000 source of truth. | None |
| `docs/PROJECT_HANDOVER.md` | None | Do not transfer | Old handover document is historical reference only. | None |
| `docs/Master_Project_Status.md` | None | Do not transfer | Old status document describes Tradingbot2607. | None |
| `docs/Current_System_Status.md` | None | Do not transfer | Old live status is historical evidence. | None |
| `docs/OPEN_ISSUES_MASTER.md` | None | Do not transfer | Old issues may not apply and must not drive R1000 implementation. | None |
| `docs/OpenIssues.md` | None | Do not transfer | Old issue list is historical only. | None |
| `docs/ChangeLog.md` | `docs/CHANGELOG.md` | Replace | R1000 needs its own changelog history. | Release process |
| `docs/Project_History.md` | None | Do not transfer | Old project history should remain in the 2607 reference. | None |
| `docs/Durable_Project_History.md` | None | Do not transfer | Historical 2607 narrative is not R1000 implementation source. | None |
| `docs/Release_01_Completion_Report.md` | None | Do not transfer | Old release report is evidence only. | None |
| `docs/Release_1_Verification.md` | None | Do not transfer | Old verification report is evidence only. | None |
| `docs/Release_02_Completion_Report.md` | None | Do not transfer | Old release report is evidence only. | None |
| `docs/Release_02_Test_Record.md` | None | Do not transfer | Old test record is evidence only. | None |
| `docs/Release2_Summary.md` | None | Do not transfer | Old release summary is evidence only. | None |
| `docs/Release_03_Kickoff.md` | None | Do not transfer | Old release kickoff is evidence only. | None |
| `docs/Release_03_01_IBKR_Official_Reporting.md` | `docs/IBKR_REPORTING_REFERENCE.md` | Adapt | Preserve broker-reporting concepts only as R1000 reporting guidance. | Reconciliation modules |
| `docs/Release_03_02_Flex_Data_Dictionary.md` | `docs/FLEX_DATA_DICTIONARY.md` | Adapt | Preserve Flex field definitions if still compatible with current IBKR output. | Flex modules |
| `docs/Release_03_Completion_Report.md` | None | Do not transfer | Old release completion report is evidence only. | None |
| `docs/release5_codex_conversation.md` | None | Do not transfer | Conversation transcript is historical evidence and not an implementation artifact. | None |
| `docs/IBKR_Trading_System_Implementation_Plan_v1.md` | None | Do not transfer | Old implementation plan is superseded by R1000 project specification and this matrix. | None |
| `docs/DataIBKR.txt` | None | Do not transfer | Data notes are reference-only and must not override the approved strategy. | None |
| `docs/Can you access the repository ainergiconsulting.docx` | None | Do not transfer | Repository-access conversation artifact is not application documentation. | None |

## Operator Shortcut Matrix

| Source path | Destination path in TradingbotR1000 | Action | Justification | Dependency |
|---|---|---|---|---|
| `TradingBot_Control/Start Trading System.lnk` | `TradingbotControl/Start Trading System.lnk` | Replace | Shortcut starts the complete R1000 runtime in the background. | `run/start_trading_system.bat` |
| `TradingBot_Control/Stop Trading System.lnk` | `TradingbotControl/Stop Trading System.lnk` | Replace | Shortcut is the only supported clean shutdown application. | `run/stop_trading_system.bat` |
| `TradingBot_Control/Manual Console.lnk` | `TradingbotControl/Control Console.lnk` | Replace | Shortcut opens the single operational interface without affecting the running bot. | `run/control_console.bat` |
| `TradingBot_Control/STARTBOT.txt - Shortcut.lnk` | `TradingbotControl/Operating Manual.lnk` | Replace | Shortcut opens the simplified operating manual. | `docs/OPERATING_MANUAL.md` |

## Implementation Order

1. Establish R1000 package/config skeleton and preserve current approved strategy module.
2. Migrate generic utilities and adapt config/path dependencies.
3. Replace old strategy engine with R1000 daily scan, selection, order-plan, and exit workflow.
4. Adapt IBKR integration, order safety, state, runtime health, and controller around the new engine.
5. Adapt Telegram, reconciliation, reporting, analytics, and operator launchers.
6. Port/adapt tests in the same order and keep old Tradingbot2607 generated evidence out of source control.
7. Recreate operator shortcuts and local secrets/templates only after runtime paths are final.

This matrix is intended to remove further architectural decision-making before
implementation; remaining choices should be implementation details bounded by
`docs/PROJECT_SPECIFICATION.md` and the approved strategy DOCX.

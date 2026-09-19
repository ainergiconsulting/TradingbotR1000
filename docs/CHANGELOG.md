# TradingbotR1000 Changelog

## 2026-07-21

- Migrated the Tradingbot2607 operational architecture into the R1000 package
  shape.
- Preserved the approved TradingbotR1000 strategy specification as the trading
  authority.
- Added R1000 dry-run scan, order-plan, state, monitoring, reconciliation,
  analytics, launcher, and test scaffolding.
## 2026-09-11 - No-leverage cash cap restored

- Corrected Operational Buy Budget to use `min(cash, AvailableFunds, LookAheadAvailableFunds)` before the strategic ceiling and 1% safety margin.
- Prevents IBKR margin capacity from inflating BUY sizing after positions already exist.
- Added regression coverage reproducing the live failure mode where cash was about $261k while AvailableFunds was about $813k.
- Updated Operating Manual, IBKR Operations, Project Specification, code documentation, and Master History.

## 2026-09-13 — IBKR health/alert state hardening
- Persistent IBKR API timeouts are now promoted to `DEGRADED` after 3 consecutive supervisor cycles instead of remaining silently `UNKNOWN`.
- A `DEGRADED` episode emits one `ibkr_degraded` Telegram alert; hard socket/Gateway loss emits `ibkr_disconnected`; recovery emits `ibkr_reconnected`.
- Supervisor `status` is no longer `OK` merely because the heartbeat is fresh: it now reports `IBKR_UNKNOWN`, `DEGRADED_IBKR`, `IBKR_DISCONNECTED`, or `STALE_HEARTBEAT` when applicable.
- Added focused regression tests for timeout degradation, hard disconnect and recovery transitions.


## 2026-09-17 — Mobile/order pipeline full repair
- Canonicalized mobile position fields at the API boundary so average cost, market price/value and unrealized P&L use the same broker snapshot as Telegram.
- Added a final broker-authoritative long-only SELL guard immediately before automated `placeOrder`, in addition to planning-time position validation.
- Preserved strict separation between local PLANNED intents and broker PENDING/SUBMITTED orders.
- Mobile broker mutations remain disabled pending controlled acceptance.


## 2026-09-17 - Complete operational repair and order-lifecycle hardening
- Mobile position schema normalized: average_cost, market_price, market_value, unrealized_pnl and realized_pnl are populated from IBKR camelCase fields while retaining compatibility aliases. Live verification returned full ABNB values rather than N/A.
- Market-hours path verified against IBKR server time; ABNB returned known=true, trading_open=true, liquid_open=true, time_source=IBKR_SERVER_TIME. tzdata/US-Eastern resolution verified working in production venv.
- Long-only SELL safety hardened at final broker submission boundary. Immediately before placeOrder, fresh broker positions and all open orders are re-read; pending SELL quantity is deducted; any SELL producing projected position < 0 fails closed. A synthetic stale BRKR SELL with no live position was rejected with broker_orders_transmitted=0.
- Automated SELL submission now uses OrderIntentGuard around the final placeOrder boundary and records uncertain submission outcomes rather than incorrectly labelling an exception as a definite rejection.
- Telegram status separates current valid plans from stale/blocked SELL plans; portfolio Pending orders are broker-open orders, not merely local plans.
- Reconciliation hardened: locally active orders with broker IDs that disappear from a fresh complete broker open-order snapshot no longer remain permanently PreSubmitted. They transition to UnknownFinal without fabricating an unsupported cancellation cause.
- Mobile manual mutations remain disabled (MOBILE_MANUAL_MUTATIONS_ENABLED=0).

VALIDATION:
- Operational targeted regression suite: 54 tests, all passed.
- Full project discovery: 70 operational/strategy tests passed; 4 unrelated backtest/short-strategy import/setup errors remain because optional/missing backtest modules/files are absent. These are outside live TradingbotR1000 operational code and were not treated as operational failures.
- Live read-only IBKR check: current position ABNB 1176; zero open orders.
- Synthetic phantom BRKR SELL dry run: rejected no_live_position_quantity; proof_no_broker_order_transmitted=true.
- Controller intentionally remains STOPPED during repair/acceptance; no live/paper broker order was transmitted by this repair.

DESIGN DECISION REQUIRED FOR FUTURE ENTRY ORDERS:
Automated entry orders are currently DAY by explicit code. If strategy intent is instead to keep an unfilled limit order beyond the session, that is a strategy/order-policy change (e.g. GTC or controlled resubmission) and must be decided explicitly rather than silently changed during a repair.

FINAL VERIFICATION ADDENDUM 2026-09-17:
- A subsequent live read-only sample exposed an intermittent race: positions could arrive before IBKR portfolio market/P&L fields, yielding N/A. operational_api_snapshot.snapshot_positions was hardened with a bounded wait for portfolio updates on the already-connected read-only session.
- After mobile-console restart, two consecutive live samples returned ABNB qty 1176, averageCost 169.305003, marketPrice 165.57772825, marketValue 194719.41, unrealizedPNL -4383.28; open orders 0 in both samples.
- Final operational regression suite repeated after this change: 54/54 tests passed.
- Final service state: controller INACTIVE intentionally; mobile console ACTIVE; Telegram ACTIVE; health supervisor/execution monitor/IB Gateway ACTIVE. No order was transmitted during repair verification.

## 2026-09-17 — Daily-cycle watchdog and health-probe hardening
- Forensics confirmed the 2026-09-17 strategy cycle did not run because the controller was intentionally stopped at 13:22:55 UTC during repair work, before the configured 09:28 ET / 13:28 UTC cycle. The daily market-data refresh itself completed OK at 12:44:28 UTC with 1017/1017 symbols current through 20260916.
- Added an independent health-supervisor watchdog: on an eligible US session, if the configured daily strategy cycle has not been recorded within 15 minutes after 09:28 ET, health becomes `STRATEGY_CYCLE_MISSED` (when IBKR/heartbeat do not already indicate a higher-priority fault) and a deduplicated `strategy_cycle_missed` alert is emitted. This prevents a missed trading day from remaining silent.
- Confirmed recurring `completed orders request timed out` lines came from ib_insync's optional connect-time completed-order synchronization in the read-only health probe, not from the strategy scheduler. The probe remains broker-read-only and suppresses that known library warning locally while still validating the actual requested health evidence.
- Corrected PROJECT_SPECIFICATION schedule drift from 09:35 ET to the actual configured/tested 09:28 ET.
- Automated PAPER activation preflight passed with current PAPER account, connected IBKR API, RECONCILED broker state, zero open orders, and current market data. Controller remains stopped until final acceptance/restart verification is complete.
- Final Sep-17 readiness: 76/76 operational/support tests passed. Isolated no-transmission end-to-end scan against current data found RVMD/NTRS/MS/IVZ and reconciled cleanly with 0 broker transmissions.
- Added one-shot `tradingbot-controller-resume.timer` for 2026-09-18 11:45 UTC (07:45 ET), intentionally before the 08:30 ET data refresh and 09:28 ET cycle. Controller is not started late on Sep-17 because scheduler catch-up semantics would execute today's missed cycle immediately.
- Restored canonical automated execution report after synthetic BRKR safety test contamination, using durable Sep-16 automated-order evidence.

## 2026-09-18 - Stale Telegram plan status corrected
- Forensic review confirmed automated BUY LIMIT tif=DAY is an established accepted policy, introduced after IBKR warning 10349 on 2026-08-28 and exercised in the 2026-08-31 PAPER end-to-end acceptance. No GTC/carry-forward strategy change was made.
- Corrected Telegram /status: saved BUY plans from an earlier ET date are no longer labelled PLANNED / CURRENTLY VALID; they are shown as STALE / NOT CURRENT.
- Added regression coverage proving a previous-day BUY plan produces Orders currently valid: 0.
- Sep-16 BNY/JHX/NTRS exact final broker cancellation/expiry timestamp remains unavailable from retained evidence; no fabricated cause is assigned.

## 2026-09-18 - Pre-session runtime/status correction
- Removed previous-day strategy plans entirely from Telegram /status; historical plans are not operational status.
- Started the controller before the scheduled cycle after proving is_cycle_due=False, eliminating the misleading STOPPED runtime and stale heartbeat while preserving the normal 08:30 ET refresh / 09:28 ET cycle.
- Removed the obsolete 07:45 ET one-shot resume timer after starting the controller.
- Live verification: Runtime RUNNING, heartbeat fresh, Gateway/API connected, reconciliation RECONCILED, zero current orders; Trading enabled remains false only because the US market is currently closed/outside liquid hours.

## 2026-09-18 - Telegram status semantics clarified
- /status no longer mixes the previous completed scan's Selected count with today's current-order count.
- Before today's 09:28 ET strategy cycle, /status explicitly reports Today's scan: NOT RUN YET, Last completed scan, Selected today: 0, Orders currently valid: 0.
- After today's scan, the existing current-cycle branch reports today's selected count and current plan details.

## 2026-09-18 - Pre-scan status no longer implies zero candidates
- Before the scheduled 09:28 ET strategy cycle, Telegram /status now reports Today's scan: PENDING and Selected today: N/A (not evaluated yet), rather than zero.
- This prevents interpreting a not-yet-run scan as a completed scan with no qualifying securities.

## 2026-09-18 - Scan timing rationale documented
- Clarified that the strategy uses completed daily bars from the prior completed US session; 09:28 ET is not a strategy-data requirement.
- Git history confirms 09:28 ET was introduced as a pre-open computation time paired with separate 09:30 ET order transmission.
- The execution path refreshes live account/positions/open orders again immediately before transmission, so broker-state freshness does not require the signal scan itself to wait until 09:28.
- No timing change applied yet; decoupling candidate generation from market-open transmission is now explicitly documented for operator decision.

## 2026-09-18 - Weekend scan/execute decoupling work scheduled
- No production behavior change today.
- Added docs/WEEKEND_SCAN_DECOUPLING_PLAN_2026-09-19.md with the implementation, test and acceptance plan for separating post-refresh strategy PREPARE from 09:30 ET broker EXECUTE.
- Work is scheduled to begin Saturday 2026-09-19 and finish before the US market reopens Monday 2026-09-21.


## 2026-09-19 - Weekend scope corrected to minimal early order evaluation

- The broad PREPARE/EXECUTE redesign was abandoned before promotion. The operator clarified that only the timing of order evaluation/disclosure should change; the proven 09:28 strategy cycle and 09:30 broker execution path should remain unchanged.
- Added a read-only `--preview-only` strategy evaluation immediately after the successful 08:30 ET daily-bar refresh.
- The preview writes `reports/preopen_preview_report.json` and sends Telegram details for all planned BUY/SELL orders, including planned quantity and LIMIT price where applicable, with `Broker submitted: 0`.
- The regular 09:28 scan and the existing 09:30 broker-processing/reconciliation block are unchanged and remain authoritative if account state changes after the preview.
- Git verification confirms `automated_broker.py`, `automated_order_store.py`, `order_safety.py` and `strategy_scheduler.py` are identical to main; the execution block in `trading_engine.py` is byte-identical to main.
- Real-data Sep-18 equivalence replay: preview selected HSIC/LAD/PNC/VZ with the exact same 82.49/312.03/225.05/46.88 LIMIT prices as the accepted regular scan.
- Isolated preview verification proved that `wait_until_order_transmission_time()` and `process_order_plan()` are not reached, canonical scan/order/execution report hashes are unchanged, and live PAPER broker state is unchanged.
- Expanded operational/support suite passed 87/87; full discovery still reports only the same four pre-existing optional backtest/short-strategy setup/import errors.
- Because the broker execution path is unchanged, no new live order acceptance is required solely for this feature.


## 2026-09-19 - Minimal preview promoted to main

- The verified minimal early-order-preview implementation was fast-forwarded to `main` at commit `b57a1c0` and pushed; local and remote `main` match.
- The superseded broad refactor branches were deleted locally and remotely to prevent accidental deployment.
- Telegram and health-supervisor services were restarted after promotion so they are running code from current `main`.
- No broker order was transmitted during implementation or verification.
- The trading controller remains inactive and systemd-disabled from the acceptance hold. SentinelX policy currently permits status/restart but not a direct `start` action for this service; that restriction was not bypassed.

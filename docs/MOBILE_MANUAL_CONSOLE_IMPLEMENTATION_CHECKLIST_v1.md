# Mobile Manual Console - Implementation Checklist v1

Date: 2026-09-14
Status: ACTIVE IMPLEMENTATION CHECKLIST

Canonical implementation order: B -> C -> D -> E -> F -> G -> H -> I -> J -> K.

A. Architecture baseline - COMPLETE
- Private PWA on Hetzner through Tailscale and HTTPS.
- Application authentication with passkey/WebAuthn preferred.
- Server-side inactivity session policy.
- No IBKR credentials on phone.
- PC and mobile use the same Manual Trading Core.
- Preserve PC order workflow.
- BUY: searchable R1000 selector.
- SELL: only currently held positions, revalidated at broker before submission.

B. Prepare existing system - COMPLETE (2026-09-14)
- [x] Preserved current manual_control_console.py as docs/manual_control_console.reference_20260914.py before refactor.
- [x] Identified reusable broker/safety layer vs interactive UI layer. Reusable/core candidates occupy the connection/account/broker-state/contract/market-price/market-hours/position-validation/order/cancel/liquidation functions; interactive PC UI begins principally with confirmation/input/print/select helpers and _interactive_order/menu/run_console.
- [x] No automatic strategy/scheduler/investment logic altered.
- [x] Dedicated manual IBKR client ID verified: 1001. Automatic=1000, reconciliation=1002, remote-control=1003; no service environment override detected.
- [x] Port 4002 exposure checked at host firewall: IB Gateway listens on *:4002, but UFW/nftables INPUT policy is DROP and only SSH/22 is allowed inbound. No 4002 allow rule exists. Keep final external reachability check in acceptance and consider loopback/restricted bind if IB Gateway configuration permits without operational regression.

C. Shared Manual Trading Core - COMPLETE BASELINE (2026-09-14)
- [x] Created canonical shared module current_reference/PaperTradingR1000/manual_trading_core.py from the frozen, previously operational PC console implementation.
- [x] Converted manual_control_console.py into a compatibility wrapper that exports the same functions/objects and invokes the same run_console entry point.
- [x] Account Summary; Positions; Open Orders; Market/Liquid Hours remain provided by the shared core.
- [x] Current prices and suggested LIMIT price remain provided by the shared core.
- [x] BUY/SELL Market and Limit remain provided by the shared core.
- [x] Cancel selected/all and liquidate selected/all remain provided by the shared core.
- [x] Investable Capital Control, Execution History and audit logging remain in the shared core.
- [x] Long-only/order-safety behavior remains unchanged from the frozen reference implementation.
- [x] Python compilation/import identity checks passed; wrapper exports the same core callables; manual client ID remains 1001 and all 15 menu choices remain available.
- [x] Controlled no-order PC-console startup passed: connected to 127.0.0.1:4002 with client 1001, displayed the unchanged menu, and exited with code 0 without submitting an order.
- [x] Read-only live core smoke test passed: account summary available, 4 positions observed, 0 open orders observed. No broker-mutating function was invoked.
- [ ] Full automated regression suite not run because pytest is not installed in the existing venv. Do not install it solely for this block; add focused tests during API/mobile implementation if required.
- NOTE: IBKR emitted the pre-existing/non-fatal message 'completed orders request timed out' during disconnect/startup smoke tests; connection and requested read-only state succeeded. Track separately if it becomes operationally relevant.

D. Mobile safety - CORE PRIMITIVES COMPLETE (2026-09-14)
- [x] Persistent mobile request-ID reservation added to shared Manual Trading Core.
- [x] Duplicate request IDs are rejected/returned as duplicates before broker mutation, providing deterministic double-tap/retry protection for the future API.
- [x] Mobile request states persist server-side and support RESERVED, SUBMITTING, UNKNOWN_PENDING_RECONCILIATION and terminal/completed states.
- [x] SUBMITTING and UNKNOWN_PENDING_RECONCILIATION are explicitly fail-closed and require reconciliation before retry.
- [x] Broker order path now distinguishes failures before confirmed submission from exceptions after ib.placeOrder() returned.
- [x] Any exception after ib.placeOrder() returns is classified as BrokerActionUncertainError / UNKNOWN_PENDING_RECONCILIATION with available orderId/permId/clientId retained for reconciliation; caller must not retry blindly.
- [x] Existing persistent order-intent guard verified to block duplicate active intents; it remains the lower-level broker/order-safety protection and is not duplicated.
- [x] Synthetic no-broker-mutation tests passed for duplicate request IDs, persistent active-intent duplicate blocking, fail-closed SUBMITTING state and simulated lost acknowledgement after broker submission.
- [ ] Wire these primitives into Mobile Manual API mutation endpoints; reserve request ID before invoking any mutating core function and update state from observed outcome.
- [ ] Implement broker reconciliation routine using orderId/permId plus open orders/executions before clearing UNKNOWN_PENDING_RECONCILIATION.
- [ ] Add recent re-authentication requirements for destructive mobile actions in the authentication/API layer.

E. Russell 1000 selector - COMPLETE DATA/SEARCH LAYER (2026-09-14)
- [x] Reuse canonical repository-root IWB_holdings.csv maintained by existing weekly official iShares IWB refresh; no second universe source introduced.
- [x] Current validated universe contains 1018 unique USD Equity symbols (holdings as of 2026-09-11; refreshed on server 2026-09-14).
- [x] Added current_reference/PaperTradingR1000/mobile_r1000_selector.py as lightweight reusable selector/search layer.
- [x] Selector exposes canonical symbol, IBKR symbol, company name, sector, exchange, expected IBKR primary exchange and currency; it deliberately ignores portfolio weights/market values for mobile instrument selection.
- [x] Existing symbol_mapping.py is reused for class-share symbols (e.g. BRK.B -> IBKR BRK B, HEI.A -> HEI A); no duplicate symbol-normalization logic introduced.
- [x] Search ranks exact ticker first, then ticker prefix/substring, then company-name matches; results are capped (max 100) so the phone does not need a flat thousand-row primary view.
- [x] Universe loader is cached by file mtime/size and automatically sees a newly refreshed IWB file without changing the existing refresh process.
- [x] Fail-closed validation requires expected columns and a validated 950-1100 USD-equity universe size.
- [x] Tests passed with 1018 entries and ticker/name/class-share queries including NV, NVIDIA, BRK.B/BRK B, BERK and HEI.A.
- [x] BUY membership lookup available via get_r1000_symbol().
- [x] SELL remains outside this selector by design: Mobile SELL source is current broker positions only and will be implemented in the API/UI from broker state.
- [ ] Optional Recent/Favorites views are UI conveniences only; defer until PWA implementation and add only if they improve usability.

F. Mobile API and PWA - LOCAL READ-ONLY BASELINE COMPLETE (2026-09-14)
- [x] FastAPI 0.141.1 and Uvicorn 0.53.0 installed in the existing TradingBotR1000 venv as the minimal web-service dependencies; no separate nginx/web stack introduced.
- [x] Added mobile_api.py and mobile_pwa/ with responsive phone UI, web manifest and service-worker baseline.
- [x] API tested bound ONLY to 127.0.0.1:8765; it was not exposed through Tailscale or the public Internet in this block.
- [x] Startup/status path reports Gateway socket, IBKR API, manual client ID, PAPER/unknown account mode and whether broker mutations are enabled.
- [x] Read-only endpoints implemented/tested for Account Summary, Positions, Open Orders, latest executions, R1000 search/membership and market-hours lookup.
- [x] PWA navigation baseline: Account / Positions / Orders / BUY R1000 / Executions / Controls.
- [x] R1000 search is phone-oriented and uses the Block E selector; SELL source is explicitly the current broker Positions page, never the R1000 list.
- [x] IBKR access is serialized through one dedicated worker thread/client so ib_insync keeps a consistent event loop; live read-only test connected as manual client 1001 to PAPER account and returned account plus 4 positions.
- [x] All POST API paths are deliberately locked with HTTP 423 in this build; no broker mutation endpoint is active before Block G authentication and Block D request/reconciliation wiring.
- [x] Local smoke test: /api/status, /api/account, /api/positions, R1000 BRK.B search and PWA root all succeeded; server listened only on loopback. Test server was stopped afterward.
- [ ] Full PC-style BUY/SELL/cancel/liquidation interaction controls will be enabled only after Block G authentication and the remaining Block D mutation lifecycle/reconciliation are wired.
- [ ] Add final PWA icon assets and installability polish when phone/Tailscale access is enabled.
- NOTE: existing non-fatal 'completed orders request timed out' IBKR message was again observed during initial connection; read-only requests succeeded.

G. Authentication and sessions
- Install/configure Tailscale server and phone.
- Tailscale Serve HTTPS; no public Funnel.
- Restrict authorized identity/device access.
- Configure passkey/WebAuthn and secure server-side session cookie.
- No persistent remember-me.
- Approx. 10-15 minutes genuine inactivity timeout; automatic polling never extends it.
- Document lost-phone revocation/new-phone enrollment.

H. Operational service
- Dedicated systemd service with controlled startup/restart/health and separate logs.
- Mobile-service failure/restart/reboot must not create broker actions or interfere with automatic bot.

I. Technical tests without orders
- Authentication/session; account/positions/orders; R1000 search; prices/hours/executions.
- Network/Tailscale/IBKR disconnects; session expiration; double tap; restart; audit verification.

J. Controlled PAPER acceptance
- Small BUY LIMIT including default and edited price; cancel; controlled BUY MARKET.
- SELL LIMIT/MARKET only from held positions; SELL all where supported; oversell rejected.
- Duplicate protection; capital validation; outside-hours behavior.
- Controlled uncertain-response/reconciliation test.
- Cross-check Mobile vs PC vs IBKR; audit log; selected liquidation; emergency-all only in prepared PAPER conditions.

K. Final acceptance
- No unwanted orders or regressions.
- No public console/IBKR API exposure.
- Tailscale/passkey/device revocation verified.
- Restart/recovery and UNKNOWN reconciliation verified.
- Documentation and Master History updated.
- Declare MOBILE MANUAL CONSOLE PAPER ACCEPTED only after all gates pass.


## Block H — Canonical operational snapshot, execution ledger and P&L (added 2026-09-15)

- [ ] H1 Diagnose simultaneous Telegram/mobile portfolio-value discrepancy observed 2026-09-15; identify exact price/snapshot sources before changing calculations.
- [ ] H2 Implement one canonical server-side operational snapshot shared by PC/Telegram/mobile for common account, position and open-order data.
- [ ] H3 Include snapshot timestamp/source and verify simultaneous PC/Telegram/mobile values agree within explicitly defined freshness tolerance.
- [ ] H4 Fix Market/Liquid-Hours trusted-time source; no steady-state UNKNOWN due to missing trusted time source.
- [ ] H5 Implement persistent execution ledger, normalized across automated bot, PC manual and mobile/manual client IDs.
- [ ] H6 Reconcile ledger with IBKR and existing bot/order logs; deduplicate by broker execution identity and recover historical executions as far back as reliably possible.
- [ ] H7 Investigate why Mobile Execution History returned `No items` on 2026-09-15 despite at least two reported SELL fills that day.
- [ ] H8 Expose execution history from persistent reconciled ledger rather than current-session-only IBKR results.
- [ ] H9 Implement cumulative Realized P&L with explicit reliable start date; current Unrealized P&L; Combined P&L; per-symbol cumulative realized P&L where reliable.
- [ ] H10 Add Telegram lifecycle alerts for BUY FILLED, SELL FILLED, PARTIAL FILL, REJECTED, CANCELLED; include execution details and SELL realized P&L when reliable.
- [ ] H11 Make Telegram execution alerts origin-independent (bot/PC/mobile) and idempotent so one execution produces one notification.
- [ ] H12 Regression-test current automatic bot, Telegram commands, PC manual console and mobile read-only console after integration.
- [ ] H13 Keep `MOBILE_MANUAL_MUTATIONS_ENABLED=0` throughout Block H; no live/paper broker mutation as part of data-layer implementation tests.
- [ ] H14 Controlled PAPER acceptance: verify canonical snapshot, execution capture, P&L and Telegram alert behavior before enabling any mobile mutation endpoint.

- [ ] H15 Telegram planned-orders transparency: when reporting `N orders planned`, list the actual planned symbols/orders from the bot's canonical planning structure, including action and any already-determined quantity/order type/limit price; do not independently recompute the candidate set for Telegram.

- [ ] H16 Manual Console IB Gateway service control: add explicit START/STOP controls for `tradingbot-ibgateway.service` on PC and mobile, with current-state display, confirmation before STOP, post-START verification of service + API connectivity, strict scoping to that service only, and full audit logging.


## 2026-09-16 operational update — Flex ledger and Telegram execution lifecycle
- [x] Durable IBKR Flex Trade Confirmation ledger created in existing execution-history SQLite database; initial import contains 107 fills and repeat import deduplicates them.
- [x] Flex Trade Confirmation sync installed as `tradingbot-flex-sync.timer`, scheduled every 15 minutes; latest verified service run exited SUCCESS and timer is active.
- [x] Mobile execution history and cumulative realized P&L use the durable Flex ledger rather than current-session-only executions; current history coverage is partial and must not be described as account inception history.
- [x] Telegram scan reporting can expose canonical PLANNED and SUBMITTED/PENDING order details; synthetic lifecycle test passed without broker mutation or real Telegram delivery.
- [x] Telegram lifecycle rendering added for PARTIALLY FILLED, CANCELLED, REJECTED and FILLED states.
- [x] Persistent `execution_notifications` deduplication registry added. IBKR API `execId` is the canonical immediate-notification identity and Flex `ibExecID` is used to recognize the same execution later.
- [x] Flex path now claims the execution identity before Telegram delivery, preventing a later Flex confirmation from duplicating an API-originated fill notification.
- [x] Reconciliation path can claim an IBKR API execution and generate an immediate execution alert payload. No broker mutation was enabled or performed.
- [ ] Complete immediate execution monitoring architecture: verify whether current reconciliation cadence is sufficiently prompt; otherwise use a persistent IBKR execution-event listener/monitor so API-confirmed fills reach Telegram within seconds rather than waiting for the 15-minute Flex cycle.
- [ ] Correlate and test real PAPER partial fills/final fills across IBKR API and Flex; never label an individual Flex execution as final completion unless broker state proves remaining quantity is zero.
- [ ] Add Flex coverage/sync metadata (`complete_from`, `through`, `earliest_execution`, `last_successful_sync_at`) so report coverage is distinct from earliest observed trade.
- [ ] Cross-check previous-business-day Flex Activity realized P&L against durable ledger daily totals and alert/log discrepancies.
- [ ] Final acceptance requirement: every real execution must generate one timely Telegram execution notification, independent of bot/PC/mobile origin, with no duplicate when Flex later confirms it.

## Project maintenance gate — mandatory after each completed implementation block
- [ ] Code change complete and tested.
- [ ] Requirements/architecture/checklist updated where affected.
- [ ] `history/TradingBotR1000_Master_History.txt` updated with decisions, implementation result, tests and remaining risks.
- [ ] Git working tree reviewed for secrets/runtime artifacts before staging.
- [ ] Relevant source/docs committed and pushed to configured GitHub `origin`; do not commit credentials, Flex tokens, runtime databases, raw broker reports or other sensitive account data.
- [ ] SentinelX continuity context checkpointed after the durable documentation/Git state is complete.

### 2026-09-16 — Block H execution notification hardening
- Added dedicated read-only `execution_monitor.py` using IBKR client ID 1007 and `execDetailsEvent`; deployed as enabled `tradingbot-execution-monitor.service`.
- Monitor is broker-mutation-free and maintains a persistent IBKR API connection; verified active and connected. Flex remains the 15-minute durable accounting/reconciliation fallback.
- Reworked execution notification registry from claim-before-send to observed/delivered semantics: an execution is marked Telegram-notified only after alert transport returns successfully. Failed delivery therefore remains retryable.
- API `execId` and Flex `ibExecID` share one persistent deduplication identity. Flex confirmation records confirmation without duplicating a notification already delivered by the API.
- Migrated durable Flex ledger to persist `ib_exec_id` and `ib_order_id`; all 107 existing fills were backfilled from internal raw JSON without exposing identifiers.
- Corrected lifecycle display to `PARTIALLY FILLED`.
- Synthetic retry/dedup tests and Python compilation passed. No broker order was submitted; mobile mutations remain disabled.
- Remaining acceptance: observe a controlled PAPER execution end-to-end and verify one timely Telegram execution notification plus later Flex confirmation with no duplicate.

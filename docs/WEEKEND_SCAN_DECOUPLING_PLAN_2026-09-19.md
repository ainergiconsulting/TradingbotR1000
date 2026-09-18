# TradingBotR1000 - Weekend Scan/Execution Decoupling Plan

Status: PLANNED ONLY - NO PRODUCTION CHANGE ON 2026-09-18
Planned work window: Saturday 2026-09-19 through Sunday 2026-09-20
Target: complete implementation and acceptance before US market reopens Monday 2026-09-21.

## Objective
Decouple strategy candidate preparation from broker order transmission without changing the approved trading strategy.

Current flow:
08:30 ET market-data refresh -> 09:28 ET scan -> 09:30 ET broker transmission.

Target flow:
08:30 ET market-data refresh -> scan immediately after successful refresh -> PREPARED plan + Telegram details -> wait -> 09:30 ET live broker revalidation -> EXECUTE -> reconciliation + Telegram broker status.

## Invariants
- Strategy inputs remain completed daily bars from the prior completed US session.
- No change to SMA, Bollinger, RSI, ranking, 97% BUY limit, max positions, long-only, no leverage, or DAY order policy.
- No broker order may be transmitted during implementation/testing until the explicitly controlled PAPER acceptance phase.
- IBKR remains authoritative for positions, open orders, available funds and order status.
- Final quantities are determined/revalidated immediately before transmission from live capital and broker state.
- SELL safety is rechecked immediately before placeOrder().
- Any stale/corrupt/mismatched prepared plan fails closed.
- Late execution beyond the approved execution window must fail closed.

## Planned implementation
1. Introduce separate PREPARE and EXECUTE lifecycle states.
2. Persist prepared-plan metadata: trade date, signal date, prepared timestamp, cycle/plan ID, market-data latest session, strategy version, configuration SHA256, candidate details, limit prices and execution state.
3. Trigger PREPARE immediately after successful 08:30 ET market-data refresh, rather than waiting until 09:28.
4. Preserve 09:30 ET as broker transmission time.
5. At EXECUTE, refresh broker/account evidence and revalidate PAPER account, market/liquid hours, current positions, all open orders, operational buy budget, available slots, duplicate prevention, long-only SELL guard, and prepared-plan date/session/config/version integrity.
6. Recalculate/finalize order quantities at EXECUTE using live operational capital.
7. Add a maximum late-execution window. If missed, mark execution MISSED and transmit nothing.
8. Split scheduler state into preparation and execution evidence.
9. Add separate watchdogs for PREPARE not completed by deadline and EXECUTE not completed after 09:30 ET.
10. Update Telegram lifecycle semantics: PENDING -> PREPARED -> SUBMITTED/PENDING; never show prior-day plans as current.

## Estimated engineering time
Expected controlled implementation/testing effort: approximately 5-7 hours.
Plan the work as a full weekend task rather than a quick time-setting change.

## Test and acceptance plan
A. Deterministic scheduler tests across pre-refresh, post-refresh, 09:30, late window, weekends, holidays and DST.
B. Failure injection for IBKR disconnects, incomplete/stale data, permission failures, stale/corrupt plans, config changes, controller restarts, capital changes, manual position changes, duplicate/open orders and zero-candidate days.
C. Strategy-equivalence test: same completed bars must generate identical candidates, rankings, BUY limits and exit signals before/after decoupling.
D. Isolated full-cycle no-transmission test using temporary state.
E. Capital/sizing matrix proving aggregate BUY notional never exceeds operational buy budget and margin buying power never increases spendable capital.
F. SELL/long-only tests immediately before broker mutation.
G. Telegram lifecycle/output tests.
H. Controlled PAPER broker-path acceptance using minimum size only after all prior tests pass.
I. Full PAPER session validation and next-day rollover validation.

## Weekend completion criteria
Do not declare complete unless all new and existing operational tests pass; PREPARE and EXECUTE are independently idempotent; restart scenarios cannot duplicate orders; stale plans cannot execute; late execution cannot occur outside the approved window; Telegram semantics match broker/state semantics; isolated E2E proves zero unintended broker mutations; controlled PAPER acceptance passes; Master History, CHANGELOG, specification and Git are updated; and Monday pre-market readiness check passes.

## Friday 2026-09-18 instruction
No implementation or operational scheduling changes today. Production continues with the current timing for Friday. Begin this work on Saturday 2026-09-19.

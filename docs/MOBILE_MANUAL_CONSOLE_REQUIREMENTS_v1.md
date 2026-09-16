# TradingBotR1000 Mobile Manual Console — Requirements v1

Date: 2026-09-14
Status: REQUIREMENTS CLOSED / APPROVED FOR ARCHITECTURE PHASE
Project: TradingBotR1000
Subproject: Mobile Manual Console

## 1. Purpose

The Mobile Manual Console must provide a secure, reliable and easy-to-use mobile equivalent of the existing TradingBotR1000 Manual Control Console.

Priority order:
1. Security.
2. Reliability and fail-safe behavior.
3. Ease of use and practicality.
4. Functional parity with the existing PC Manual Control Console.

The mobile interface must not create a second independent trading logic. All broker actions and trading-safety decisions must remain under deterministic server-side control.

## 2. Mobile access and user experience

The console must be accessible from a smartphone through an icon on the phone home screen, with an app-like user experience. The preferred implementation is a Progressive Web App (PWA).

The user must not need SSH, ConnectBot, VNC, a terminal, or manually typed technical server commands in order to use the console.

## 3. Secure access

Security is the primary requirement.

The Mobile Manual Console must not be exposed directly to the public Internet as an unrestricted trading interface. Access must use a private authenticated path to the server; the preferred direction is Tailscale/private VPN, subject to final architecture validation.

The console must require application-level authentication in addition to network-level access.

Preferred authentication is passkey/WebAuthn with biometric or device-PIN verification where supported. TOTP (for example Google Authenticator) may be used as a recovery or secondary factor, but is not preferred as the primary authentication mechanism.

The mobile device must not store IBKR credentials and must never become a direct IBKR client. The browser/mobile client must never be the authority for determining whether a trade is safe or permissible.

No long-lived "remember me" authentication is allowed. Sessions must be server-side, short-lived, use secure cookies (Secure, HttpOnly, SameSite=Strict where applicable), and expire automatically after a short inactivity interval to be finalized during architecture design. Closing the browser alone must not be relied upon as the security boundary.

## 4. Portability and phone replacement

The system must not depend on one specific smartphone. If the phone is replaced, lost, damaged or changed, the trading system itself must not need to be rebuilt.

Critical logic, configuration, Russell 1000 data, audit information and IBKR integration remain server-side.

A replacement phone should require only re-establishment of private-network access, opening/installing the PWA, adding its icon to the home screen, and enrolling a new authentication credential/passkey.

It must be possible to revoke an old or lost phone independently of TradingBotR1000 and independently of IBKR credentials.

The design should support Android and iPhone/iPad-class devices without requiring separate native applications.

## 5. Functional parity with the PC Manual Control Console

Required functions:
- Account Summary.
- Positions.
- Open Orders.
- BUY Limit.
- BUY Market.
- SELL Limit.
- SELL Market.
- Cancel selected order.
- Cancel all orders / global cancellation.
- Liquidate selected position.
- Emergency Liquidate All Positions.
- Market / Liquid Hours status.
- Investable Capital Control.
- Recent/latest broker execution history.

The mobile interface may present these functions differently, but underlying rules and safety behavior must remain consistent with the PC console.

## 6. Russell 1000 instrument list

The console should include a dedicated Russell 1000 page representing the TradingBotR1000 trading universe.

The page must be searchable/browsable by ticker symbol and company name. Where practical it may also show current position and open-order status.

Tapping a symbol should open an instrument-specific view from which the user can initiate BUY or SELL.

This page must not implement a second trading path. It may only select the instrument and route the action through the same deterministic server-side Manual Trading Service used by all other manual orders.

## 7. Order-entry experience

Before final submission the interface must show an explicit summary including, as applicable:
- Symbol/instrument.
- BUY or SELL.
- Order type.
- Quantity.
- Limit price.
- Estimated order value when available.
- Relevant market/liquid-hours status or warning.

A deliberate confirmation is required before submission. Destructive/high-impact actions, especially Emergency Liquidate All and global cancellation, require stronger confirmation semantics.

Biometric-backed confirmation may be used where appropriate but never replaces deterministic backend safety checks.

## 8. Server-side authority and reuse of safety logic

A deterministic server-side Manual Trading Service is the sole authority for manual broker actions.

The existing TradingBotR1000 manual-control logic should be reused/refactored rather than duplicated wherever possible.

Server-side controls must continue to enforce at minimum:
- Correct account/environment validation, including PAPER/LIVE safeguards as applicable.
- Long-only behavior unless explicitly changed later.
- No unintended leverage.
- Positive and valid quantities.
- Valid limit prices.
- Current broker position validation before SELL/liquidation.
- Duplicate/conflicting SELL-order protection.
- IBKR connectivity/state checks.
- Market/liquid-hours checks and required acknowledgements.
- Order-intent/duplicate-submission safeguards.
- Required confirmations for destructive operations.
- Audit logging.

The UI must be treated as untrusted for trading-safety purposes.

## 9. Reliability and fail-safe behavior

The system must fail closed whenever the state needed to trade safely cannot be established.

Architecture and testing must explicitly cover:
- IBKR disconnected.
- IB Gateway alive but API degraded/unresponsive.
- Phone connectivity lost before submission.
- Phone connectivity lost after submission but before response display.
- Double tap/resubmission.
- Duplicate requests reaching the server.
- IBKR accepts an order but application acknowledgement/status is uncertain.
- Displayed position/order data becomes stale before submission.
- Session expires during an action.
- Phone lost/revoked.
- Backend detects inconsistent or uncertain trading state.

An uncertain outcome must never automatically be treated as a failed submission that is safe to repeat. Broker state must be reconciled first.

## 10. Auditability

All mobile manual trading actions must be auditable server-side. The audit trail must record enough information to reconstruct the request, validation, broker submission and observed outcome.

Auditability must not depend on local history retained by the phone.

## 11. Simplicity and maintainability

The design must minimize duplicated code and duplicated decision paths.

PC manual control and mobile manual control should ultimately consume the same server-side trading logic so that safety changes are implemented in one place.

The mobile layer should remain primarily a presentation, authentication and request/response layer.

## 12. Cost requirement

The architecture should avoid unnecessary recurring costs. The existing Hetzner server should be reused where practical. Open-source components and free TLS/passkey capabilities should be preferred when they satisfy security and reliability requirements.

Tailscale Personal may be zero-cost if its terms and intended use are appropriate; otherwise the applicable paid Tailscale tier is an acceptable small recurring cost subject to explicit approval.

## 13. Validation before operational use

The Mobile Manual Console must not be considered operational until it has passed controlled paper-trading validation, including normal actions and failure scenarios.

Any future LIVE use requires a separate explicit acceptance decision after successful paper-trading validation.

## 14. Requirements-phase conclusion

These requirements are the approved baseline for Mobile Manual Console v1. The next project phase is architecture design.

Any material change must be explicitly recorded in this document or a later version and reflected in the TradingBotR1000 Master History.


## 2026-09-15 — Operational data consistency, executions, P&L, Telegram alerts

The Mobile Manual Console shall not maintain an independent portfolio/account calculation path. PC console, Telegram status/reporting, and Mobile Manual Console must consume the same canonical server-side IBKR operational snapshot wherever the underlying datum is the same.

Required canonical snapshot content includes at minimum: account mode (PAPER/LIVE only; never expose the full account identifier to the mobile client), cash, available funds/buying power as applicable, operational buy budget/investable capital, invested value, cash weight, current positions, current/market values, unrealized P&L, open/pending orders, and a timestamp/source for the snapshot.

Execution History is a required operational function. It must be based on a persistent server-side execution ledger reconciled with IBKR, not solely on the lifetime of the current IBKR API session. Executions from the automated bot, PC manual console, mobile manual console, and other recognized API client IDs must be normalized into the same ledger with deduplication by execution identity.

The console shall expose cumulative Realized P&L from the earliest date for which the execution history can be reconstructed reliably. The UI must display the start date of the cumulative series. It shall also display current Unrealized P&L and Combined P&L = cumulative Realized P&L + current Unrealized P&L. Per-symbol cumulative realized P&L should be provided when it can be derived reliably from the persistent execution/position-cost history.

A completed or partially completed BUY/SELL execution must generate an operational Telegram notification independent of whether the originating order came from the bot, PC console, or mobile console. Notifications must cover at minimum: BUY FILLED, SELL FILLED, PARTIAL FILL, REJECTED and CANCELLED. Fill notifications should include symbol, quantity, average fill price, notional/proceeds, timestamp, source/origin, and for SELL the realized P&L when reliably available. Duplicate notifications for the same broker execution must be prevented.

Market/Liquid-Hours Status is a safety-critical feature. `UNKNOWN` caused by an unavailable trusted time source is not acceptable as a steady-state implementation. The mobile console must use the same trusted market-hours/time source as the canonical operational layer and fail closed for order submission if that status cannot be established or explicitly acknowledged according to the existing PC-console safety logic.


## 2026-09-15 — Telegram planned-orders transparency

Whenever Telegram reports a summary count such as `N orders planned`, it must also identify the planned orders/tickers that produced that count. The operator must be able to see in advance which symbols currently satisfy the strategy's entry criteria before broker submission.

At minimum, the planned-orders section should include for each candidate: symbol, intended action, planned quantity if already determined, planned order type/limit price if already determined, and a concise reason/status showing that the symbol passed the strategy selection criteria. Where quantity or price is not yet final, the message should still list the symbol and mark the unresolved fields explicitly rather than omitting the candidate.

The list must be derived from the same canonical planning/output structure used by the bot to create orders, so Telegram is reporting the actual planned set rather than independently recomputing candidates.


## 2026-09-16 — IB Gateway service control from Manual Console

The Manual Console must provide explicit controls to stop and start the TradingBotR1000 IB Gateway service (`tradingbot-ibgateway.service`) so the operator can intentionally release the IBKR session when manual access to IBKR is required and then restore the bot connection afterwards.

Required behavior:
- Display current IB Gateway service state before any action.
- Provide separate STOP IB GATEWAY and START IB GATEWAY actions; do not use a blind toggle.
- STOP must require an explicit confirmation describing the operational consequence: TradingBotR1000 loses broker connectivity and automated/manual broker operations become unavailable until Gateway is restarted.
- START must report success/failure and then verify service state plus API connectivity before declaring the Gateway operational.
- The control must affect only `tradingbot-ibgateway.service`; it must not implicitly stop the bot, mobile console, Telegram listener, or other services unless a later approved safety rule explicitly requires it.
- The same capability should be available on both PC Manual Console and Mobile Manual Console, subject to the same authentication/audit requirements as other privileged operational controls.
- Every start/stop request and result must be audit logged with timestamp, origin (PC/mobile), authenticated session identity where available, requested action, and resulting service/API state.

## Execution notification clarification — 2026-09-16
The requirement that every actual broker execution be reported on Telegram is implemented as near-real-time IBKR API observation with durable Flex reconciliation/fallback. Notification deduplication is by broker execution identity and successful delivery, not by order submission. Partial executions remain distinct fills; whole-order completion may be stated only from broker order state showing no remaining quantity. Notification infrastructure must remain read-only with respect to broker mutations.

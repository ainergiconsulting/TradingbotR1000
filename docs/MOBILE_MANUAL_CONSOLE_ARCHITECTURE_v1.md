# TradingBotR1000 Mobile Manual Console — Architecture v1

Date: 2026-09-14
Status: ARCHITECTURE BASELINE — READY FOR IMPLEMENTATION CHECKLIST

## 1. Design principle
Mobile v1 is not a new trading platform. It is a secure mobile interface over the existing Manual Control Console logic. Existing PC behavior is preserved wherever possible. New functionality is limited primarily to secure mobile access/PWA and convenient BUY-symbol selection from the Russell 1000 universe.

## 2. High-level architecture
Phone/PWA -> Tailscale private network -> HTTPS/Tailscale Serve -> application authentication/passkey -> Mobile Manual API -> shared Manual Trading Core -> IB Gateway -> IBKR.

The phone never connects directly to IBKR and stores no IBKR credentials. Trading safety authority remains server-side.

## 3. Network and access security
- No public Internet exposure of the Mobile Manual Console.
- Preferred private transport: Tailscale.
- Preferred HTTPS ingress: Tailscale Serve, avoiding nginx in v1 unless later required.
- Web application/backend should listen only on loopback (for example 127.0.0.1), not on the public interface.
- Tailscale access should be restricted to explicitly authorized identity/device access rather than granting broad server access unnecessarily.
- Application-level authentication remains required even after Tailscale access.
- Preferred application authentication: Passkey/WebAuthn with device biometric/PIN verification. TOTP may be retained as controlled secondary/recovery mechanism.
- No persistent remember-me login.

## 4. Session policy
Session is server-side and short-lived after genuine user inactivity. Genuine activity means deliberate physical interaction with the console UI, such as tap/click, typing/searching, navigation, opening an item, or manual scrolling. Automatic price refresh, polling, notifications, background traffic or other machine-generated activity MUST NOT extend the session.

The exact inactivity timeout will be finalized during implementation; initial design target is approximately 10–15 minutes of genuine inactivity. Continuous deliberate use, including spending longer periods browsing/searching Russell 1000 instruments, keeps the session active.

## 5. Startup/status behavior
The mobile console follows the existing PC-console concept: after authentication/opening, it connects/verifies the manual IBKR path and immediately presents operational status before trading actions.

The initial status view should clearly expose at least:
- IB Gateway/API connectivity.
- Manual IBKR client connectivity.
- PAPER/LIVE account/environment.
- Operational/trading enabled or blocked state.
- Relevant market status where applicable.

If broker state cannot be safely established, trading actions fail closed.

## 6. Shared Manual Trading Core
Existing broker/safety functions from the current PC Manual Control Console are to be reused/refactored into a common server-side core rather than duplicated in the mobile layer.

PC Manual Console -> shared Manual Trading Core
Mobile Manual API -> shared Manual Trading Core
Shared Manual Trading Core -> IB Gateway/IBKR

The existing interactive input()/print()/menu layer remains a PC interface and is not the mobile API.

## 7. Functional parity
Mobile v1 retains the existing PC-console functionality:
- Account Summary
- Positions
- Open Orders
- BUY Limit
- SELL Limit
- BUY Market
- SELL Market
- Cancel Selected Order
- Cancel All Orders
- Liquidate Selected Position
- Emergency Liquidate All Positions
- Market/Liquid-Hours Status
- Investable Capital Control
- Latest Broker Execution History

## 8. BUY and SELL instrument selection
BUY: instrument selection may use a searchable Russell 1000 universe. A flat 1000-row mobile list is not required; search/filter is the primary interaction. The Russell 1000 page is only an instrument selector and creates no independent trading path.

SELL: instrument selection MUST be restricted to currently held broker positions, matching the existing PC-console logic. The Russell 1000 list is not a SELL source. Immediately before submission, the backend independently revalidates the current broker position and allowed quantity. Existing SELL-all behavior is retained where applicable.

## 9. Order-entry workflow
Preserve the existing PC-console logic and ordering as closely as practical:
1. Select instrument (BUY from R1000/search; SELL from owned positions only).
2. Enter quantity (SELL may support all).
3. Select MARKET or LIMIT.
4. If LIMIT, present the server-generated suggested/default limit price. The field is prefilled; accepting it leaves the value unchanged, while the user may replace it with another value.
5. Show final order review including action, contract/symbol, current price, limit price if applicable, quantity, estimated notional, liquid-hours status and relevant warning(s).
6. Explicitly confirm the order.
7. Backend revalidates critical broker/safety state and submits through the shared Manual Trading Core.

## 10. Safety and failure semantics
The mobile UI is not trusted for safety decisions. The server revalidates account, broker connectivity, contract, current position, quantity, price, capital/buying-power constraints, long-only rules, duplicate/conflicting intent, market/liquid-hours rules and other existing safeguards.

Duplicate mobile submissions/double taps must not create duplicate orders. Requests that can mutate broker state require a unique idempotency/request identifier.

If submission outcome becomes uncertain (for example IBKR may have accepted the order but the response path fails), the system MUST NOT treat this as a safe failure to retry. It must reconcile broker order/execution state before permitting a potentially duplicate submission.

## 11. IBKR connection model
The mobile service follows the PC-console operational concept: opening/using the console establishes/verifies a dedicated manual IBKR client connection using an appropriate dedicated client ID, and status is visible to the user. The connection is maintained while the manual console is actively in use. The architecture must avoid creating a new IBKR connection for every UI click/order.

## 12. Portability
Critical logic/configuration remains on Hetzner. Replacing a phone should require only private-network enrollment, PWA access/install, passkey enrollment and revocation of the old device/credential. No TradingBotR1000 or IBKR rebuild is required.

## 13. Server components for v1
Expected components on Hetzner:
- Existing IB Gateway and TradingBotR1000 environment.
- Shared Manual Trading Core refactored from existing console logic.
- Lightweight Mobile Manual API/web service.
- PWA static/frontend assets.
- Server-side authentication/session storage appropriate for a single-user private console.
- Server-side audit/idempotency/reconciliation state.
- Tailscale and Tailscale Serve HTTPS ingress.
- systemd service for the Mobile Manual Console/API, configured for automatic startup and controlled restart.

Avoid additional infrastructure (nginx, separate database, containers, cloud services) unless implementation proves it necessary.

## 14. Implementation grouping
Implementation should be performed in grouped phases to minimize operator switching:
A. Server/SentinelX batch: code/refactor, dependencies, service, loopback binding, Tailscale installation/config preparation, security checks, audit/logging, tests.
B. One PC/operator batch: Tailscale identity/tailnet authorization and any identity-provider action that cannot safely be automated.
C. One phone batch: Tailscale enrollment, open/install PWA, passkey/biometric enrollment, Home-screen icon.
D. Controlled paper-trading acceptance test: normal flows plus duplicate, disconnect, stale/uncertain-state and destructive-action scenarios.

## 15. Pre-implementation security check
Before operational activation, verify the exposure of the existing IBKR API port (currently observed listening on port 4002 on all interfaces). Determine actual firewall reachability and restrict it appropriately if necessary. This check is independent of the PWA but required for coherent overall security.

## 16. Architecture conclusion
Architecture v1 deliberately minimizes novelty: secure private mobile access and R1000 BUY selection are added around the already established Manual Control Console behavior. SELL remains restricted to held positions. Trading logic and safety remain deterministic and server-side. The next step is a concrete implementation checklist, followed by grouped implementation and paper-trading acceptance testing.

## Execution notification architecture update — 2026-09-16
Execution notification is now dual-source with a single broker execution identity. A dedicated read-only long-lived IBKR API monitor (client ID 1007) consumes `execDetailsEvent` for near-real-time operator notification. The durable Flex Trade Confirmation sync remains the accounting/reconciliation fallback. IBKR API `execId` is correlated with Flex `ibExecID`; persistent notification state separates observation from successful Telegram delivery so transport failure is retryable and later Flex confirmation cannot create a duplicate after successful API delivery. Neither notification path is permitted to place, modify, or cancel broker orders.

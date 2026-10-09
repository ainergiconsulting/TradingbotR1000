# TradingbotR1000 Operating Manual

## Startup Procedure

1. Start IB Gateway and log in to the IBKR Paper account.
2. Confirm the IB Gateway API is enabled on paper port `4002`.
3. Open `TradingbotControl\Start Trading System.lnk`.
4. Use `TradingbotControl\Control Console.lnk` to view status, broker evidence,
   reports, pending orders, and available controls.

Closing the Start Trading System window does not stop the bot after the
background runtime has started.

## Shutdown Procedure

1. Open `TradingbotControl\Stop Trading System.lnk`.
2. Wait for the Stop Trading System window to report that the stop request was
   completed.
3. Close IB Gateway only after the trading system has stopped.

Do not stop the bot by closing the Control Console window.

## Applications

### Start Trading System

Starts the complete TradingbotR1000 runtime in the background after startup
validation. It prevents duplicate controller and supervisor processes. The
approved launcher enables automated PAPER execution for the background runtime;
activation fails closed if the PAPER account, API, live account values,
reconciliation, market data, persistence, or duplicate-prevention checks are not
healthy.

### Stop Trading System

Requests a clean shutdown of all TradingbotR1000 runtime components while
preserving state, logs, broker snapshots, and reports.

### Control Console

The only operational interface. It can be opened or closed at any time without
starting or stopping the bot. It opens the migrated manual trading console menu
for account summary, positions, open orders, BUY/SELL orders, cancellations,
liquidation actions, market-hours checks, and execution history where supported.
BUY Limit and BUY Market use the R1000 manual watchlist.

Option 13 controls the strategic capital ceiling:

- `AUTO`: the strategy-configured percentage of current live IBKR NLV (currently 100%).
- `MANUAL`: operator-defined fixed USD ceiling, rejected if it exceeds current live NLV.
- Blank input leaves the current setting unchanged.

This strategic ceiling is NOT the amount the bot may actually spend. Under the
no-leverage policy, every BUY cycle computes a broker-authoritative Operational
Buy Budget from the minimum of actual cash, IBKR AvailableFunds and
LookAheadAvailableFunds, then applies the configured safety margin (currently
1%). NLV and BuyingPower are informational/ceiling values and can never increase
the spendable BUY budget. If cash or AvailableFunds is invalid/missing, BUY
sizing fails closed.

First-three-session automated PAPER quality reports are written to
`current_reference\PaperTradingR1000\reports\quality_monitoring`.

### IBKR health state and alerts
The independent health supervisor treats a fresh controller heartbeat and a healthy IBKR API as separate requirements. `OK` requires both a fresh heartbeat and an IBKR `CONNECTED` state. A single/transient API probe failure is reported as `UNKNOWN`; after 3 consecutive transient failures the state becomes `DEGRADED` and one Telegram `ibkr_degraded` alert is sent. A hard socket/Gateway failure is `DISCONNECTED` and sends `ibkr_disconnected`. Recovery from `DEGRADED` or `DISCONNECTED` sends `ibkr_reconnected`. `DEGRADED` and `DISCONNECTED` are operationally fail-closed for trading.


### PC Manual Console session safety and execution history

The PC Manual Console permits only one active console session at a time. A newly
opened console may replace an older console only when the older session is
waiting at the menu; it will not terminate a console while an action is being
processed. Menu inactivity closes the PC console after 10 minutes and disconnects
the manual IBKR session cleanly.

Option 14, **Latest Broker Execution History**, is broker-ledger based. It shows
Flex-confirmed fills together with IBKR API fills that are still awaiting Flex
confirmation, and labels those sources separately. This view is observational;
it does not create, cancel, or modify broker orders.


### Post-close strategy plan and Telegram status precedence

Entry conditions are determined from completed daily bars. After the 16:30 ET
post-close refresh has successfully obtained the just-completed US session, the
read-only next-session preview is the current strategy plan for status/reporting
purposes.

If a saved regular scan belongs to the just-finished ET trading date and a newer
post-close preview targets a later eligible ET session, Telegram `/status`
must display the newer preview, not the older regular-scan plan. The preview is
still non-submitting: actual broker transmission remains in the unchanged
09:28/09:30 regular execution path, which refreshes broker/account safety state
again before transmitting any order.

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

Option 13 controls investable capital:

- `AUTO`: 70% of current live IBKR NLV.
- `MANUAL`: operator-defined fixed USD amount, rejected if it exceeds current
  live NLV.
- Blank input leaves the current setting unchanged.

First-three-session automated PAPER quality reports are written to
`current_reference\PaperTradingR1000\reports\quality_monitoring`.

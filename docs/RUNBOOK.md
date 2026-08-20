# TradingbotR1000 Runbook

Primary owner entry points are in `TradingbotControl`:

- `Start Trading System.lnk`
- `Stop Trading System.lnk`
- `Control Console.lnk`

Operating manual:

```text
docs\OPERATING_MANUAL.md
```

Use the Control Console for the migrated manual console menu: account summary,
positions, open orders, BUY/SELL orders, cancellations, liquidation actions,
market-hours checks, and execution history where supported.
BUY Limit and BUY Market use `config\manual_trading_watchlist.xlsx`.
The runtime writes health, heartbeat, controller, broker snapshot, scan,
order-plan, and reconciliation evidence under `current_reference\PaperTradingR1000`.

The configured local universe file is `IWB_holdings.csv` at the repository
root.

For manual dry-run scans, pass account equity as Net Liquidation Value, for
example `python trading_engine.py --scan-once --net-liquidation-value 100000`.

Generated runtime files and local secrets are intentionally ignored by Git.

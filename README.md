# TradingbotR1000

TradingbotR1000 is a Windows-oriented IBKR paper-trading project migrated from
the Tradingbot2607 operational architecture and adapted for the approved
Russell 1000 daily mean-reversion strategy.

Authoritative strategy source:

```text
docs/TradingbotR1000_Strategy_Specification_FINAL_v1.1.docx
```

The runtime package is:

```text
current_reference/PaperTradingR1000
```

The configured local Russell 1000 universe source is:

```text
IWB_holdings.csv
```

Operator shortcuts are in:

```text
TradingbotControl
```

The migrated Control Console uses:

```text
config/manual_trading_watchlist.xlsx
```

The implementation is dry-run/order-plan oriented by default. Broker order
submission remains disabled unless explicitly enabled by local runtime
configuration.

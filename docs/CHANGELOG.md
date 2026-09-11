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

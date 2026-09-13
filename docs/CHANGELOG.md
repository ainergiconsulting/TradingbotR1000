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

# TradingbotR1000 IBKR Operations

IBKR connectivity is handled through the adapted `ibkr_utils.py` layer.

The strategy specification does not define a data provider, adjusted-price
policy, order type, or time-in-force. Any broker-specific setting is an
implementation setting and must not be treated as a trading rule.
## No-Leverage Capital Invariant

Automated BUY sizing must never use IBKR margin capacity. The authoritative
Operational Buy Budget is capped by the minimum of broker-reported actual cash,
`AvailableFunds`, and `LookAheadAvailableFunds` (when present), further limited
by any lower strategy capital ceiling, and reduced by the configured safety
margin. `NetLiquidation` and `BuyingPower` must not increase this budget.

This cash cap is mandatory once positions exist: IBKR `AvailableFunds` may then
be materially higher than cash because it reflects margin capacity. A missing or
invalid cash/AvailableFunds value is a fail-closed condition for new BUY sizing.

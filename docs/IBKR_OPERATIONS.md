# TradingbotR1000 IBKR Operations

IBKR connectivity is handled through the adapted `ibkr_utils.py` layer.

The strategy specification does not define a data provider, adjusted-price
policy, order type, or time-in-force. Any broker-specific setting is an
implementation setting and must not be treated as a trading rule.

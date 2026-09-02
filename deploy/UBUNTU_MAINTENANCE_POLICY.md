# Ubuntu maintenance policy for TradingBotR1000

The production/PAPER trading server must not install packages or restart services automatically during the trading week.

Enforced controls:

- `APT::Periodic::Unattended-Upgrade "0"` disables unattended package installation.
- `apt-daily-upgrade.timer` is disabled.
- `apt-daily.timer` remains enabled so package metadata can still refresh.
- `needrestart` is forced to list-only mode (`$nrconf{restart} = 'l'`), so package maintenance cannot automatically restart TradingBot/IB Gateway dependencies.
- Required service restarts/reboots are performed only during explicit weekend maintenance. If automatic needrestart behavior is intentionally required during maintenance, invoke that maintenance explicitly with `NEEDRESTART_MODE=a`.

Incident rationale: on 2026-09-02 `needrestart` correctly deferred direct restart of `tradingbot-ibgateway.service`, but automatically restarted `tradingbot-xvfb.service`. Because IB Gateway declares `Requires=tradingbot-xvfb.service`, stopping Xvfb propagated a stop to IB Gateway, destroying the authenticated API session. Protecting only the Gateway unit was therefore insufficient.

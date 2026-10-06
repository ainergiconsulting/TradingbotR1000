# Ubuntu maintenance policy for TradingBotR1000

The production/PAPER trading server must not install packages or restart services automatically during the trading week.

Enforced controls:

- `APT::Periodic::Unattended-Upgrade "0"` disables unattended package installation.
- `apt-daily-upgrade.timer` is disabled.
- `apt-daily.timer` remains enabled so package metadata can still refresh.
- `needrestart` is forced to list-only mode (`$nrconf{restart} = 'l'`), so package maintenance cannot automatically restart TradingBot/IB Gateway dependencies.
- Required service restarts/reboots are performed only during explicit weekend maintenance. If automatic needrestart behavior is intentionally required during maintenance, invoke that maintenance explicitly with `NEEDRESTART_MODE=a`.

Incident rationale: on 2026-09-02 `needrestart` correctly deferred direct restart of `tradingbot-ibgateway.service`, but automatically restarted `tradingbot-xvfb.service`. Because IB Gateway declares `Requires=tradingbot-xvfb.service`, stopping Xvfb propagated a stop to IB Gateway, destroying the authenticated API session. Protecting only the Gateway unit was therefore insufficient.

## 2026-10-06 restart-storm hardening

The Oct-04 weekly reboot exposed a separate startup failure mode: persistent controller/supervisor PID files survived the reboot, and Linux reused one of those numeric PIDs for an unrelated process. Older singleton logic treated any live PID as proof that the TradingBot process already existed, so systemd received exit status 10 and, because the services used `Restart=on-failure`, retried every five seconds.

Current safeguards are layered:

- Runtime singleton checks validate both PID existence and the expected command line before treating a PID file as authoritative. Reused/stale PIDs are cleared without signalling the unrelated process.
- `tradingbot-controller.service` and `tradingbot-health-supervisor.service` use `RestartPreventExitStatus=10`, so an explicit "already running" result can never create a restart storm.
- Both services use `StartLimitIntervalSec=300` and `StartLimitBurst=5`, bounding any other unexpected crash loop instead of allowing unlimited retries.
- Weekly maintenance now stops both controller and health supervisor before package work, verifies that both are inactive, and only then removes their PID bookkeeping files. If either process cannot stop cleanly, maintenance aborts before package changes/reboot.
- The weekly schedule remains Sunday 04:00 America/New_York (08:00 UTC while New York is on EDT), preserving the established margin after the IBKR weekly authentication reset. IB Gateway is not changed by this hardening and post-reboot trading remains fail-closed until API/reconciliation are healthy.

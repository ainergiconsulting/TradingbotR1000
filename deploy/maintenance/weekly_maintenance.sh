#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ibkradmin/trading/TradingbotR1000
HISTORY="$ROOT/history/TradingBotR1000_Master_History.txt"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DRY_RUN="${TRADINGBOT_MAINTENANCE_DRY_RUN:-0}"

log_history() {
  printf '\n[%s] WEEKLY_MAINTENANCE: %s\n' "$(date -u +%Y-%m-%d)" "$1" >> "$HISTORY"
  chown ibkradmin:ibkradmin "$HISTORY" || true
}

# Safety: this job is designed only for Sunday in America/New_York.
NY_WEEKDAY="$(TZ=America/New_York date +%u)"
if [ "$NY_WEEKDAY" != "7" ] && [ "$DRY_RUN" != "1" ]; then
  log_history "ABORTED outside Sunday America/New_York safety window."
  exit 2
fi

exec 9>/run/tradingbot-weekly-maintenance.lock
flock -n 9 || exit 0

if [ "$DRY_RUN" = "1" ]; then
  echo "DRY_RUN: would stop controller, update/upgrade Ubuntu in needrestart list-only mode, then reboot server."
  echo "DRY_RUN: apt unattended installation remains disabled during the trading week."
  exit 0
fi

log_history "START at $STAMP. Trading controller will stop; Ubuntu packages will be updated in controlled maintenance; server will reboot afterward. IB Gateway authentication may require user action after reboot."

# Stop both long-lived processes that maintain persistent PID bookkeeping.
# This gives them a clean shutdown before the deliberate reboot. If either
# refuses to stop, abort maintenance rather than upgrading around a live bot.
systemctl stop tradingbot-controller.service tradingbot-health-supervisor.service || true
if systemctl is-active --quiet tradingbot-controller.service || systemctl is-active --quiet tradingbot-health-supervisor.service; then
  log_history "ABORTED because controller or health supervisor did not stop cleanly."
  exit 3
fi

# Services are confirmed inactive, so persistent PID bookkeeping cannot refer
# to a live controller/supervisor. Remove any residue before the reboot.
rm -f "$ROOT/current_reference/PaperTradingR1000/state/operational_controller.pid"
rm -f "$ROOT/current_reference/PaperTradingR1000/state/health_supervisor.pid"

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=l
apt-get update
apt-get -y -o Dpkg::Options::=--force-confold upgrade
apt-get -y autoremove

log_history "PACKAGE PHASE COMPLETE. Controlled reboot initiated; post-reboot Gateway/API authentication and reconciliation are required before trading resumes."
sync
systemctl reboot

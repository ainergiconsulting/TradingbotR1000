#!/bin/bash

echo "TradingbotR1000 runtime status"
echo

systemctl --no-pager --quiet is-active tradingbot-controller.service && echo "Controller: RUNNING" || echo "Controller: STOPPED"
systemctl --no-pager --quiet is-active tradingbot-supervisor.service && echo "Supervisor: RUNNING" || echo "Supervisor: STOPPED"

echo
systemctl status tradingbot-controller.service tradingbot-supervisor.service --no-pager --lines=5

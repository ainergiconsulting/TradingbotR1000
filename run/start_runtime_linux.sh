#!/bin/bash
set -e

sudo systemctl start tradingbot-supervisor.service
sudo systemctl start tradingbot-controller.service

echo
systemctl --no-pager --quiet is-active tradingbot-supervisor.service && echo "Supervisor: RUNNING" || echo "Supervisor: STOPPED"
systemctl --no-pager --quiet is-active tradingbot-controller.service && echo "Controller: RUNNING" || echo "Controller: STOPPED"

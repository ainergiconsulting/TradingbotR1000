#!/bin/bash
set -e

sudo systemctl stop tradingbot-controller.service
sudo systemctl stop tradingbot-supervisor.service

echo
systemctl --no-pager --quiet is-active tradingbot-controller.service && echo "Controller: RUNNING" || echo "Controller: STOPPED"
systemctl --no-pager --quiet is-active tradingbot-supervisor.service && echo "Supervisor: RUNNING" || echo "Supervisor: STOPPED"

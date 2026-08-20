"""IBKR reconciliation entry point for TradingbotR1000."""

from __future__ import annotations

import json

import config as cfg
from live_account import collect_live_account_context
from reconciliation import reconcile_local_state


def collect_broker_snapshot() -> dict[str, object]:
    return collect_live_account_context(client_id=cfg.RECONCILIATION_CLIENT_ID, readonly=True)


def main() -> int:
    snapshot = collect_broker_snapshot()
    report = reconcile_local_state(broker_snapshot=snapshot)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only near-real-time IBKR execution monitor.

Maintains a dedicated IBKR API connection and reacts to execDetailsEvent.
It never places, modifies or cancels orders. Telegram delivery is deduplicated
persistently by broker execId; Flex remains the accounting/fallback source.
"""
from __future__ import annotations

import time
from ib_insync import IB

import config as cfg
from flex_execution_ledger import mark_execution_notified, observe_execution, record_commission_report
from telegram_alerts import alert_execution_filled

RECONNECT_SECONDS = 5


def _payload(trade, fill) -> tuple[str, dict]:
    execution = fill.execution
    contract = fill.contract
    exec_id = str(getattr(execution, "execId", "") or "").strip()
    raw_side = str(getattr(execution, "side", "") or "").upper()
    side = "BUY" if raw_side in {"BOT", "BUY"} else ("SELL" if raw_side in {"SLD", "SELL"} else raw_side)
    return exec_id, {
        "symbol": str(getattr(contract, "symbol", "") or "").upper(),
        "side": side,
        "quantity": float(getattr(execution, "shares", 0) or 0),
        "price": float(getattr(execution, "price", 0) or 0),
        "date_time": str(getattr(execution, "time", "") or ""),
        "ib_order_id": str(getattr(execution, "orderId", "") or ""),
        "source": "IBKR API real-time execution",
    }


def _on_exec_details(trade, fill) -> None:
    exec_id, payload = _payload(trade, fill)
    order_id = str(getattr(fill.execution, "orderId", "") or "").strip()
    if not observe_execution(exec_id, source="IBKR_API", symbol=payload["symbol"], side=payload["side"], quantity=payload["quantity"], price=payload["price"], execution_time=payload["date_time"], ib_order_id=order_id):
        return
    # Deliberately mark only after alert transport returns successfully. If it
    # raises, the execution remains retryable by a reconnect/reconciliation/Flex.
    alert_execution_filled(payload)
    mark_execution_notified(exec_id)


def _on_commission_report(trade, fill, report) -> None:
    """Persist commission and realized P&L reported by IBKR for this fill."""
    exec_id = str(getattr(report, "execId", "") or getattr(fill.execution, "execId", "") or "").strip()
    commission = getattr(report, "commission", None)
    currency = str(getattr(report, "currency", "") or "")
    realized_pnl = getattr(report, "realizedPNL", None)
    record_commission_report(exec_id, commission, currency, realized_pnl)


def run() -> int:
    while True:
        ib = IB()
        try:
            ib.connect(cfg.HOST, cfg.PORT, clientId=cfg.EXECUTION_MONITOR_CLIENT_ID, readonly=True, timeout=10)
            # Reconcile executions already known to IBKR before subscribing to
            # new events. Historical observations are persisted without
            # generating retrospective Telegram alerts.
            reconciled = 0
            for fill in ib.reqExecutions():
                exec_id, payload = _payload(None, fill)
                order_id = str(getattr(fill.execution, "orderId", "") or "").strip()
                observe_execution(exec_id, source="IBKR_API", symbol=payload["symbol"], side=payload["side"], quantity=payload["quantity"], price=payload["price"], execution_time=payload["date_time"], ib_order_id=order_id)
                report = getattr(fill, "commissionReport", None)
                if report is not None and str(getattr(report, "execId", "") or "").strip():
                    _on_commission_report(None, fill, report)
                reconciled += 1
            ib.execDetailsEvent += _on_exec_details
            ib.commissionReportEvent += _on_commission_report
            print(f"Execution monitor connected and reconciled {reconciled} executions (read-only).", flush=True)
            ib.run()
        except KeyboardInterrupt:
            return 0
        except Exception as error:
            print(f"Execution monitor reconnect after {type(error).__name__}", flush=True)
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass
        time.sleep(RECONNECT_SECONDS)


if __name__ == "__main__":
    raise SystemExit(run())

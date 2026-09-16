"""Read-only near-real-time IBKR execution monitor.

Maintains a dedicated IBKR API connection and reacts to execDetailsEvent.
It never places, modifies or cancels orders. Telegram delivery is deduplicated
persistently by broker execId; Flex remains the accounting/fallback source.
"""
from __future__ import annotations

import time
from ib_insync import IB

import config as cfg
from flex_execution_ledger import mark_execution_notified, observe_execution
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
        "source": "IBKR API real-time execution",
    }


def _on_exec_details(trade, fill) -> None:
    exec_id, payload = _payload(trade, fill)
    if not observe_execution(exec_id, source="IBKR_API", symbol=payload["symbol"], side=payload["side"], quantity=payload["quantity"], price=payload["price"]):
        return
    # Deliberately mark only after alert transport returns successfully. If it
    # raises, the execution remains retryable by a reconnect/reconciliation/Flex.
    alert_execution_filled(payload)
    mark_execution_notified(exec_id)


def run() -> int:
    while True:
        ib = IB()
        try:
            ib.connect(cfg.HOST, cfg.PORT, clientId=cfg.EXECUTION_MONITOR_CLIENT_ID, readonly=True, timeout=10)
            ib.execDetailsEvent += _on_exec_details
            print("Execution monitor connected (read-only).", flush=True)
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

from __future__ import annotations

import os
import socket
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from ib_insync import IB

import config as cfg
import manual_trading_core as core
import mobile_auth as auth
from live_account import collect_live_account_context
from flex_execution_ledger import latest as ledger_latest, order_history as ledger_order_history, pnl_summary as ledger_pnl_summary
from candidate_history import recent_candidate_history
from mobile_r1000_selector import get_r1000_symbol, load_r1000_universe, search_r1000

BASE = Path(__file__).resolve().parent
PWA = BASE / "mobile_pwa"
IB_CLIENT: IB | None = None
BROKER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mobile-ibkr")
MUTATIONS_ENABLED = os.getenv("MOBILE_MANUAL_MUTATIONS_ENABLED", "0") == "1"


class WebAuthnFinish(BaseModel):
    challenge_id: str
    credential: dict



def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if k not in {"contract", "trade"}}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _socket_ok() -> bool:
    try:
        with socket.create_connection((cfg.HOST, cfg.PORT), timeout=1.0):
            return True
    except Exception:
        return False


async def _broker_call(function, *args, **kwargs):
    """Run one serialized mobile broker operation on a short-lived API session.

    The old mobile design kept client 1001 connected between HTTP requests.
    Because no IB event loop ran while the PWA was idle, Gateway traffic could
    accumulate in the TCP receive queue.  Connect/use/disconnect preserves the
    same request semantics without leaving an idle API client behind.
    """
    loop = asyncio.get_running_loop()

    def work():
        worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(worker_loop)
        ib = IB()
        try:
            core.connect_manual_console(ib)
            return function(ib, *args, **kwargs)
        finally:
            if ib.isConnected():
                ib.disconnect()

    try:
        return await loop.run_in_executor(BROKER_EXECUTOR, work)
    except core.ManualControlError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"IBKR unavailable: {type(exc).__name__}") from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    global IB_CLIENT
    # Disconnect any legacy persistent mobile connection left by an older
    # process version. New requests use short-lived serialized sessions.
    if IB_CLIENT is not None and IB_CLIENT.isConnected():
        IB_CLIENT.disconnect()
    IB_CLIENT = None
    yield
    BROKER_EXECUTOR.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="TradingBotR1000 Mobile Manual Console", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PWA), name="static")


@app.get("/api/auth/state")
def auth_state(request: Request):
    authenticated = True
    try:
        auth.require_session(request)
    except HTTPException:
        authenticated = False
    return {"authenticated": authenticated, "passkey_enrolled": auth.credential_count() > 0,
            "rp_id": auth.RP_ID, "mutations_enabled": MUTATIONS_ENABLED}


@app.post("/api/auth/register/options")
def auth_register_options():
    return auth.registration_options()


@app.post("/api/auth/register/finish")
def auth_register_finish(payload: WebAuthnFinish, response: Response):
    auth.finish_registration(payload.challenge_id, payload.credential)
    auth.new_session(response)
    return {"ok": True}


@app.post("/api/auth/login/options")
def auth_login_options():
    return auth.authentication_options("login")


@app.post("/api/auth/login/finish")
def auth_login_finish(payload: WebAuthnFinish, response: Response):
    auth.finish_authentication(payload.challenge_id, payload.credential, "login")
    auth.new_session(response)
    return {"ok": True}


@app.post("/api/auth/activity")
def auth_activity(request: Request):
    auth.record_physical_activity(request)
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    auth.logout(request, response)
    return {"ok": True}


@app.middleware("http")
async def protect_api(request: Request, call_next):
    path = request.url.path
    public = path.startswith("/api/auth/") or not path.startswith("/api/")
    if not public:
        try:
            auth.require_session(request)
        except HTTPException as exc:
            return Response(content=json.dumps({"detail": exc.detail}), status_code=exc.status_code, media_type="application/json")
    return await call_next(request)


@app.get("/")
def home():
    return FileResponse(PWA / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(PWA / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(PWA / "sw.js", media_type="application/javascript")


@app.get("/api/status")
async def status():
    socket_status = _socket_ok()
    account_mode = "UNKNOWN"
    api_reachable = False
    if socket_status:
        try:
            probe = await _broker_call(
                lambda ib: {
                    "connected": bool(ib.isConnected()),
                    "accounts": [str(x) for x in (ib.managedAccounts() or [])],
                }
            )
            api_reachable = bool(probe.get("connected"))
            accounts = probe.get("accounts") or []
            account_id = accounts[0] if accounts else None
            account_mode = "PAPER" if account_id and str(account_id).upper().startswith("DU") else ("LIVE" if account_id else "UNKNOWN")
        except HTTPException:
            pass
    return {"gateway_socket": socket_status, "ibkr_api": api_reachable,
            "manual_client_id": core.MANUAL_CLIENT_ID,
            "account_mode": account_mode,
            "trading": "READ_ONLY_BUILD" if not MUTATIONS_ENABLED else "MUTATIONS_ENABLED",
            "mutations_enabled": MUTATIONS_ENABLED}


def _canonical_mobile_snapshot():
    return collect_live_account_context(
        client_id=cfg.MOBILE_SNAPSHOT_CLIENT_ID,
        readonly=True,
    )


@app.get("/api/account")
async def account():
    snapshot = await asyncio.get_running_loop().run_in_executor(
        BROKER_EXECUTOR, _canonical_mobile_snapshot
    )
    values = snapshot.get("account_values", {})
    # Flex is the durable accounting source; unconfirmed IBKR API executions
    # are added provisionally and automatically disappear once Flex confirms them.
    ledger = ledger_pnl_summary()
    realized_since_start = ledger.get("realized_pnl_since_start")
    unrealized = values.get("unrealized_pnl")
    combined = (
        float(realized_since_start) + float(unrealized)
        if realized_since_start is not None and unrealized is not None
        else None
    )

    def item(key):
        value = values.get(key)
        return {"value": value, "currency": "USD" if value is not None else None}

    return {
        "net_liquidation": item("net_liquidation"),
        "cash": item("cash"),
        "available_funds": item("available_funds"),
        "buying_power": item("buying_power"),
        "realized_pnl_since_start": {"value": realized_since_start, "currency": "USD"},
        "confirmed_realized_pnl": {"value": ledger.get("confirmed_realized_pnl"), "currency": "USD"},
        "pending_realized_pnl": {"value": ledger.get("pending_realized_pnl"), "currency": "USD"},
        "pending_execution_count": ledger.get("pending_execution_count", 0),
        "current_unrealized_pnl": item("unrealized_pnl"),
        "combined_pnl": {"value": combined, "currency": "USD" if combined is not None else None},
        "pnl_start_date": ledger.get("pnl_start_date"),
        "pnl_through": ledger.get("through"),
        "pnl_pending_through": ledger.get("pending_through"),
        "pnl_history_status": "PARTIAL_HISTORY" if ledger.get("through") else "NO_HISTORY",
        "snapshot_timestamp_utc": snapshot.get("timestamp_utc"),
    }


def _mobile_position_row(row: dict) -> dict:
    """Canonical mobile position schema; never make the PWA guess IBKR field names."""
    return {
        **row,
        "symbol": row.get("symbol") or row.get("ibkrSymbol") or "",
        "quantity": row.get("quantity") if row.get("quantity") not in (None, "") else row.get("position"),
        "average_cost": row.get("averageCost") if row.get("averageCost") not in (None, "") else row.get("avgCost"),
        "market_price": row.get("marketPrice"),
        "market_value": row.get("marketValue"),
        "unrealized_pnl": row.get("unrealizedPNL"),
        "realized_pnl": row.get("realizedPNL"),
    }


@app.get("/api/positions")
async def positions():
    snapshot = await asyncio.get_running_loop().run_in_executor(
        BROKER_EXECUTOR, _canonical_mobile_snapshot
    )
    return _plain([_mobile_position_row(row) for row in snapshot.get("positions", [])])


@app.get("/api/orders")
async def orders():
    snapshot = await asyncio.get_running_loop().run_in_executor(
        BROKER_EXECUTOR, _canonical_mobile_snapshot
    )
    return _plain(snapshot.get("open_orders", []))


@app.get("/api/executions")
async def executions(limit: int = Query(100, ge=1, le=500)):
    # Fill-level audit view. Durable IBKR Flex ledger, not the transient Gateway session.
    return _plain(ledger_latest(limit=limit))


@app.get("/api/execution-orders")
async def execution_orders(
    side: str = Query("ALL", pattern="^(ALL|BUY|SELL)$"),
    symbol: str = Query("", max_length=16),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    # Human-facing history: one row per broker order, with fill count retained for audit.
    return _plain(ledger_order_history(side=side, symbol=symbol, limit=limit, offset=offset))


@app.get("/api/pnl")
def pnl():
    result = ledger_pnl_summary()
    result["history_status"] = "PARTIAL_HISTORY" if result.get("through") else "NO_HISTORY"
    result["source"] = "IBKR_FLEX_PLUS_PENDING_API_EXECUTIONS"
    return _plain(result)


@app.get("/api/candidate-history")
def candidate_history(days: int = Query(15, ge=1, le=90)):
    snapshots = recent_candidate_history(days=days)
    return {
        "display_days": days,
        "archive_retention": "DURABLE_NO_AUTOMATIC_DELETION",
        "additional_candidate_limit": 10,
        "snapshots": _plain(snapshots),
    }


@app.get("/api/r1000")
def r1000(q: str = "", limit: int = Query(30, ge=1, le=100)):
    return search_r1000(q, limit=limit)


@app.get("/api/r1000-meta")
def r1000_meta():
    return {"count": len(load_r1000_universe()), "source": "IWB_holdings.csv"}


@app.get("/api/r1000/{symbol}")
def r1000_symbol(symbol: str):
    item = get_r1000_symbol(symbol)
    if item is None:
        raise HTTPException(status_code=404, detail="Symbol is not in current R1000 universe")
    return item


@app.get("/api/market/{symbol}")
async def market(symbol: str):
    item = get_r1000_symbol(symbol)
    if item is None:
        raise HTTPException(status_code=404, detail="BUY symbol is not in current R1000 universe")
    def market_status(ib):
        contract = core.qualify_stock(ib, item["ibkr_symbol"])
        return core.get_market_hours_status(ib, contract)
    return _plain(await _broker_call(market_status))


@app.get("/api/order-prepare/{action}/{order_type}/{symbol}")
async def order_prepare(action: str, order_type: str, symbol: str):
    action = action.strip().upper()
    order_type = order_type.strip().upper()
    if action not in {"BUY", "SELL"} or order_type not in {"LIMIT", "MARKET"}:
        raise HTTPException(status_code=400, detail="Invalid action or order type")

    def prepare(ib):
        if action == "BUY":
            item = get_r1000_symbol(symbol)
            if item is None:
                raise core.ManualControlError("BUY symbol is not in current R1000 universe")
            contract = core.qualify_stock(ib, item["ibkr_symbol"], "USD")
        else:
            owned = [p for p in core.get_positions(ib) if float(p.get("quantity") or 0) > 0]
            position = next((p for p in owned if str(p.get("symbol") or "").upper() == symbol.upper()), None)
            if position is None:
                raise core.ManualControlError("SELL symbol is not a currently owned long position")
            contract = core.qualify_manual_contract(ib, position["contract"])
        held = max(0.0, core.current_broker_position(ib, contract, refresh=True))
        price_info = core.get_current_market_price(ib, contract)
        current_price = price_info.get("price")
        suggested = None
        if order_type == "LIMIT":
            suggested = core.suggest_buy_limit_price(price_info) if action == "BUY" else current_price
        hours = core.get_market_hours_status(ib, contract)
        return {
            "action": action,
            "order_type": order_type,
            "contract": core.contract_identity(contract),
            "current_price": current_price,
            "price_source": price_info.get("source"),
            "suggested_limit_price": suggested,
            "held_quantity": held if action == "SELL" else None,
            "allow_all": action == "SELL",
            "liquid_hours": hours,
            "market_order_warning": order_type == "MARKET",
            "submission_enabled": MUTATIONS_ENABLED,
        }
    try:
        return _plain(await _broker_call(prepare))
    except core.ManualControlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/market-hours")
async def market_hours_all():
    def read(ib):
        result = []
        for position in core.get_positions(ib):
            try:
                status = core.get_market_hours_status(ib, position["contract"])
                result.append({"symbol": position["symbol"], **status})
            except Exception as exc:
                result.append({"symbol": position["symbol"], "liquid_open": None, "detail": type(exc).__name__})
        return result
    return _plain(await _broker_call(read))


@app.get("/api/investable-capital")
async def investable_capital():
    def read(ib):
        summary = core.get_account_summary(ib)
        nlv = summary["net_liquidation"]["value"]
        if nlv is None:
            raise core.ManualControlError("IBKR NetLiquidation is unavailable")
        return core.evaluate_investable_capital_control(nlv)
    try:
        return _plain(await _broker_call(read))
    except core.ManualControlError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/mobile-capabilities")
def mobile_capabilities():
    return {
        "account_summary": True,
        "positions": True,
        "open_orders": True,
        "buy_limit": True,
        "sell_limit": True,
        "buy_market": True,
        "sell_market": True,
        "cancel_selected": False,
        "cancel_all": False,
        "liquidate_selected": False,
        "emergency_liquidate_all": False,
        "market_liquid_hours": True,
        "investable_capital_control": "READ_ONLY",
        "execution_history": True,
        "broker_mutations": MUTATIONS_ENABLED,
    }


@app.post("/api/{path:path}")
def mutations_locked(path: str):
    raise HTTPException(status_code=423, detail="Broker mutations locked until authenticated mobile API is enabled")

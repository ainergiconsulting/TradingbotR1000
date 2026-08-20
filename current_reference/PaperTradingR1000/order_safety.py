from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import math
import msvcrt
import os
from pathlib import Path
import re

import config as cfg
from logger_utils import log


FINAL_ORDER_STATES = {
    "Filled",
    "Cancelled",
    "ApiCancelled",
    "Inactive",
}
DEFAULT_EVIDENCE_TIMEOUT_SECONDS = 5
ORDER_INTENT_TTL_SECONDS = 24 * 60 * 60
ORDER_SAFETY_STATE_DIR = Path(cfg.BASE_DIR) / "state"
ENGINE_LEASE_FILE = "execution_engine.lock"
INTENT_STORE_FILE = "order_intents.json"
ORDER_LOCK_DIR = "order_locks"
ACTIVE_INTENT_STATES = {
    "PENDING_SUBMIT",
    "SUBMITTED",
    "PRESUBMITTED",
    "PENDINGSUBMIT",
    "ACTIVE",
    "UNKNOWN",
}


class LongOnlySafetyError(RuntimeError):
    pass


class LongOnlyOrderRejected(LongOnlySafetyError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


class _NonBlockingFileLease:
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"#")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            handle.close()
            raise LongOnlyOrderRejected(
                f"Order safety lease unavailable: {self.path.name}"
            ) from error
        self.handle = handle
        return self

    def release(self):
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            try:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        finally:
            self.handle.close()
            self.handle = None


class OrderIntentGuard:
    def __init__(
        self,
        ib,
        contract,
        action,
        quantity,
        *,
        allow_short=False,
        context="",
        strategy="",
        refresh=True,
        state_dir=None,
        evidence_timeout_seconds=DEFAULT_EVIDENCE_TIMEOUT_SECONDS,
    ):
        self.ib = ib
        self.contract = contract
        self.action = str(action or "").upper()
        self.quantity = quantity
        self.allow_short = allow_short
        self.context = context
        self.strategy = strategy
        self.refresh = refresh
        self.state_dir = Path(state_dir or ORDER_SAFETY_STATE_DIR)
        self.evidence_timeout_seconds = evidence_timeout_seconds
        self.account_id = None
        self.intent_key = None
        self.validation = None
        self._engine_lease = None
        self._symbol_lease = None
        self._submitted = False

    def __enter__(self):
        self.account_id = _account_id(self.ib)
        symbol = _symbol(self.contract)
        self._engine_lease = _NonBlockingFileLease(
            self.state_dir / ENGINE_LEASE_FILE
        ).acquire()
        try:
            self._symbol_lease = _NonBlockingFileLease(
                self.state_dir
                / ORDER_LOCK_DIR
                / f"{_safe_name(self.account_id)}_{_safe_name(symbol)}.lock"
            ).acquire()
            if self.action == "SELL":
                self.validation = enforce_long_only_order(
                    self.ib,
                    self.contract,
                    self.action,
                    self.quantity,
                    allow_short=self.allow_short,
                    context=self.context,
                    strategy=self.strategy,
                    refresh=self.refresh,
                    evidence_timeout_seconds=self.evidence_timeout_seconds,
                )
            self.intent_key = _intent_key(
                self.account_id,
                self.contract,
                self.action,
                self.quantity,
                self.context,
                self.strategy,
                self.validation,
            )
            self._reserve_intent()
        except Exception:
            self._release()
            raise
        return self

    def __exit__(self, exc_type, exc, _tb):
        if exc_type is not None and not self._submitted and self.intent_key:
            self._update_intent("ERROR", error=f"{exc_type.__name__}: {exc}")
        self._release()
        return False

    def _release(self):
        if self._symbol_lease is not None:
            self._symbol_lease.release()
            self._symbol_lease = None
        if self._engine_lease is not None:
            self._engine_lease.release()
            self._engine_lease = None

    def _reserve_intent(self):
        store = _load_intent_store(self.state_dir)
        existing = store.get(self.intent_key)
        if _active_duplicate(existing):
            raise LongOnlyOrderRejected(
                "Duplicate order intent rejected before broker submission: "
                f"account={self.account_id} symbol={_symbol(self.contract)} "
                f"action={self.action} quantity={self.quantity} "
                f"strategy={self.strategy} context={self.context}"
            )
        store[self.intent_key] = {
            "status": "PENDING_SUBMIT",
            "created_utc": _utc_now(),
            "updated_utc": _utc_now(),
            "account_id": self.account_id,
            "symbol": _symbol(self.contract),
            "con_id": getattr(self.contract, "conId", None),
            "action": self.action,
            "quantity": _safe_float(self.quantity, self.quantity),
            "context": self.context,
            "strategy": self.strategy,
            "validation": self.validation.to_dict()
            if self.validation is not None
            else None,
        }
        _write_intent_store(self.state_dir, store)

    def _update_intent(self, status, **extra):
        store = _load_intent_store(self.state_dir)
        record = store.get(self.intent_key, {})
        record.update(extra)
        record["status"] = status
        record["updated_utc"] = _utc_now()
        store[self.intent_key] = record
        _write_intent_store(self.state_dir, store)

    def mark_submitted(self, trade):
        status = str(getattr(getattr(trade, "orderStatus", None), "status", "") or "")
        order = getattr(trade, "order", None)
        normalized = _intent_status_from_broker(status)
        self._update_intent(
            normalized,
            broker_status=status,
            order_id=getattr(order, "orderId", None),
            perm_id=getattr(order, "permId", None),
            client_id=getattr(order, "clientId", None),
        )
        self._submitted = True


@dataclass
class LongOnlyValidationResult:
    timestamp: str
    symbol: str
    action: str
    requested_quantity: float
    broker_position: float
    pending_buy_quantity: float
    pending_sell_quantity: float
    effective_position: float
    projected_position: float
    allow_short: bool
    context: str
    strategy: str
    calling_function: str
    pending_orders: list
    call_stack: str

    def to_dict(self):
        return asdict(self)


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        if not math.isfinite(number):
            return default
        return number
    except Exception:
        return default


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "UNKNOWN"))


def _account_id(ib):
    managed = getattr(ib, "managedAccounts", None)
    if callable(managed):
        try:
            accounts = managed()
            if accounts:
                return str(accounts[0])
        except Exception:
            pass
    return "UNKNOWN_ACCOUNT"


def _intent_status_from_broker(status):
    normalized = str(status or "UNKNOWN").upper()
    if normalized in {state.upper() for state in FINAL_ORDER_STATES}:
        return normalized
    if normalized in {"PRESUBMITTED", "SUBMITTED", "PENDINGSUBMIT"}:
        return "ACTIVE"
    return "SUBMITTED" if normalized else "UNKNOWN"


def _intent_key(account_id, contract, action, quantity, context, strategy, validation):
    payload = {
        "account_id": str(account_id),
        "symbol": _symbol(contract),
        "con_id": str(getattr(contract, "conId", "") or ""),
        "sec_type": str(getattr(contract, "secType", "") or ""),
        "currency": str(getattr(contract, "currency", "") or ""),
        "action": str(action or "").upper(),
        "quantity": _safe_float(quantity, quantity),
        "context": str(context or ""),
        "strategy": str(strategy or ""),
        "broker_position": getattr(validation, "broker_position", None),
        "pending_sell_quantity": getattr(validation, "pending_sell_quantity", None),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_intent_store(state_dir):
    path = Path(state_dir) / INTENT_STORE_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as error:
        raise LongOnlyOrderRejected(
            f"Order intent store unavailable: {type(error).__name__}"
        ) from error


def _write_intent_store(state_dir, store):
    path = Path(state_dir) / INTENT_STORE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _active_duplicate(record):
    if not record:
        return False
    status = str(record.get("status", "") or "").upper()
    if status not in ACTIVE_INTENT_STATES:
        return False
    created = record.get("created_utc") or record.get("updated_utc")
    if not created:
        return True
    try:
        created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - created_dt).total_seconds()
        return age <= ORDER_INTENT_TTL_SECONDS
    except Exception:
        return True


def acquire_manual_order_intent_guard(*args, **kwargs):
    return OrderIntentGuard(*args, **kwargs)


def _contract_matches(left, right):
    if left is None or right is None:
        return False

    left_con_id = getattr(left, "conId", None)
    right_con_id = getattr(right, "conId", None)
    if left_con_id and right_con_id:
        return str(left_con_id) == str(right_con_id)

    return (
        str(getattr(left, "symbol", "")).upper()
        == str(getattr(right, "symbol", "")).upper()
        and str(getattr(left, "secType", "")).upper()
        == str(getattr(right, "secType", "")).upper()
        and str(getattr(left, "currency", "")).upper()
        == str(getattr(right, "currency", "")).upper()
    )


def _symbol(contract):
    return str(getattr(contract, "symbol", "") or "").upper()


def _call_stack_text():
    frames = []
    for frame in inspect.stack()[2:9]:
        frames.append(f"{frame.filename}:{frame.lineno}:{frame.function}")
    return " > ".join(frames)


def _calling_function():
    try:
        frame = inspect.stack()[2]
        return f"{frame.filename}:{frame.lineno}:{frame.function}"
    except Exception:
        return "unknown"


def _call_with_request_timeout(ib, method, timeout_seconds):
    sentinel = object()
    original_timeout = getattr(ib, "RequestTimeout", sentinel)
    if original_timeout is not sentinel:
        ib.RequestTimeout = timeout_seconds
    try:
        return method()
    finally:
        if original_timeout is not sentinel:
            ib.RequestTimeout = original_timeout


def _refresh_broker_evidence(ib, timeout_seconds):
    for method_name in ("reqPositions", "reqAllOpenOrders", "reqOpenOrders"):
        method = getattr(ib, method_name, None)
        if callable(method):
            _call_with_request_timeout(ib, method, timeout_seconds)


def _broker_position(ib, contract):
    total = 0.0
    sources = []

    positions = getattr(ib, "positions", None)
    if callable(positions):
        sources.append(positions)

    portfolio = getattr(ib, "portfolio", None)
    if callable(portfolio):
        sources.append(portfolio)

    if not sources:
        raise LongOnlySafetyError("No broker position source is available.")

    found_source = False
    for source in sources:
        rows = source()
        if rows is None:
            continue
        found_source = True
        for item in rows:
            item_contract = getattr(item, "contract", None)
            if _contract_matches(item_contract, contract):
                total += _safe_float(getattr(item, "position", None), 0.0)

    if not found_source:
        raise LongOnlySafetyError("Broker position source returned no evidence.")

    return total


def _remaining_quantity(order, status):
    remaining = _safe_float(getattr(status, "remaining", None))
    if remaining is not None:
        return max(0.0, remaining)

    total = _safe_float(getattr(order, "totalQuantity", None), 0.0)
    filled = _safe_float(getattr(status, "filled", None), 0.0)
    return max(0.0, total - filled)


def _dedupe_key(trade):
    order = getattr(trade, "order", None)
    status = getattr(trade, "orderStatus", None)
    contract = getattr(trade, "contract", None)
    return (
        getattr(order, "permId", None),
        getattr(order, "orderId", None),
        getattr(order, "clientId", None),
        getattr(status, "status", None),
        getattr(contract, "conId", None),
        id(trade),
    )


def _open_trades(ib, timeout_seconds):
    trades = []

    for method_name in ("reqAllOpenOrders", "reqOpenOrders"):
        method = getattr(ib, method_name, None)
        if callable(method):
            result = _call_with_request_timeout(ib, method, timeout_seconds)
            if result:
                trades.extend(result)

    open_trades = getattr(ib, "openTrades", None)
    if callable(open_trades):
        result = open_trades()
        if result:
            trades.extend(result)

    unique = {}
    for trade in trades:
        unique[_dedupe_key(trade)] = trade
    return list(unique.values())


def _pending_quantities(ib, contract, timeout_seconds):
    pending_buy = 0.0
    pending_sell = 0.0
    pending_orders = []

    for trade in _open_trades(ib, timeout_seconds):
        trade_contract = getattr(trade, "contract", None)
        if not _contract_matches(trade_contract, contract):
            continue

        order = getattr(trade, "order", None)
        status = getattr(trade, "orderStatus", None)
        status_text = str(getattr(status, "status", "") or "")
        if status_text in FINAL_ORDER_STATES:
            continue

        action = str(getattr(order, "action", "") or "").upper()
        remaining = _remaining_quantity(order, status)
        if remaining <= 0:
            continue

        if action == "BUY":
            pending_buy += remaining
        elif action == "SELL":
            pending_sell += remaining
        else:
            continue

        pending_orders.append(
            {
                "action": action,
                "remaining": remaining,
                "status": status_text,
                "order_id": getattr(order, "orderId", None),
                "perm_id": getattr(order, "permId", None),
                "client_id": getattr(order, "clientId", None),
            }
        )

    return pending_buy, pending_sell, pending_orders


def _critical_log(result, message):
    log(
        "CRITICAL LONG_ONLY_ORDER_REJECTED | "
        f"message={message} | "
        f"symbol={result.symbol} | "
        f"current_position={result.broker_position:g} | "
        f"pending_buy={result.pending_buy_quantity:g} | "
        f"pending_sell={result.pending_sell_quantity:g} | "
        f"requested_quantity={result.requested_quantity:g} | "
        f"projected_position={result.projected_position:g} | "
        f"calling_function={result.calling_function} | "
        f"strategy={result.strategy} | "
        f"pending_orders={result.pending_orders} | "
        f"call_stack={result.call_stack} | "
        f"timestamp={result.timestamp}"
    )


def enforce_long_only_order(
    ib,
    contract,
    action,
    quantity,
    *,
    allow_short=False,
    context="",
    strategy="",
    refresh=True,
    evidence_timeout_seconds=DEFAULT_EVIDENCE_TIMEOUT_SECONDS,
):
    action = str(action or "").upper()
    requested_quantity = _safe_float(quantity)

    if action != "SELL" or allow_short:
        return None

    if requested_quantity is None or requested_quantity <= 0:
        raise LongOnlySafetyError("SELL quantity must be a positive finite number.")

    try:
        if refresh:
            _refresh_broker_evidence(ib, evidence_timeout_seconds)
        broker_position = _broker_position(ib, contract)
        pending_buy, pending_sell, pending_orders = _pending_quantities(
            ib, contract, evidence_timeout_seconds
        )
    except Exception as error:
        timestamp = datetime.now(timezone.utc).isoformat()
        symbol = _symbol(contract)
        message = (
            "Long-only validation failed closed because broker position/open-order "
            f"evidence was unavailable: {type(error).__name__}"
        )
        log(
            "CRITICAL LONG_ONLY_EVIDENCE_UNAVAILABLE | "
            f"symbol={symbol} | requested_quantity={requested_quantity:g} | "
            f"calling_function={_calling_function()} | strategy={strategy} | "
            f"call_stack={_call_stack_text()} | timestamp={timestamp} | "
            f"error={repr(error)}"
        )
        raise LongOnlyOrderRejected(message) from error

    # Pending BUY orders are not owned shares yet; do not let them increase
    # sellable quantity because a SELL can fill before the BUY.
    effective_position = broker_position - pending_sell
    projected_position = effective_position - requested_quantity

    result = LongOnlyValidationResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        symbol=_symbol(contract),
        action=action,
        requested_quantity=requested_quantity,
        broker_position=broker_position,
        pending_buy_quantity=pending_buy,
        pending_sell_quantity=pending_sell,
        effective_position=effective_position,
        projected_position=projected_position,
        allow_short=bool(allow_short),
        context=context,
        strategy=strategy,
        calling_function=_calling_function(),
        pending_orders=pending_orders,
        call_stack=_call_stack_text(),
    )

    if projected_position < 0:
        message = (
            f"SELL rejected for {result.symbol}: projected position "
            f"{projected_position:g} would create or increase a short position."
        )
        _critical_log(result, message)
        raise LongOnlyOrderRejected(message, result=result)

    return result


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    action: str
    quantity: float
    limit_price: float | None
    reason: str


def _strategy_intent_key(intent: OrderIntent) -> str:
    payload = json.dumps(asdict(intent), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_long_only_order(intent: OrderIntent, current_position: float = 0.0) -> None:
    if intent.quantity <= 0:
        raise LongOnlyOrderRejected("order quantity must be positive")
    action = intent.action.upper()
    if action == "BUY":
        return
    if action == "SELL":
        if current_position - intent.quantity < -1e-9:
            raise LongOnlyOrderRejected("sell quantity would create a short position")
        return
    raise LongOnlyOrderRejected(f"unsupported order action:{intent.action}")


def _record_strategy_order_intent(intent: OrderIntent) -> dict:
    state_dir = ORDER_SAFETY_STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    key = _strategy_intent_key(intent)
    store = _load_intent_store(state_dir)
    if key in store:
        raise LongOnlyOrderRejected("duplicate order intent already recorded")
    store[key] = {
        "status": "RECORDED",
        "created_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "intent": asdict(intent),
    }
    _write_intent_store(state_dir, store)
    log("order intent guarded", extra={"symbol": intent.symbol, "action": intent.action})
    return store[key]


def acquire_order_intent_guard(*args, **kwargs):
    if len(args) == 1 and isinstance(args[0], OrderIntent) and not kwargs:
        return _record_strategy_order_intent(args[0])
    return acquire_manual_order_intent_guard(*args, **kwargs)


def build_buy_intent(symbol: str, quantity: float, limit_price: float, reason: str) -> OrderIntent:
    return OrderIntent(
        symbol=str(symbol or "").upper(),
        action="BUY",
        quantity=float(quantity),
        limit_price=float(limit_price),
        reason=str(reason or ""),
    )


def build_exit_intent(symbol: str, quantity: float, reason: str) -> OrderIntent:
    return OrderIntent(
        symbol=str(symbol or "").upper(),
        action="SELL",
        quantity=float(quantity),
        limit_price=None,
        reason=str(reason or ""),
    )

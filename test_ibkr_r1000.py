#!/usr/bin/env python3
"""Test IBKR historical daily data coverage for the full IWB/Russell 1000 universe.

Input: the official iShares IWB holdings CSV (including its metadata rows).
Output directory:
  - historical_bars.csv
  - request_report.csv
  - run_summary.json
  - ibkr_r1000_test.log

The script first qualifies each equity contract through reqContractDetails and then
requests the latest two calendar days of 1-day ADJUSTED_LAST bars.

Run only while TWS or IB Gateway is open and API connections are enabled.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import queue
import signal
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Tuple

try:
    from ibapi.client import EClient
    from ibapi.contract import Contract, ContractDetails
    from ibapi.wrapper import EWrapper
except ImportError as exc:
    raise SystemExit(
        "Modulo 'ibapi' non trovato. Installa la TWS API Python di IBKR "
        "e riprova."
    ) from exc


HEADER_NAME = "Ticker"
TERMINAL_ERROR_CODES = {
    200,   # No security definition found
    321,   # Validation error
    354,   # Market data not subscribed (may also affect historical data)
    366,   # No historical data query found for ticker id
    420,   # Invalid real-time query / pacing-related validation
    162,   # Historical market data service error
    10167, # Requested market data is not subscribed / delayed not enabled
}
IGNORABLE_ERROR_CODES = {
    2104, 2106, 2107, 2108, 2158,  # farm status messages
}

# iShares exchange labels -> IBKR primaryExchange values.
PRIMARY_EXCHANGE_MAP = {
    "NASDAQ": "NASDAQ",
    "NEW YORK STOCK EXCHANGE INC.": "NYSE",
    "NYSE": "NYSE",
    "NYSE ARCA": "ARCA",
    "ARCA": "ARCA",
    "CBOE BZX": "BATS",
    "BATS": "BATS",
    "NYSE AMERICAN": "AMEX",
    "AMEX": "AMEX",
}


@dataclass
class Holding:
    original_ticker: str
    ibkr_symbol: str
    name: str
    asset_class: str
    exchange: str
    currency: str


@dataclass
class BarRecord:
    original_ticker: str
    ibkr_symbol: str
    con_id: int
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: str
    bar_count: int
    wap: str


@dataclass
class ResultRecord:
    original_ticker: str
    ibkr_symbol: str
    name: str
    source_exchange: str
    status: str = "PENDING"
    con_id: Optional[int] = None
    qualified_symbol: Optional[str] = None
    primary_exchange: Optional[str] = None
    bars_received: int = 0
    latest_bar_date: Optional[str] = None
    attempts: int = 0
    elapsed_seconds: float = 0.0
    error_code: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class RequestState:
    kind: str  # "contract" or "history"
    holding: Holding
    result: ResultRecord
    contract: Contract
    started_at: float
    attempt: int
    deadline: float
    contract_candidates: List[ContractDetails] = field(default_factory=list)
    bars: List[BarRecord] = field(default_factory=list)


class IBKRFullUniverseTest(EWrapper, EClient):
    def __init__(
        self,
        holdings: List[Holding],
        max_in_flight: int,
        request_interval: float,
        timeout_seconds: float,
        max_retries: int,
        logger: logging.Logger,
    ) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.holdings = holdings
        self.max_in_flight = max_in_flight
        self.request_interval = request_interval
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.log = logger

        self.connected_event = threading.Event()
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.events: "queue.Queue[Tuple[str, int, object]]" = queue.Queue()
        self.pending: Dict[int, RequestState] = {}
        self.results: Dict[str, ResultRecord] = {
            h.original_ticker: ResultRecord(
                original_ticker=h.original_ticker,
                ibkr_symbol=h.ibkr_symbol,
                name=h.name,
                source_exchange=h.exchange,
            )
            for h in holdings
        }
        self.all_bars: List[BarRecord] = []
        self.req_id = 1

    # ---------- IB callbacks ----------
    def nextValidId(self, orderId: int) -> None:  # noqa: N802 (IB API naming)
        self.connected_event.set()
        self.log.info("Connessione API pronta; nextValidId=%s", orderId)

    def connectionClosed(self) -> None:  # noqa: N802
        self.log.error("Connessione IBKR chiusa.")
        self.stop_event.set()

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson="") -> None:  # noqa: N802
        if errorCode in IGNORABLE_ERROR_CODES:
            self.log.info("IBKR status %s: %s", errorCode, errorString)
            return

        if reqId == -1:
            self.log.warning("IBKR message %s: %s", errorCode, errorString)
            return

        self.log.warning("IBKR error reqId=%s code=%s: %s", reqId, errorCode, errorString)
        if errorCode in TERMINAL_ERROR_CODES:
            self.events.put(("error", int(reqId), (int(errorCode), str(errorString))))

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:  # noqa: N802
        with self.lock:
            state = self.pending.get(reqId)
            if state and state.kind == "contract":
                state.contract_candidates.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.events.put(("contract_end", reqId, None))

    def historicalData(self, reqId: int, bar) -> None:  # noqa: N802
        with self.lock:
            state = self.pending.get(reqId)
            if not state or state.kind != "history":
                return
            contract = state.contract
            record = BarRecord(
                original_ticker=state.holding.original_ticker,
                ibkr_symbol=contract.symbol,
                con_id=int(contract.conId or 0),
                date=str(bar.date),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=str(bar.volume),
                bar_count=int(bar.barCount),
                wap=str(bar.average),
            )
            state.bars.append(record)

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        self.events.put(("history_end", reqId, (start, end)))

    # ---------- orchestration ----------
    def next_req_id(self) -> int:
        with self.lock:
            value = self.req_id
            self.req_id += 1
            return value

    def run_test(self) -> Tuple[List[ResultRecord], List[BarRecord]]:
        contract_queue: Deque[Tuple[Holding, int]] = deque((h, 1) for h in self.holdings)
        history_queue: Deque[Tuple[Holding, Contract, int]] = deque()
        last_request_time = 0.0
        completed = 0
        total = len(self.holdings)
        started = time.monotonic()

        while completed < total and not self.stop_event.is_set():
            now = time.monotonic()

            # Start new requests up to the configured concurrency limit.
            while len(self.pending) < self.max_in_flight:
                wait_left = self.request_interval - (time.monotonic() - last_request_time)
                if wait_left > 0:
                    break

                if history_queue:
                    holding, contract, attempt = history_queue.popleft()
                    self._start_history(holding, contract, attempt)
                    last_request_time = time.monotonic()
                elif contract_queue:
                    holding, attempt = contract_queue.popleft()
                    self._start_contract(holding, attempt)
                    last_request_time = time.monotonic()
                else:
                    break

            # Process callbacks without blocking the network thread.
            try:
                event_type, req_id, payload = self.events.get(timeout=0.10)
                finished = self._process_event(
                    event_type,
                    req_id,
                    payload,
                    contract_queue,
                    history_queue,
                )
                completed += finished
                if finished:
                    self._log_progress(completed, total, started)
            except queue.Empty:
                pass

            # Handle timeouts.
            now = time.monotonic()
            timed_out = []
            with self.lock:
                for req_id, state in list(self.pending.items()):
                    if now >= state.deadline:
                        timed_out.append((req_id, state))

            for req_id, state in timed_out:
                self.log.warning(
                    "Timeout %s per %s (tentativo %s)",
                    state.kind,
                    state.holding.original_ticker,
                    state.attempt,
                )
                if state.kind == "history":
                    try:
                        self.cancelHistoricalData(req_id)
                    except Exception:
                        pass
                with self.lock:
                    self.pending.pop(req_id, None)

                if state.attempt <= self.max_retries:
                    if state.kind == "contract":
                        contract_queue.append((state.holding, state.attempt + 1))
                    else:
                        history_queue.append((state.holding, state.contract, state.attempt + 1))
                else:
                    self._mark_failed(state, None, f"Timeout {state.kind}")
                    completed += 1
                    self._log_progress(completed, total, started)

            # Avoid a busy loop while respecting request_interval.
            time.sleep(0.01)

        if self.stop_event.is_set() and completed < total:
            self.log.error("Test interrotto: completati %s di %s titoli.", completed, total)

        ordered_results = [self.results[h.original_ticker] for h in self.holdings]
        return ordered_results, self.all_bars

    def _start_contract(self, holding: Holding, attempt: int) -> None:
        contract = Contract()
        contract.symbol = holding.ibkr_symbol
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = holding.currency or "USD"
        mapped = PRIMARY_EXCHANGE_MAP.get(holding.exchange.upper().strip())
        if mapped:
            contract.primaryExchange = mapped

        req_id = self.next_req_id()
        result = self.results[holding.original_ticker]
        result.attempts = max(result.attempts, attempt)
        state = RequestState(
            kind="contract",
            holding=holding,
            result=result,
            contract=contract,
            started_at=time.monotonic(),
            attempt=attempt,
            deadline=time.monotonic() + self.timeout_seconds,
        )
        with self.lock:
            self.pending[req_id] = state
        self.log.debug("Contract reqId=%s %s", req_id, holding.original_ticker)
        self.reqContractDetails(req_id, contract)

    def _start_history(self, holding: Holding, contract: Contract, attempt: int) -> None:
        req_id = self.next_req_id()
        result = self.results[holding.original_ticker]
        result.attempts = max(result.attempts, attempt)
        state = RequestState(
            kind="history",
            holding=holding,
            result=result,
            contract=contract,
            started_at=time.monotonic(),
            attempt=attempt,
            deadline=time.monotonic() + self.timeout_seconds,
        )
        with self.lock:
            self.pending[req_id] = state
        self.log.debug("History reqId=%s %s conId=%s", req_id, holding.original_ticker, contract.conId)
        self.reqHistoricalData(
            req_id,
            contract,
            "",              # now
            "2 D",
            "1 day",
            "ADJUSTED_LAST",
            1,               # regular trading hours only
            1,               # yyyyMMdd for daily bars
            False,
            [],
        )

    def _process_event(
        self,
        event_type: str,
        req_id: int,
        payload: object,
        contract_queue: Deque[Tuple[Holding, int]],
        history_queue: Deque[Tuple[Holding, Contract, int]],
    ) -> int:
        with self.lock:
            state = self.pending.pop(req_id, None)
        if state is None:
            return 0

        elapsed = time.monotonic() - state.started_at

        if event_type == "error":
            code, message = payload  # type: ignore[misc]
            if state.attempt <= self.max_retries:
                self.log.info(
                    "Retry %s %s dopo errore %s",
                    state.kind,
                    state.holding.original_ticker,
                    code,
                )
                if state.kind == "contract":
                    contract_queue.append((state.holding, state.attempt + 1))
                else:
                    history_queue.append((state.holding, state.contract, state.attempt + 1))
                return 0
            self._mark_failed(state, int(code), str(message))
            return 1

        if event_type == "contract_end":
            chosen = choose_contract(state.holding, state.contract_candidates)
            if chosen is None:
                if state.attempt <= self.max_retries:
                    contract_queue.append((state.holding, state.attempt + 1))
                    return 0
                self._mark_failed(state, 200, "Nessun contratto azionario USD qualificato")
                return 1

            result = state.result
            result.con_id = int(chosen.conId)
            result.qualified_symbol = str(chosen.symbol)
            result.primary_exchange = str(chosen.primaryExchange or "")
            result.elapsed_seconds += elapsed
            history_queue.append((state.holding, chosen, 1))
            return 0

        if event_type == "history_end":
            result = state.result
            result.elapsed_seconds += elapsed
            if not state.bars:
                if state.attempt <= self.max_retries:
                    history_queue.append((state.holding, state.contract, state.attempt + 1))
                    return 0
                self._mark_failed(state, 366, "IBKR non ha restituito barre")
                return 1

            state.bars.sort(key=lambda b: b.date)
            self.all_bars.extend(state.bars)
            result.status = "SUCCESS"
            result.bars_received = len(state.bars)
            result.latest_bar_date = state.bars[-1].date
            result.error_code = None
            result.error_message = None
            return 1

        # Unexpected callback: put state back so it can time out rather than vanish.
        with self.lock:
            self.pending[req_id] = state
        return 0

    def _mark_failed(self, state: RequestState, code: Optional[int], message: str) -> None:
        result = state.result
        result.status = "FAILED"
        result.elapsed_seconds += time.monotonic() - state.started_at
        result.error_code = code
        result.error_message = message

    def _log_progress(self, completed: int, total: int, started: float) -> None:
        successes = sum(1 for r in self.results.values() if r.status == "SUCCESS")
        failures = sum(1 for r in self.results.values() if r.status == "FAILED")
        elapsed = time.monotonic() - started
        self.log.info(
            "Progresso %s/%s | successi=%s errori=%s | %.1f min",
            completed,
            total,
            successes,
            failures,
            elapsed / 60.0,
        )


def normalize_ibkr_symbol(ticker: str) -> str:
    """Convert common class-share notation to IBKR's stock symbol notation."""
    return ticker.strip().upper().replace(".", " ")


def load_iwb_holdings(path: Path) -> List[Holding]:
    """Read the official iShares CSV even when metadata precedes the table."""
    text = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    header_index = None
    for index, line in enumerate(text):
    row = next(csv.reader([line]), [])

    if not row:
        continue

    first_cell = row[0].strip()

    if first_cell == HEADER_NAME:
        header_index = index
        break
    if header_index is None:
        raise ValueError("Intestazione 'Ticker' non trovata nel CSV.")

    reader = csv.DictReader(text[header_index:])
    holdings: List[Holding] = []
    seen = set()
    for row in reader:
        ticker = (row.get("Ticker") or "").strip().upper()
        asset_class = (row.get("Asset Class") or "").strip()
        currency = (row.get("Currency") or "USD").strip().upper()
        if not ticker or ticker == "-":
            continue
        if asset_class.lower() != "equity":
            continue
        if currency != "USD":
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        holdings.append(
            Holding(
                original_ticker=ticker,
                ibkr_symbol=normalize_ibkr_symbol(ticker),
                name=(row.get("Name") or "").strip(),
                asset_class=asset_class,
                exchange=(row.get("Exchange") or "").strip(),
                currency=currency,
            )
        )
    if not holdings:
        raise ValueError("Nessun titolo Equity USD trovato nel CSV.")
    return holdings


def choose_contract(holding: Holding, candidates: Iterable[ContractDetails]) -> Optional[Contract]:
    """Select the best matching USD stock contract returned by IBKR."""
    candidates = list(candidates)
    if not candidates:
        return None

    expected_primary = PRIMARY_EXCHANGE_MAP.get(holding.exchange.upper().strip(), "")

    def score(details: ContractDetails) -> Tuple[int, int, int, int]:
        c = details.contract
        return (
            1 if c.secType == "STK" else 0,
            1 if c.currency == "USD" else 0,
            1 if c.symbol.upper() == holding.ibkr_symbol.upper() else 0,
            1 if expected_primary and c.primaryExchange == expected_primary else 0,
        )

    valid = [d for d in candidates if d.contract.secType == "STK" and d.contract.currency == "USD"]
    if not valid:
        return None
    best = max(valid, key=score).contract

    qualified = Contract()
    qualified.conId = best.conId
    qualified.symbol = best.symbol
    qualified.secType = best.secType
    qualified.exchange = "SMART"
    qualified.primaryExchange = best.primaryExchange
    qualified.currency = best.currency
    qualified.localSymbol = best.localSymbol
    qualified.tradingClass = best.tradingClass
    return qualified


def configure_logging(output_dir: Path, verbose: bool) -> logging.Logger:
    logger = logging.getLogger("ibkr-r1000-test")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(output_dir / "ibkr_r1000_test.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


def write_outputs(
    output_dir: Path,
    results: List[ResultRecord],
    bars: List[BarRecord],
    started_at_utc: str,
    elapsed_seconds: float,
    input_file: Path,
    args: argparse.Namespace,
) -> None:
    report_path = output_dir / "request_report.csv"
    with report_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = list(asdict(results[0]).keys()) if results else []
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))

    bars_path = output_dir / "historical_bars.csv"
    with bars_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = list(asdict(bars[0]).keys()) if bars else [
            "original_ticker", "ibkr_symbol", "con_id", "date", "open", "high",
            "low", "close", "volume", "bar_count", "wap",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for bar in bars:
            writer.writerow(asdict(bar))

    success_count = sum(1 for r in results if r.status == "SUCCESS")
    failure_count = sum(1 for r in results if r.status == "FAILED")
    summary = {
        "started_at_utc": started_at_utc,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "elapsed_minutes": round(elapsed_seconds / 60.0, 3),
        "input_file": str(input_file.resolve()),
        "titles_tested": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate_percent": round((success_count / len(results) * 100.0), 4) if results else 0,
        "bars_received": len(bars),
        "connection": {
            "host": args.host,
            "port": args.port,
            "client_id": args.client_id,
        },
        "request_settings": {
            "max_in_flight": args.max_in_flight,
            "request_interval_seconds": args.request_interval,
            "timeout_seconds": args.timeout,
            "max_retries": args.retries,
            "duration": "2 D",
            "bar_size": "1 day",
            "what_to_show": "ADJUSTED_LAST",
            "use_rth": True,
        },
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test IBKR ADJUSTED_LAST per tutti i titoli Equity USD del file IWB."
    )
    parser.add_argument("csv_file", type=Path, help="File CSV ufficiale delle holdings IWB")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=7497,
        help="7497 TWS paper; 7496 TWS live; 4002 Gateway paper; 4001 Gateway live",
    )
    parser.add_argument("--client-id", type=int, default=81)
    parser.add_argument("--max-in-flight", type=int, default=8)
    parser.add_argument("--request-interval", type=float, default=0.30)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=Path("ibkr_r1000_results"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.max_in_flight < 1 or args.max_in_flight > 40:
        parser.error("--max-in-flight deve essere compreso tra 1 e 40")
    if args.request_interval < 0:
        parser.error("--request-interval non può essere negativo")
    if args.timeout <= 0:
        parser.error("--timeout deve essere positivo")
    if args.retries < 0:
        parser.error("--retries non può essere negativo")
    return args


def main() -> int:
    args = parse_args()
    if not args.csv_file.exists():
        raise SystemExit(f"File non trovato: {args.csv_file}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    logger = configure_logging(args.output_dir, args.verbose)

    try:
        holdings = load_iwb_holdings(args.csv_file)
    except Exception as exc:
        logger.exception("Errore nella lettura del CSV: %s", exc)
        return 2

    logger.info("Titoli Equity USD unici caricati: %s", len(holdings))
    logger.info(
        "Connessione a IBKR %s:%s clientId=%s",
        args.host,
        args.port,
        args.client_id,
    )

    app = IBKRFullUniverseTest(
        holdings=holdings,
        max_in_flight=args.max_in_flight,
        request_interval=args.request_interval,
        timeout_seconds=args.timeout,
        max_retries=args.retries,
        logger=logger,
    )

    def stop_handler(signum, frame) -> None:
        logger.warning("Segnale %s ricevuto: arresto richiesto.", signum)
        app.stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        app.connect(args.host, args.port, clientId=args.client_id)
    except Exception as exc:
        logger.exception("Connessione iniziale fallita: %s", exc)
        return 3

    network_thread = threading.Thread(target=app.run, name="ibkr-network", daemon=True)
    network_thread.start()

    if not app.connected_event.wait(timeout=15):
        logger.error(
            "IBKR non ha completato la connessione entro 15 secondi. "
            "Controlla TWS/Gateway, porta e impostazioni API."
        )
        app.disconnect()
        return 4

    started_at_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    try:
        results, bars = app.run_test()
    finally:
        elapsed = time.monotonic() - started
        if app.isConnected():
            app.disconnect()
        network_thread.join(timeout=5)

    write_outputs(
        output_dir=args.output_dir,
        results=results,
        bars=bars,
        started_at_utc=started_at_utc,
        elapsed_seconds=elapsed,
        input_file=args.csv_file,
        args=args,
    )

    success_count = sum(1 for r in results if r.status == "SUCCESS")
    failure_count = sum(1 for r in results if r.status == "FAILED")
    logger.info("Test terminato in %.1f minuti.", elapsed / 60.0)
    logger.info("Successi: %s | Errori: %s", success_count, failure_count)
    logger.info("Output: %s", args.output_dir.resolve())
    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

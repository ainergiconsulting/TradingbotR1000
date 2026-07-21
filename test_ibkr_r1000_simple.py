#!/usr/bin/env python3
"""Test completo dei dati storici IBKR sull'universo IWB/Russell 1000.

Uso (IB Gateway Paper):
    python test_ibkr_r1000_simple.py IWB_holdings.csv --port 4002

Requisiti:
    python -m pip install ibapi

IB Gateway deve essere aperto, collegato e configurato per accettare connessioni API.
Lo script non invia ordini.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    from ibapi.client import EClient
    from ibapi.contract import Contract, ContractDetails
    from ibapi.wrapper import EWrapper
except ImportError:
    raise SystemExit(
        "Modulo ibapi non installato. Esegui: python -m pip install ibapi"
    )


@dataclass
class Holding:
    ticker: str
    name: str
    exchange: str


class IBApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.connected_event = threading.Event()
        self.next_order_id: Optional[int] = None
        self.accounts: List[str] = []

        self._lock = threading.Lock()
        self._next_req_id = 1
        self.contract_requests: Dict[int, dict] = {}
        self.history_requests: Dict[int, dict] = {}

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.connected_event.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [x.strip() for x in accountsList.split(",") if x.strip()]

    def connectionClosed(self) -> None:  # noqa: N802
        print("\nConnessione IBKR chiusa.")

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson="") -> None:  # noqa: N802
        message = f"{errorCode}: {errorString}"

        # Messaggi informativi comuni della farm dati: non sono errori del test.
        if errorCode in {2104, 2106, 2107, 2108, 2158}:
            return

        with self._lock:
            if reqId in self.contract_requests:
                self.contract_requests[reqId]["errors"].append(message)
            if reqId in self.history_requests:
                self.history_requests[reqId]["errors"].append(message)

        if reqId == -1:
            print(f"IBKR: {message}")

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:  # noqa: N802
        with self._lock:
            state = self.contract_requests.get(reqId)
            if state is not None:
                state["details"].append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        with self._lock:
            state = self.contract_requests.get(reqId)
            if state is not None:
                state["event"].set()

    def historicalData(self, reqId, bar) -> None:  # noqa: N802
        with self._lock:
            state = self.history_requests.get(reqId)
            if state is not None:
                state["bars"].append(
                    {
                        "date": str(bar.date),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "bar_count": bar.barCount,
                        "average": bar.average,
                    }
                )

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        with self._lock:
            state = self.history_requests.get(reqId)
            if state is not None:
                state["event"].set()

    def new_req_id(self) -> int:
        with self._lock:
            req_id = self._next_req_id
            self._next_req_id += 1
            return req_id

    def qualify_contract(self, holding: Holding, timeout: float) -> tuple[Optional[Contract], str]:
        req_id = self.new_req_id()
        event = threading.Event()
        self.contract_requests[req_id] = {"event": event, "details": [], "errors": []}

        contract = Contract()
        contract.symbol = ibkr_symbol(holding.ticker)
        contract.secType = "STK"
        contract.exchange = "SMART"
        contract.currency = "USD"

        self.reqContractDetails(req_id, contract)
        completed = event.wait(timeout)

        with self._lock:
            state = self.contract_requests.pop(req_id)

        if not completed:
            if not completed:
    return None, "Timeout qualificazione contratto"
            return None, "Timeout qualificazione contratto"

        details: List[ContractDetails] = state["details"]
        errors: List[str] = state["errors"]

        if not details:
            return None, "; ".join(errors) or "Contratto non trovato"

        # Preferisce un contratto azionario USA in USD su SMART.
        candidates = [
            d.contract
            for d in details
            if d.contract.secType == "STK" and d.contract.currency == "USD"
        ]
        if not candidates:
            candidates = [d.contract for d in details]

        selected = candidates[0]
        selected.exchange = "SMART"
        return selected, ""

    def request_daily_bars(self, contract: Contract, timeout: float) -> tuple[List[dict], str]:
        req_id = self.new_req_id()
        event = threading.Event()
        self.history_requests[req_id] = {"event": event, "bars": [], "errors": []}

        self.reqHistoricalData(
            req_id,
            contract,
            "",
            "2 D",
            "1 day",
            "ADJUSTED_LAST",
            1,
            1,
            False,
            [],
        )

        completed = event.wait(timeout)

        if not completed:
            self.cancelHistoricalData(req_id)

        with self._lock:
            state = self.history_requests.pop(req_id)

        bars: List[dict] = state["bars"]
        errors: List[str] = state["errors"]

        if not completed:
            return bars, "; ".join(errors) or "Timeout dati storici"
        if not bars:
            return [], "; ".join(errors) or "Nessuna barra ricevuta"
        return bars, ""


def ibkr_symbol(ticker: str) -> str:
    """Converte ticker come BRK.B nel formato IBKR BRK B."""
    return ticker.strip().upper().replace(".", " ")


def load_iwb_holdings(path: Path) -> List[Holding]:
    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {path}")

    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    header_index: Optional[int] = None

    for index, line in enumerate(lines):
        if not line.strip():
            continue
        row = next(csv.reader([line]), [])
        if row and row[0].strip().lower() == "ticker":
            header_index = index
            break

    if header_index is None:
        raise ValueError("Intestazione 'Ticker' non trovata nel CSV iShares.")

    reader = csv.DictReader(lines[header_index:])
    holdings: List[Holding] = []
    seen = set()

    for row in reader:
        ticker = (row.get("Ticker") or "").strip().upper()
        name = (row.get("Name") or "").strip()
        asset_class = (row.get("Asset Class") or "").strip().lower()
        currency = (row.get("Currency") or "").strip().upper()
        exchange = (row.get("Exchange") or "").strip()

        if not ticker or ticker == "-":
            continue
        if asset_class and asset_class != "equity":
            continue
        if currency and currency != "USD":
            continue
        if ticker in seen:
            continue

        seen.add(ticker)
        holdings.append(Holding(ticker=ticker, name=name, exchange=exchange))

    if not holdings:
        raise ValueError("Nessun titolo azionario USD trovato nel CSV.")

    return holdings


def write_csv(path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test IBKR ADJUSTED_LAST sull'intero universo IWB/Russell 1000."
    )
    parser.add_argument("csv_file", type=Path, help="File ufficiale IWB holdings CSV")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4002, help="4002 Gateway Paper; 4001 Gateway Live")
    parser.add_argument("--client-id", type=int, default=81)
    parser.add_argument("--timeout", type=float, default=25.0, help="Timeout per richiesta in secondi")
    parser.add_argument("--retries", type=int, default=1, help="Numero di retry dopo il primo tentativo")
    parser.add_argument("--delay", type=float, default=0.25, help="Pausa fra titoli in secondi")
    parser.add_argument("--output", type=Path, default=Path("ibkr_r1000_results"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        holdings = load_iwb_holdings(args.csv_file)
    except Exception as exc:
        print(f"ERRORE CSV: {exc}")
        return 1

    print(f"Ticker azionari USD trovati: {len(holdings)}")
    print(f"Connessione a IB Gateway {args.host}:{args.port}, client ID {args.client_id}...")

    app = IBApp()
    try:
        app.connect(args.host, args.port, clientId=args.client_id)
    except Exception as exc:
        print(f"ERRORE connessione: {exc}")
        return 2

    api_thread = threading.Thread(target=app.run, name="IBAPI", daemon=True)
    api_thread.start()

    if not app.connected_event.wait(15):
        print("ERRORE: IB Gateway non ha completato la connessione API entro 15 secondi.")
        app.disconnect()
        return 2

    time.sleep(1.0)
    account_text = ", ".join(app.accounts) if app.accounts else "non comunicato"
    print(f"Connesso. Account: {account_text}")
    print("Avvio del test completo. Interrompi con Ctrl+C; i risultati parziali saranno salvati.\n")

    started = time.time()
    report_rows: List[dict] = []
    bar_rows: List[dict] = []

    try:
        for index, holding in enumerate(holdings, start=1):
            ticker_started = time.time()
            status = "ERROR"
            error_message = ""
            bars: List[dict] = []
            contract: Optional[Contract] = None
            attempts_used = 0

            for attempt in range(1, args.retries + 2):
                attempts_used = attempt
                contract, error_message = app.qualify_contract(holding, args.timeout)
                if contract is None:
                    if attempt <= args.retries:
                        time.sleep(1.0)
                        continue
                    break

                bars, error_message = app.request_daily_bars(contract, args.timeout)
                if bars:
                    status = "OK"
                    break

                if attempt <= args.retries:
                    time.sleep(1.5)

            elapsed = time.time() - ticker_started
            con_id = contract.conId if contract is not None else ""
            local_symbol = contract.localSymbol if contract is not None else ""
            primary_exchange = contract.primaryExchange if contract is not None else ""

            for bar in bars:
                bar_rows.append(
                    {
                        "ticker": holding.ticker,
                        "name": holding.name,
                        "con_id": con_id,
                        "local_symbol": local_symbol,
                        **bar,
                    }
                )

            report_rows.append(
                {
                    "ticker": holding.ticker,
                    "name": holding.name,
                    "status": status,
                    "bars_received": len(bars),
                    "attempts": attempts_used,
                    "elapsed_seconds": round(elapsed, 3),
                    "con_id": con_id,
                    "local_symbol": local_symbol,
                    "primary_exchange": primary_exchange,
                    "error": error_message,
                }
            )

            ok_count = sum(1 for row in report_rows if row["status"] == "OK")
            print(
                f"[{index:4d}/{len(holdings)}] {holding.ticker:<8} "
                f"{status:<5} barre={len(bars)} tempo={elapsed:.1f}s "
                f"successi={ok_count}"
            )
            time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\nInterruzione richiesta. Salvataggio dei risultati parziali...")
    finally:
        app.disconnect()

    args.output.mkdir(parents=True, exist_ok=True)

    report_path = args.output / "request_report.csv"
    bars_path = args.output / "historical_bars.csv"
    summary_path = args.output / "run_summary.json"

    write_csv(
        report_path,
        [
            "ticker", "name", "status", "bars_received", "attempts",
            "elapsed_seconds", "con_id", "local_symbol", "primary_exchange", "error",
        ],
        report_rows,
    )
    write_csv(
        bars_path,
        [
            "ticker", "name", "con_id", "local_symbol", "date", "open", "high",
            "low", "close", "volume", "bar_count", "average",
        ],
        bar_rows,
    )

    total_elapsed = time.time() - started
    success_count = sum(1 for row in report_rows if row["status"] == "OK")
    failure_count = len(report_rows) - success_count
    success_rate = (success_count / len(report_rows) * 100.0) if report_rows else 0.0

    summary = {
        "run_finished_local": datetime.now().isoformat(timespec="seconds"),
        "host": args.host,
        "port": args.port,
        "client_id": args.client_id,
        "accounts": app.accounts,
        "universe_size": len(holdings),
        "processed": len(report_rows),
        "successes": success_count,
        "failures": failure_count,
        "success_rate_percent": round(success_rate, 3),
        "elapsed_seconds": round(total_elapsed, 3),
        "request": {
            "duration": "2 D",
            "bar_size": "1 day",
            "what_to_show": "ADJUSTED_LAST",
            "use_rth": 1,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== RISULTATO ===")
    print(f"Elaborati: {len(report_rows)} / {len(holdings)}")
    print(f"Successi:  {success_count}")
    print(f"Errori:    {failure_count}")
    print(f"Successo:  {success_rate:.2f}%")
    print(f"Tempo:     {total_elapsed / 60:.1f} minuti")
    print(f"Report:    {report_path.resolve()}")
    print(f"Barre:     {bars_path.resolve()}")
    print(f"Riepilogo: {summary_path.resolve()}")

    return 0 if report_rows and failure_count == 0 else 3


if __name__ == "__main__":
    sys.exit(main())

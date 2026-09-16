from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

import config as cfg
from symbol_mapping import canonical_symbol, expected_ibkr_primary_exchange, ibkr_symbol

UNIVERSE_FILE = Path(cfg.PROJECT_ROOT) / "IWB_holdings.csv"
REQUIRED_COLUMNS = {"Ticker", "Name", "Sector", "Asset Class", "Exchange", "Currency"}


class R1000UniverseError(RuntimeError):
    pass


def _find_header(rows: list[list[str]]) -> tuple[int, list[str]]:
    for index, row in enumerate(rows):
        if row and row[0].strip() == "Ticker":
            return index, [str(value or "").strip() for value in row]
    raise R1000UniverseError("Ticker header not found in IWB holdings file.")


@lru_cache(maxsize=4)
def _load_cached(path_text: str, mtime_ns: int, size: int) -> tuple[dict, ...]:
    path = Path(path_text)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
    except Exception as error:
        raise R1000UniverseError(f"Unable to read R1000 universe: {type(error).__name__}") from error

    header_index, header = _find_header(rows)
    missing = REQUIRED_COLUMNS.difference(header)
    if missing:
        raise R1000UniverseError("R1000 universe missing required columns: " + ", ".join(sorted(missing)))

    items: list[dict] = []
    seen: set[str] = set()
    for values in rows[header_index + 1 :]:
        if len(values) < len(header):
            continue
        raw = dict(zip(header, values))
        if str(raw.get("Asset Class") or "").strip().upper() != "EQUITY":
            continue
        if str(raw.get("Currency") or "").strip().upper() != "USD":
            continue
        source_symbol = str(raw.get("Ticker") or "").strip().upper()
        symbol = canonical_symbol(source_symbol)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        exchange = str(raw.get("Exchange") or "").strip().upper()
        items.append(
            {
                "symbol": symbol,
                "ibkr_symbol": ibkr_symbol(symbol),
                "source_symbol": source_symbol,
                "name": str(raw.get("Name") or "").strip(),
                "sector": str(raw.get("Sector") or "").strip(),
                "exchange": exchange,
                "ibkr_primary_exchange": expected_ibkr_primary_exchange(exchange),
                "currency": "USD",
            }
        )

    if not (950 <= len(items) <= 1100):
        raise R1000UniverseError(f"Validated R1000 universe size out of range: {len(items)}")
    return tuple(items)


def load_r1000_universe(path: Path | None = None) -> list[dict]:
    path = Path(path or UNIVERSE_FILE)
    try:
        stat = path.stat()
    except Exception as error:
        raise R1000UniverseError(f"R1000 universe file unavailable: {type(error).__name__}") from error
    return [dict(item) for item in _load_cached(str(path), stat.st_mtime_ns, stat.st_size)]


def search_r1000(query: str = "", *, limit: int = 50, path: Path | None = None) -> list[dict]:
    """Search current R1000 by ticker or company name; exact ticker wins."""
    limit = max(1, min(int(limit), 100))
    items = load_r1000_universe(path)
    text = str(query or "").strip().upper()
    if not text:
        return items[:limit]

    canonical_query = canonical_symbol(text)
    ranked = []
    for item in items:
        symbol = item["symbol"]
        name = item["name"].upper()
        if symbol == canonical_query:
            rank = 0
        elif symbol.startswith(canonical_query):
            rank = 1
        elif canonical_query in symbol:
            rank = 2
        elif name.startswith(text):
            rank = 3
        elif text in name:
            rank = 4
        else:
            continue
        ranked.append((rank, symbol, item))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [dict(row[2]) for row in ranked[:limit]]


def get_r1000_symbol(symbol: str, path: Path | None = None) -> dict | None:
    target = canonical_symbol(symbol)
    for item in load_r1000_universe(path):
        if item["symbol"] == target:
            return item
    return None

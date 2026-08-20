"""Canonical symbol mapping for TradingbotR1000.

Project code uses the canonical symbol for historical files, strategy signals,
state, reports, reconciliation, and order intents. IBKR-specific formatting is
applied only at the broker contract boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SYMBOL_ALIASES = {
    "BRKB": "BRK.B",
    "BFA": "BF.A",
    "BFB": "BF.B",
    "HEIA": "HEI.A",
    "LENB": "LEN.B",
    "UHALB": "UHAL.B",
}

IBKR_PRIMARY_EXCHANGE_ALIASES = {
    "CBOE BZX": "BATS",
    "NYSE MKT LLC": "AMEX",
    "NYSE AMERICAN": "AMEX",
    "NYSE ARCA": "ARCA",
    "NASDAQ": "NASDAQ",
    "NYSE": "NYSE",
}

IBKR_UNRESOLVED_EXCLUSIONS: dict[str, str] = {
    "HOLX": "ibkr_unresolved_no_market_universe_symbol",
    "NSA": "ibkr_value_only_no_smart_or_nyse_stock_contract",
    "EA": "ibkr_value_only_corporate_action",
    "AVB": "ibkr_value_only_corporate_action",
    "EQR": "ibkr_unresolved_corporate_action",
    "WBS": "ibkr_value_only_corporate_action",
}


@dataclass(frozen=True)
class SymbolIdentity:
    source_symbol: str
    canonical_symbol: str
    historical_symbol: str
    ibkr_symbol: str
    historical_file: str
    source_exchange: str = ""
    expected_ibkr_primary_exchange: str = ""
    exclusion_reason: str = ""


def canonical_symbol(symbol: object) -> str:
    value = str(symbol or "").strip().upper().replace('"', "").replace("'", "")
    value = value.replace("/", ".").replace(" ", ".").replace("-", ".")
    value = re.sub(r"[^A-Z0-9.]", "", value)
    value = re.sub(r"\.+", ".", value).strip(".")
    return SYMBOL_ALIASES.get(value, value)


def canonical_symbol_from_ibkr(symbol: object) -> str:
    return canonical_symbol(str(symbol or "").replace(" ", "."))


def historical_symbol(symbol: object) -> str:
    return canonical_symbol(symbol)


def ibkr_symbol(symbol: object) -> str:
    return canonical_symbol(symbol).replace(".", " ")


def historical_filename(symbol: object) -> str:
    return f"{historical_symbol(symbol)}.csv"


def expected_ibkr_primary_exchange(source_exchange: object) -> str:
    value = str(source_exchange or "").strip().upper()
    if not value or value.startswith("NO MARKET"):
        return ""
    return IBKR_PRIMARY_EXCHANGE_ALIASES.get(value, value)


def exclusion_reason(symbol: object) -> str:
    return IBKR_UNRESOLVED_EXCLUSIONS.get(canonical_symbol(symbol), "")


def is_excluded(symbol: object) -> bool:
    return bool(exclusion_reason(symbol))


def identity_for(
    source_symbol: object,
    *,
    source_exchange: object = "",
    daily_bars_dir: Path | None = None,
) -> SymbolIdentity:
    canonical = canonical_symbol(source_symbol)
    filename = historical_filename(canonical)
    historical_file = str((daily_bars_dir / filename) if daily_bars_dir else filename)
    return SymbolIdentity(
        source_symbol=str(source_symbol or "").strip(),
        canonical_symbol=canonical,
        historical_symbol=historical_symbol(canonical),
        ibkr_symbol=ibkr_symbol(canonical),
        historical_file=historical_file,
        source_exchange=str(source_exchange or "").strip(),
        expected_ibkr_primary_exchange=expected_ibkr_primary_exchange(source_exchange),
        exclusion_reason=exclusion_reason(canonical),
    )

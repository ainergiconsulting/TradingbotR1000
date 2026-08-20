"""Build and validate the TradingbotR1000 Security Master.

The Security Master is an offline Program A data-integrity component. It is not
used by the production runtime until a later shadow integration phase.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "security_master"
DEFAULT_DATABASE = DEFAULT_OUTPUT_DIR / "security_master.sqlite3"
DEFAULT_EXPORT = DEFAULT_OUTPUT_DIR / "security_master_export.csv"
DEFAULT_IDENTIFIERS_EXPORT = DEFAULT_OUTPUT_DIR / "security_master_identifiers.csv"
DEFAULT_ACTIONS_EXPORT = DEFAULT_OUTPUT_DIR / "security_master_corporate_actions.csv"
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "security_master_manifest.json"
DEFAULT_VALIDATION_REPORT = DEFAULT_OUTPUT_DIR / "security_master_validation_report.json"
DEFAULT_VALIDATION_CSV = DEFAULT_OUTPUT_DIR / "security_master_validation_checks.csv"

DEFAULT_IWB_FILE = PROJECT_ROOT / "IWB_holdings.csv"
DEFAULT_IBKR_COMPATIBILITY_CSV = PROJECT_ROOT / "ibkr_r1000_results" / "symbol_compatibility_validation.csv"
DEFAULT_IBKR_COMPATIBILITY_REPORT = PROJECT_ROOT / "ibkr_r1000_results" / "symbol_compatibility_validation_report.json"
DEFAULT_MASSIVE_DETAILS_CSV = PROJECT_ROOT / "data" / "source" / "massive" / "reference" / "ticker_details.csv"
DEFAULT_TICKER_EVENTS_CSV = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "ticker_events.csv"
DEFAULT_SPLITS_CSV = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "splits.csv"
DEFAULT_DIVIDENDS_CSV = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "dividends.csv"
DEFAULT_EVENT_CAPABILITIES_CSV = PROJECT_ROOT / "data" / "source" / "massive" / "corporate_actions" / "event_capabilities.csv"
DEFAULT_PHASE_A2_DIAGNOSTICS_CSV = (
    PROJECT_ROOT / "data" / "validation" / "historical_corporate_actions" / "phase_a2_finding_diagnostics.csv"
)
DEFAULT_PHASE_A2_SYMBOL_VALIDATION_CSV = (
    PROJECT_ROOT
    / "data"
    / "validation"
    / "historical_corporate_actions"
    / "historical_bars_corporate_action_validation.csv"
)
DEFAULT_DAILY_BARS_DIR = PROJECT_ROOT / "data" / "daily_bars"

SYMBOL_ALIASES = {
    "BRKB": "BRK.B",
    "BFA": "BF.A",
    "BFB": "BF.B",
    "HEIA": "HEI.A",
    "LENB": "LEN.B",
    "UHALB": "UHAL.B",
}

SHARE_CLASS_SYMBOLS = ["BRK.B", "BF.A", "BF.B", "HEI.A", "LEN.B", "UHAL.B"]
SHARE_CLASS_PAIR_SYMBOLS = ["HEI", "HEI.A"]
KNOWN_EXCLUSIONS = {"HOLX", "NSA"}
PHASE_A2_BLOCKING_SYMBOLS = {"HLT", "HEI.A", "DD", "HEI", "CGNX", "APLD"}

SECURITY_EXPORT_FIELDS = [
    "canonical_security_id",
    "canonical_symbol",
    "company_name",
    "iwb_symbol",
    "massive_symbol",
    "ibkr_con_id",
    "ibkr_symbol",
    "ibkr_local_symbol",
    "ibkr_primary_exchange",
    "currency",
    "sector",
    "current_status",
    "membership_status",
    "trading_status",
    "data_quality_status",
    "promotion_status",
    "exclusion_reason",
    "phase_a2_primary_cause",
    "massive_active",
    "massive_list_date",
    "massive_delisted_utc",
    "last_verified_at_utc",
]

IDENTIFIER_EXPORT_FIELDS = [
    "canonical_security_id",
    "canonical_symbol",
    "identifier_type",
    "identifier_value",
    "source",
    "valid_from",
    "valid_to",
    "is_primary",
]

ACTION_EXPORT_FIELDS = [
    "canonical_security_id",
    "canonical_symbol",
    "event_type",
    "event_date",
    "source",
    "source_symbol",
    "target_symbol",
    "details_json",
]


@dataclass(frozen=True)
class SecurityMasterPaths:
    iwb_file: Path = DEFAULT_IWB_FILE
    ibkr_compatibility_csv: Path = DEFAULT_IBKR_COMPATIBILITY_CSV
    ibkr_compatibility_report: Path = DEFAULT_IBKR_COMPATIBILITY_REPORT
    massive_details_csv: Path = DEFAULT_MASSIVE_DETAILS_CSV
    ticker_events_csv: Path = DEFAULT_TICKER_EVENTS_CSV
    splits_csv: Path = DEFAULT_SPLITS_CSV
    dividends_csv: Path = DEFAULT_DIVIDENDS_CSV
    event_capabilities_csv: Path = DEFAULT_EVENT_CAPABILITIES_CSV
    phase_a2_diagnostics_csv: Path = DEFAULT_PHASE_A2_DIAGNOSTICS_CSV
    phase_a2_symbol_validation_csv: Path = DEFAULT_PHASE_A2_SYMBOL_VALIDATION_CSV
    daily_bars_dir: Path = DEFAULT_DAILY_BARS_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    database: Path = DEFAULT_DATABASE
    security_export: Path = DEFAULT_EXPORT
    identifiers_export: Path = DEFAULT_IDENTIFIERS_EXPORT
    actions_export: Path = DEFAULT_ACTIONS_EXPORT
    manifest: Path = DEFAULT_MANIFEST
    validation_report: Path = DEFAULT_VALIDATION_REPORT
    validation_csv: Path = DEFAULT_VALIDATION_CSV


@dataclass(frozen=True)
class BuildResult:
    database: Path
    security_export: Path
    identifiers_export: Path
    actions_export: Path
    manifest: Path
    securities: int
    tradable: int
    excluded: int
    blocked: int
    review_required: int


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_symbol(symbol: object) -> str:
    value = str(symbol or "").strip().upper().replace('"', "").replace("'", "")
    value = value.replace("/", ".").replace(" ", ".").replace("-", ".")
    value = re.sub(r"[^A-Z0-9.]", "", value)
    value = re.sub(r"\.+", ".", value).strip(".")
    return SYMBOL_ALIASES.get(value, value)


def ibkr_symbol(symbol: object) -> str:
    return canonical_symbol(symbol).replace(".", " ")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}


def write_csv_atomic(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_iwb_holdings(path: Path) -> tuple[str, list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"IWB holdings file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    as_of_date = ""
    header_index = None
    for index, row in enumerate(rows):
        cleaned = [cell.strip() for cell in row]
        if cleaned and cleaned[0] == "Fund Holdings as of" and len(cleaned) > 1:
            as_of_date = normalize_iwb_as_of_date(cleaned[1])
        if "Ticker" in cleaned and "Name" in cleaned:
            header_index = index
            break
    if header_index is None:
        raise ValueError("IWB holdings header row was not found")

    fieldnames = [field.strip() for field in rows[header_index]]
    holdings: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows[header_index + 1 :]:
        if not raw or not any(cell.strip() for cell in raw):
            continue
        row = {fieldnames[index]: raw[index].strip() if index < len(raw) else "" for index in range(len(fieldnames))}
        source_symbol = row.get("Ticker", "").strip()
        normalized = canonical_symbol(source_symbol)
        asset_class = row.get("Asset Class", "").strip().lower()
        currency = row.get("Currency", "").strip().upper()
        market_currency = row.get("Market Currency", "").strip().upper()
        if asset_class and asset_class != "equity":
            continue
        if currency and currency != "USD":
            continue
        if market_currency and market_currency != "USD":
            continue
        if not normalized or not re.match(r"^[A-Z0-9]+(?:\.[A-Z0-9]+)?$", normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        row["source_symbol"] = source_symbol
        row["canonical_symbol"] = normalized
        holdings.append(row)
    if not holdings:
        raise ValueError("IWB holdings file contains no valid equity rows")
    return as_of_date, holdings


def normalize_iwb_as_of_date(value: str) -> str:
    text = value.strip().strip('"')
    if not text:
        return ""
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def parse_decimal(value: str) -> str:
    text = str(value or "").strip().replace(",", "")
    if not text or text == "-":
        return ""
    try:
        return str(float(text))
    except ValueError:
        return ""


def rows_by_symbol(rows: list[dict[str, str]], field: str = "canonical_symbol") -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        symbol = canonical_symbol(row.get(field, ""))
        if symbol:
            result[symbol] = row
    return result


def grouped_rows_by_symbol(rows: list[dict[str, str]], field: str = "canonical_symbol") -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        symbol = canonical_symbol(row.get(field, ""))
        if symbol:
            result.setdefault(symbol, []).append(row)
    return result


def load_existing_ids(database: Path) -> dict[str, str]:
    if not database.exists():
        return {}
    conn = None
    try:
        conn = sqlite3.connect(database)
        rows = conn.execute("SELECT canonical_symbol, canonical_security_id FROM securities").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        if conn is not None:
            conn.close()
    return {str(symbol): str(security_id) for symbol, security_id in rows}


def next_security_id(existing_ids: dict[str, str]) -> int:
    highest = 0
    for security_id in existing_ids.values():
        match = re.match(r"^R1000-SEC-(\d{6})$", security_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def assign_security_ids(holdings: list[dict[str, str]], existing_ids: dict[str, str]) -> dict[str, str]:
    assigned = dict(existing_ids)
    next_id = next_security_id(existing_ids)
    for row in holdings:
        symbol = row["canonical_symbol"]
        if symbol not in assigned:
            assigned[symbol] = f"R1000-SEC-{next_id:06d}"
            next_id += 1
    return {row["canonical_symbol"]: assigned[row["canonical_symbol"]] for row in holdings}


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE securities (
            canonical_security_id TEXT PRIMARY KEY,
            canonical_symbol TEXT NOT NULL UNIQUE,
            company_name TEXT NOT NULL,
            security_type TEXT NOT NULL,
            current_status TEXT NOT NULL,
            membership_status TEXT NOT NULL,
            trading_status TEXT NOT NULL,
            data_quality_status TEXT NOT NULL,
            promotion_status TEXT NOT NULL,
            exclusion_reason TEXT,
            phase_a2_primary_cause TEXT,
            sector TEXT,
            currency TEXT,
            iwb_exchange TEXT,
            massive_active INTEGER,
            massive_list_date TEXT,
            massive_delisted_utc TEXT,
            created_at_utc TEXT NOT NULL,
            last_verified_at_utc TEXT NOT NULL
        );

        CREATE TABLE identifier_type_definitions (
            identifier_type TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            currently_populated INTEGER NOT NULL
        );

        CREATE TABLE identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_security_id TEXT NOT NULL REFERENCES securities(canonical_security_id),
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            source TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            is_primary INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE universe_memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_security_id TEXT NOT NULL REFERENCES securities(canonical_security_id),
            universe TEXT NOT NULL,
            as_of_date TEXT,
            source_symbol TEXT NOT NULL,
            source_name TEXT,
            sector TEXT,
            asset_class TEXT,
            exchange_name TEXT,
            currency TEXT,
            weight_pct REAL,
            market_value REAL,
            raw_json TEXT NOT NULL,
            source_file TEXT NOT NULL
        );

        CREATE TABLE ibkr_contracts (
            canonical_security_id TEXT PRIMARY KEY REFERENCES securities(canonical_security_id),
            ibkr_con_id TEXT,
            ibkr_symbol TEXT,
            ibkr_local_symbol TEXT,
            ibkr_trading_class TEXT,
            ibkr_sec_type TEXT,
            ibkr_exchange TEXT,
            ibkr_primary_exchange TEXT,
            ibkr_currency TEXT,
            ibkr_status TEXT NOT NULL,
            ibkr_reason TEXT,
            validated_at_utc TEXT
        );

        CREATE TABLE corporate_event_type_definitions (
            event_type TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            support_status TEXT NOT NULL,
            notes TEXT NOT NULL
        );

        CREATE TABLE corporate_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_security_id TEXT NOT NULL REFERENCES securities(canonical_security_id),
            event_type TEXT NOT NULL,
            event_date TEXT,
            source TEXT NOT NULL,
            source_symbol TEXT,
            target_symbol TEXT,
            details_json TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );

        CREATE TABLE validation_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_security_id TEXT NOT NULL REFERENCES securities(canonical_security_id),
            finding_source TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            primary_cause TEXT,
            cause_categories TEXT,
            safe_for_corrected_dataset_promotion TEXT,
            recommended_resolution TEXT,
            details TEXT
        );

        CREATE TABLE build_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE UNIQUE INDEX idx_identifiers_unique
            ON identifiers(canonical_security_id, identifier_type, identifier_value, source);
        CREATE INDEX idx_identifiers_lookup
            ON identifiers(identifier_type, identifier_value);
        CREATE INDEX idx_corporate_actions_security_date
            ON corporate_actions(canonical_security_id, event_date);
        """
    )


def insert_identifier_definitions(conn: sqlite3.Connection) -> None:
    rows = [
        ("canonical_symbol", "Project normalized symbol attribute, not the primary key.", 1),
        ("iwb_symbol", "Symbol as supplied by IWB holdings.", 1),
        ("massive_symbol", "Symbol accepted by Massive/Polygon historical/reference data.", 1),
        ("historical_file", "Local historical-bar filename.", 1),
        ("ibkr_con_id", "IBKR contract identifier.", 1),
        ("ibkr_symbol", "IBKR stock contract symbol.", 1),
        ("ibkr_local_symbol", "IBKR localSymbol.", 1),
        ("ibkr_trading_class", "IBKR tradingClass.", 1),
        ("composite_figi", "Massive/Polygon composite FIGI when available.", 1),
        ("share_class_figi", "Massive/Polygon share-class FIGI when available.", 1),
        ("cik", "SEC CIK when available.", 1),
        ("cusip", "CUSIP placeholder for future source integration.", 0),
        ("isin", "ISIN placeholder for future source integration.", 0),
        ("sedol", "SEDOL placeholder for future source integration.", 0),
    ]
    conn.executemany(
        "INSERT INTO identifier_type_definitions(identifier_type, description, currently_populated) VALUES (?, ?, ?)",
        rows,
    )


def insert_event_definitions(conn: sqlite3.Connection, event_capability_rows: list[dict[str, str]]) -> None:
    default_events = {
        "forward_split": ("Massive splits", "yes", "Derived from split_to > split_from."),
        "reverse_split": ("Massive splits", "yes", "Derived from split_to < split_from."),
        "cash_dividend": ("Massive dividends", "yes", "Cash dividend events when supplied."),
        "stock_dividend": ("future source or manual curation", "schema_only", "Supported by schema; not reliably populated yet."),
        "ticker_change": ("Massive ticker events", "best_effort", "Ticker-event evidence when supplied."),
        "merger": ("future source or manual curation", "schema_only", "Supported by schema; not inferred."),
        "acquisition": ("future source or manual curation", "schema_only", "Supported by schema; not inferred."),
        "spin_off": ("future source or manual curation", "schema_only", "Supported by schema; not inferred."),
        "delisting": ("Massive ticker details or future source", "best_effort", "Stored when delisting metadata is available."),
    }
    for row in event_capability_rows:
        event_type = row.get("event_class", "").strip()
        if event_type:
            default_events[event_type] = (
                row.get("source", ""),
                row.get("initial_support", ""),
                row.get("notes", ""),
            )
    conn.executemany(
        """
        INSERT INTO corporate_event_type_definitions(event_type, source, support_status, notes)
        VALUES (?, ?, ?, ?)
        """,
        [(event_type, source, support, notes) for event_type, (source, support, notes) in sorted(default_events.items())],
    )


def insert_identifier(
    conn: sqlite3.Connection,
    security_id: str,
    identifier_type: str,
    identifier_value: Any,
    source: str,
    *,
    valid_from: str = "",
    valid_to: str = "",
    is_primary: bool = False,
    metadata: dict[str, Any] | None = None,
) -> None:
    value = str(identifier_value or "").strip()
    if not value:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO identifiers(
            canonical_security_id, identifier_type, identifier_value, source,
            valid_from, valid_to, is_primary, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (security_id, identifier_type, value, source, valid_from, valid_to, 1 if is_primary else 0, json.dumps(metadata or {}, sort_keys=True)),
    )


def table_export(conn: sqlite3.Connection, path: Path, query: str, fieldnames: list[str]) -> None:
    rows = [dict(zip(fieldnames, row)) for row in conn.execute(query).fetchall()]
    write_csv_atomic(path, fieldnames, rows)


def determine_status(
    symbol: str,
    massive_row: dict[str, str],
    diagnostic_row: dict[str, str],
    compatibility_row: dict[str, str],
) -> tuple[str, str, str, str, str, str]:
    compatibility_status = compatibility_row.get("status", "")
    diagnostic_status = diagnostic_row.get("validation_status") or diagnostic_row.get("status") or "passed"
    primary_cause = diagnostic_row.get("primary_cause", "")
    exclusion_reason = compatibility_row.get("reason", "")

    if symbol in KNOWN_EXCLUSIONS or compatibility_status == "excluded":
        return ("excluded", "current_iwb", "excluded", "excluded", "excluded", exclusion_reason)
    if str(massive_row.get("active", "")).lower() == "false" or massive_row.get("delisted_utc", ""):
        current_status = "delisted"
    else:
        current_status = "active"

    if diagnostic_status == "failed":
        return (current_status, "current_iwb", "tradable", "failed", "blocked", exclusion_reason)
    if diagnostic_status == "review_required":
        return (current_status, "current_iwb", "tradable", "review_required", "review", exclusion_reason)
    return (current_status, "current_iwb", "tradable", diagnostic_status or "passed", "approved", exclusion_reason)


def build_security_master(paths: SecurityMasterPaths) -> BuildResult:
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    now = utc_now_text()

    as_of_date, holdings = parse_iwb_holdings(paths.iwb_file)
    existing_ids = load_existing_ids(paths.database)
    security_ids = assign_security_ids(holdings, existing_ids)

    compatibility_by_symbol = rows_by_symbol(read_csv_rows(paths.ibkr_compatibility_csv))
    massive_by_symbol = rows_by_symbol(read_csv_rows(paths.massive_details_csv))
    diagnostic_by_symbol = rows_by_symbol(read_csv_rows(paths.phase_a2_diagnostics_csv), "symbol")
    phase_a2_symbol_validation_by_symbol = rows_by_symbol(read_csv_rows(paths.phase_a2_symbol_validation_csv), "symbol")
    ticker_events_by_symbol = grouped_rows_by_symbol(read_csv_rows(paths.ticker_events_csv))
    splits_by_symbol = grouped_rows_by_symbol(read_csv_rows(paths.splits_csv))
    dividends_by_symbol = grouped_rows_by_symbol(read_csv_rows(paths.dividends_csv))
    event_capability_rows = read_csv_rows(paths.event_capabilities_csv)

    temp_db = paths.database.with_name(f"{paths.database.name}.tmp")
    if temp_db.exists():
        temp_db.unlink()

    conn = sqlite3.connect(temp_db)
    try:
        create_schema(conn)
        insert_identifier_definitions(conn)
        insert_event_definitions(conn, event_capability_rows)

        security_export_rows: list[dict[str, Any]] = []
        for holding in holdings:
            symbol = holding["canonical_symbol"]
            security_id = security_ids[symbol]
            massive_row = massive_by_symbol.get(symbol, {})
            compatibility_row = compatibility_by_symbol.get(symbol, {})
            diagnostic_row = diagnostic_by_symbol.get(symbol, {})
            phase_validation_row = phase_a2_symbol_validation_by_symbol.get(symbol, {})
            if not diagnostic_row and phase_validation_row:
                diagnostic_row = {
                    "validation_status": phase_validation_row.get("status", ""),
                    "primary_cause": phase_validation_row.get("reason", ""),
                    "safe_for_corrected_dataset_promotion": "approved",
                    "recommended_resolution": "",
                    "details": "",
                    "cause_categories": "",
                }

            current_status, membership_status, trading_status, data_quality_status, promotion_status, exclusion_reason = determine_status(
                symbol, massive_row, diagnostic_row, compatibility_row
            )
            company_name = holding.get("Name") or massive_row.get("name") or symbol
            currency = holding.get("Currency") or holding.get("Market Currency") or compatibility_row.get("ibkr_currency") or massive_row.get("currency_name", "").upper()
            massive_active = 1 if str(massive_row.get("active", "")).lower() == "true" else 0

            conn.execute(
                """
                INSERT INTO securities(
                    canonical_security_id, canonical_symbol, company_name, security_type,
                    current_status, membership_status, trading_status, data_quality_status,
                    promotion_status, exclusion_reason, phase_a2_primary_cause, sector,
                    currency, iwb_exchange, massive_active, massive_list_date,
                    massive_delisted_utc, created_at_utc, last_verified_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    security_id,
                    symbol,
                    company_name,
                    "stock",
                    current_status,
                    membership_status,
                    trading_status,
                    data_quality_status,
                    promotion_status,
                    exclusion_reason,
                    diagnostic_row.get("primary_cause", ""),
                    holding.get("Sector", ""),
                    currency,
                    holding.get("Exchange", ""),
                    massive_active,
                    massive_row.get("list_date", ""),
                    massive_row.get("delisted_utc", ""),
                    now,
                    now,
                ),
            )

            weight = parse_decimal(holding.get("Weight (%)", ""))
            market_value = parse_decimal(holding.get("Market Value", ""))
            conn.execute(
                """
                INSERT INTO universe_memberships(
                    canonical_security_id, universe, as_of_date, source_symbol, source_name,
                    sector, asset_class, exchange_name, currency, weight_pct, market_value,
                    raw_json, source_file
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    security_id,
                    "IWB",
                    as_of_date,
                    holding.get("source_symbol", ""),
                    holding.get("Name", ""),
                    holding.get("Sector", ""),
                    holding.get("Asset Class", ""),
                    holding.get("Exchange", ""),
                    currency,
                    float(weight) if weight else None,
                    float(market_value) if market_value else None,
                    json.dumps(holding, sort_keys=True),
                    str(paths.iwb_file),
                ),
            )

            insert_security_identifiers(conn, security_id, symbol, holding, massive_row, compatibility_row, paths.daily_bars_dir)
            insert_ibkr_contract(conn, security_id, compatibility_row)
            insert_validation_finding(conn, security_id, diagnostic_row, phase_validation_row)
            insert_corporate_actions(
                conn,
                security_id,
                symbol,
                ticker_events_by_symbol.get(symbol, []),
                splits_by_symbol.get(symbol, []),
                dividends_by_symbol.get(symbol, []),
                massive_row,
            )

            security_export_rows.append(
                {
                    "canonical_security_id": security_id,
                    "canonical_symbol": symbol,
                    "company_name": company_name,
                    "iwb_symbol": holding.get("source_symbol", ""),
                    "massive_symbol": massive_row.get("massive_ticker", ""),
                    "ibkr_con_id": compatibility_row.get("ibkr_con_id", ""),
                    "ibkr_symbol": compatibility_row.get("ibkr_symbol", ""),
                    "ibkr_local_symbol": compatibility_row.get("ibkr_local_symbol", ""),
                    "ibkr_primary_exchange": compatibility_row.get("ibkr_primary_exchange", ""),
                    "currency": currency,
                    "sector": holding.get("Sector", ""),
                    "current_status": current_status,
                    "membership_status": membership_status,
                    "trading_status": trading_status,
                    "data_quality_status": data_quality_status,
                    "promotion_status": promotion_status,
                    "exclusion_reason": exclusion_reason,
                    "phase_a2_primary_cause": diagnostic_row.get("primary_cause", ""),
                    "massive_active": massive_active,
                    "massive_list_date": massive_row.get("list_date", ""),
                    "massive_delisted_utc": massive_row.get("delisted_utc", ""),
                    "last_verified_at_utc": now,
                }
            )

        metadata = build_metadata_payload(paths, now, holdings)
        conn.executemany(
            "INSERT INTO build_metadata(key, value) VALUES (?, ?)",
            [(key, json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)) for key, value in metadata.items()],
        )
        conn.commit()
    finally:
        conn.close()

    temp_db.replace(paths.database)
    write_csv_atomic(paths.security_export, SECURITY_EXPORT_FIELDS, security_export_rows)
    export_identifiers(paths)
    export_actions(paths)
    manifest = build_manifest(paths, security_export_rows, metadata, as_of_date)
    write_json_atomic(paths.manifest, manifest)

    return BuildResult(
        database=paths.database,
        security_export=paths.security_export,
        identifiers_export=paths.identifiers_export,
        actions_export=paths.actions_export,
        manifest=paths.manifest,
        securities=len(security_export_rows),
        tradable=sum(1 for row in security_export_rows if row["trading_status"] == "tradable"),
        excluded=sum(1 for row in security_export_rows if row["trading_status"] == "excluded"),
        blocked=sum(1 for row in security_export_rows if row["promotion_status"] == "blocked"),
        review_required=sum(1 for row in security_export_rows if row["promotion_status"] == "review"),
    )


def insert_security_identifiers(
    conn: sqlite3.Connection,
    security_id: str,
    symbol: str,
    holding: dict[str, str],
    massive_row: dict[str, str],
    compatibility_row: dict[str, str],
    daily_bars_dir: Path,
) -> None:
    insert_identifier(conn, security_id, "canonical_symbol", symbol, "TradingbotR1000", is_primary=False)
    insert_identifier(conn, security_id, "iwb_symbol", holding.get("source_symbol", ""), "IWB", is_primary=True)
    insert_identifier(conn, security_id, "historical_file", str(daily_bars_dir / f"{symbol}.csv"), "local_historical_database")
    insert_identifier(conn, security_id, "massive_symbol", massive_row.get("massive_ticker", "") or symbol, "Massive")
    insert_identifier(conn, security_id, "composite_figi", massive_row.get("composite_figi", ""), "Massive")
    insert_identifier(conn, security_id, "share_class_figi", massive_row.get("share_class_figi", ""), "Massive")
    insert_identifier(conn, security_id, "cik", massive_row.get("cik", ""), "Massive")
    insert_identifier(conn, security_id, "ibkr_con_id", compatibility_row.get("ibkr_con_id", ""), "IBKR", is_primary=True)
    insert_identifier(conn, security_id, "ibkr_symbol", compatibility_row.get("ibkr_symbol", "") or ibkr_symbol(symbol), "IBKR")
    insert_identifier(conn, security_id, "ibkr_local_symbol", compatibility_row.get("ibkr_local_symbol", ""), "IBKR")
    insert_identifier(conn, security_id, "ibkr_trading_class", compatibility_row.get("ibkr_trading_class", ""), "IBKR")


def insert_ibkr_contract(conn: sqlite3.Connection, security_id: str, compatibility_row: dict[str, str]) -> None:
    conn.execute(
        """
        INSERT INTO ibkr_contracts(
            canonical_security_id, ibkr_con_id, ibkr_symbol, ibkr_local_symbol,
            ibkr_trading_class, ibkr_sec_type, ibkr_exchange, ibkr_primary_exchange,
            ibkr_currency, ibkr_status, ibkr_reason, validated_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            security_id,
            compatibility_row.get("ibkr_con_id", ""),
            compatibility_row.get("ibkr_symbol", ""),
            compatibility_row.get("ibkr_local_symbol", ""),
            compatibility_row.get("ibkr_trading_class", ""),
            compatibility_row.get("ibkr_sec_type", ""),
            compatibility_row.get("ibkr_exchange", ""),
            compatibility_row.get("ibkr_primary_exchange", ""),
            compatibility_row.get("ibkr_currency", ""),
            compatibility_row.get("status", "missing_compatibility_evidence"),
            compatibility_row.get("reason", ""),
            compatibility_row.get("validated_at_utc", ""),
        ),
    )


def insert_validation_finding(
    conn: sqlite3.Connection,
    security_id: str,
    diagnostic_row: dict[str, str],
    phase_validation_row: dict[str, str],
) -> None:
    if diagnostic_row:
        conn.execute(
            """
            INSERT INTO validation_findings(
                canonical_security_id, finding_source, validation_status, primary_cause,
                cause_categories, safe_for_corrected_dataset_promotion,
                recommended_resolution, details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                security_id,
                "phase_a2_finding_diagnostics",
                diagnostic_row.get("validation_status", ""),
                diagnostic_row.get("primary_cause", ""),
                diagnostic_row.get("cause_categories", ""),
                diagnostic_row.get("safe_for_corrected_dataset_promotion", ""),
                diagnostic_row.get("recommended_resolution", ""),
                diagnostic_row.get("details", ""),
            ),
        )
    elif phase_validation_row:
        conn.execute(
            """
            INSERT INTO validation_findings(
                canonical_security_id, finding_source, validation_status, primary_cause,
                cause_categories, safe_for_corrected_dataset_promotion,
                recommended_resolution, details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                security_id,
                "phase_a2_symbol_validation",
                phase_validation_row.get("status", ""),
                phase_validation_row.get("reason", ""),
                "",
                "approved" if phase_validation_row.get("status") == "passed" else "review",
                "",
                "",
            ),
        )


def insert_corporate_actions(
    conn: sqlite3.Connection,
    security_id: str,
    symbol: str,
    ticker_events: list[dict[str, str]],
    splits: list[dict[str, str]],
    dividends: list[dict[str, str]],
    massive_row: dict[str, str],
) -> None:
    for row in ticker_events:
        raw_payload = parse_raw_json(row)
        target_symbol = ""
        if isinstance(raw_payload.get("ticker_change"), dict):
            target_symbol = str(raw_payload["ticker_change"].get("ticker", "")).strip()
        insert_corporate_action(
            conn,
            security_id,
            "ticker_change",
            row.get("event_date", ""),
            "Massive ticker events",
            row.get("source_symbol", "") or symbol,
            target_symbol,
            row,
        )
    for row in splits:
        insert_corporate_action(
            conn,
            security_id,
            row.get("event_class", "") or "split",
            row.get("execution_date", ""),
            "Massive splits",
            row.get("source_symbol", "") or symbol,
            "",
            row,
        )
    for row in dividends:
        insert_corporate_action(
            conn,
            security_id,
            row.get("event_class", "") or "cash_dividend",
            row.get("ex_dividend_date", ""),
            "Massive dividends",
            row.get("source_symbol", "") or symbol,
            "",
            row,
        )
    if massive_row.get("delisted_utc", ""):
        insert_corporate_action(
            conn,
            security_id,
            "delisting",
            massive_row.get("delisted_utc", "")[:10],
            "Massive ticker details",
            symbol,
            "",
            massive_row,
        )


def parse_raw_json(row: dict[str, str]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("raw_json", "") or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def insert_corporate_action(
    conn: sqlite3.Connection,
    security_id: str,
    event_type: str,
    event_date: str,
    source: str,
    source_symbol: str,
    target_symbol: str,
    row: dict[str, str],
) -> None:
    raw_json = row.get("raw_json", "")
    details = {key: value for key, value in row.items() if key != "raw_json"}
    conn.execute(
        """
        INSERT INTO corporate_actions(
            canonical_security_id, event_type, event_date, source,
            source_symbol, target_symbol, details_json, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (security_id, event_type, event_date, source, source_symbol, target_symbol, json.dumps(details, sort_keys=True), raw_json),
    )


def build_metadata_payload(paths: SecurityMasterPaths, created_at_utc: str, holdings: list[dict[str, str]]) -> dict[str, Any]:
    inputs = {
        "iwb_file": str(paths.iwb_file),
        "ibkr_compatibility_csv": str(paths.ibkr_compatibility_csv),
        "massive_details_csv": str(paths.massive_details_csv),
        "ticker_events_csv": str(paths.ticker_events_csv),
        "splits_csv": str(paths.splits_csv),
        "dividends_csv": str(paths.dividends_csv),
        "phase_a2_diagnostics_csv": str(paths.phase_a2_diagnostics_csv),
        "phase_a2_symbol_validation_csv": str(paths.phase_a2_symbol_validation_csv),
    }
    return {
        "builder_version": "1",
        "created_at_utc": created_at_utc,
        "universe_symbols": len(holdings),
        "input_files": inputs,
        "input_hashes": {name: file_sha256(Path(path)) for name, path in inputs.items()},
        "production_runtime_changed": False,
        "corrected_dataset_written": False,
    }


def build_manifest(
    paths: SecurityMasterPaths,
    security_export_rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    as_of_date: str,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    promotion_counts: dict[str, int] = {}
    for row in security_export_rows:
        status_counts[row["current_status"]] = status_counts.get(row["current_status"], 0) + 1
        promotion_counts[row["promotion_status"]] = promotion_counts.get(row["promotion_status"], 0) + 1
    return {
        **metadata,
        "iwb_as_of_date": as_of_date,
        "outputs": {
            "database": str(paths.database),
            "security_export": str(paths.security_export),
            "identifiers_export": str(paths.identifiers_export),
            "actions_export": str(paths.actions_export),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "promotion_counts": dict(sorted(promotion_counts.items())),
        "known_exclusions": sorted(KNOWN_EXCLUSIONS),
        "phase_a2_blocking_symbols": sorted(PHASE_A2_BLOCKING_SYMBOLS),
    }


def export_identifiers(paths: SecurityMasterPaths) -> None:
    conn = sqlite3.connect(paths.database)
    try:
        query = """
            SELECT i.canonical_security_id, s.canonical_symbol, i.identifier_type,
                   i.identifier_value, i.source, i.valid_from, i.valid_to, i.is_primary
            FROM identifiers i
            JOIN securities s USING(canonical_security_id)
            ORDER BY s.canonical_symbol, i.identifier_type, i.identifier_value
        """
        table_export(conn, paths.identifiers_export, query, IDENTIFIER_EXPORT_FIELDS)
    finally:
        conn.close()


def export_actions(paths: SecurityMasterPaths) -> None:
    conn = sqlite3.connect(paths.database)
    try:
        query = """
            SELECT ca.canonical_security_id, s.canonical_symbol, ca.event_type,
                   ca.event_date, ca.source, ca.source_symbol, ca.target_symbol,
                   ca.details_json
            FROM corporate_actions ca
            JOIN securities s USING(canonical_security_id)
            ORDER BY s.canonical_symbol, ca.event_date, ca.event_type
        """
        table_export(conn, paths.actions_export, query, ACTION_EXPORT_FIELDS)
    finally:
        conn.close()


def validate_security_master(paths: SecurityMasterPaths) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool, details: str = "", severity: str = "error") -> None:
        checks.append({"check": name, "passed": bool(passed), "severity": severity, "details": details})

    if not paths.database.exists():
        add_check("database_exists", False, str(paths.database))
        return finalize_validation(paths, checks, {})

    conn = sqlite3.connect(paths.database)
    try:
        conn.row_factory = sqlite3.Row
        expected_tables = {
            "securities",
            "identifiers",
            "identifier_type_definitions",
            "universe_memberships",
            "ibkr_contracts",
            "corporate_actions",
            "corporate_event_type_definitions",
            "validation_findings",
            "build_metadata",
        }
        actual_tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        add_check("required_tables_exist", expected_tables.issubset(actual_tables), f"missing={sorted(expected_tables - actual_tables)}")

        expected_universe_count = metadata_int(conn, "universe_symbols")
        security_count = scalar_int(conn, "SELECT COUNT(*) FROM securities")
        membership_count = scalar_int(conn, "SELECT COUNT(*) FROM universe_memberships WHERE universe='IWB'")
        unique_ids = scalar_int(conn, "SELECT COUNT(DISTINCT canonical_security_id) FROM securities")
        unique_symbols = scalar_int(conn, "SELECT COUNT(DISTINCT canonical_symbol) FROM securities")
        add_check(
            "current_iwb_symbols_resolve_once",
            security_count == expected_universe_count and membership_count == expected_universe_count,
            f"expected={expected_universe_count}; securities={security_count}; memberships={membership_count}",
        )
        add_check("canonical_security_ids_unique", unique_ids == security_count, f"unique_ids={unique_ids}; securities={security_count}")
        add_check("canonical_symbols_unique", unique_symbols == security_count, f"unique_symbols={unique_symbols}; securities={security_count}")

        pk_columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(securities)").fetchall()
            if row["pk"]
        ]
        add_check("security_primary_key_is_internal_id", pk_columns == ["canonical_security_id"], f"pk_columns={pk_columns}")

        tradable_with_conid = scalar_int(
            conn,
            """
            SELECT COUNT(*)
            FROM securities s
            JOIN ibkr_contracts i USING(canonical_security_id)
            WHERE s.trading_status='tradable'
              AND i.ibkr_status='ok'
              AND COALESCE(i.ibkr_con_id, '') <> ''
            """,
        )
        tradable_count = scalar_int(conn, "SELECT COUNT(*) FROM securities WHERE trading_status='tradable'")
        excluded_count = scalar_int(conn, "SELECT COUNT(*) FROM securities WHERE trading_status='excluded'")
        add_check("tradable_symbols_have_verified_ibkr_contracts", tradable_with_conid == tradable_count, f"tradable={tradable_count}; with_conid={tradable_with_conid}")
        add_check("known_exclusions_preserved", excluded_count == 2 and symbols_have_status(conn, KNOWN_EXCLUSIONS, "excluded"), f"excluded_count={excluded_count}")

        add_check(
            "phase_a2_blockers_preserved",
            symbols_have_promotion_status(conn, PHASE_A2_BLOCKING_SYMBOLS, "blocked"),
            ",".join(sorted(PHASE_A2_BLOCKING_SYMBOLS)),
        )
        add_check(
            "share_class_mappings_present",
            symbols_exist(conn, SHARE_CLASS_SYMBOLS),
            ",".join(SHARE_CLASS_SYMBOLS),
        )
        add_check(
            "hei_share_classes_are_distinct",
            distinct_security_ids(conn, SHARE_CLASS_PAIR_SYMBOLS) and distinct_ibkr_con_ids(conn, SHARE_CLASS_PAIR_SYMBOLS),
            ",".join(SHARE_CLASS_PAIR_SYMBOLS),
        )
        add_check(
            "supported_corporate_event_types_registered",
            event_types_registered(conn, {"ticker_change", "merger", "acquisition", "spin_off", "delisting", "forward_split", "reverse_split", "cash_dividend", "stock_dividend"}),
            "",
        )

        duplicate_critical = critical_identifier_duplicates(conn)
        add_check("critical_external_identifiers_not_ambiguous", not duplicate_critical, json.dumps(duplicate_critical, sort_keys=True))

        summary = {
            "security_count": security_count,
            "tradable_count": tradable_count,
            "excluded_count": excluded_count,
            "blocked_promotion_count": scalar_int(conn, "SELECT COUNT(*) FROM securities WHERE promotion_status='blocked'"),
            "review_promotion_count": scalar_int(conn, "SELECT COUNT(*) FROM securities WHERE promotion_status='review'"),
            "identifier_count": scalar_int(conn, "SELECT COUNT(*) FROM identifiers"),
            "corporate_action_count": scalar_int(conn, "SELECT COUNT(*) FROM corporate_actions"),
        }
    finally:
        conn.close()

    return finalize_validation(paths, checks, summary)


def scalar_int(conn: sqlite3.Connection, query: str) -> int:
    return int(conn.execute(query).fetchone()[0])


def metadata_int(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT value FROM build_metadata WHERE key=?", (key,)).fetchone()
    if row is None:
        return 0
    try:
        return int(str(row[0]).strip('"'))
    except ValueError:
        return 0


def symbols_exist(conn: sqlite3.Connection, symbols: Iterable[str]) -> bool:
    found = {
        row[0]
        for row in conn.execute(
            "SELECT canonical_symbol FROM securities WHERE canonical_symbol IN ({})".format(",".join("?" for _ in symbols)),
            tuple(symbols),
        ).fetchall()
    }
    return set(symbols).issubset(found)


def symbols_have_status(conn: sqlite3.Connection, symbols: set[str], status: str) -> bool:
    rows = conn.execute(
        "SELECT canonical_symbol, trading_status FROM securities WHERE canonical_symbol IN ({})".format(",".join("?" for _ in symbols)),
        tuple(sorted(symbols)),
    ).fetchall()
    return {row[0]: row[1] for row in rows} == {symbol: status for symbol in symbols}


def symbols_have_promotion_status(conn: sqlite3.Connection, symbols: set[str], status: str) -> bool:
    rows = conn.execute(
        "SELECT canonical_symbol, promotion_status FROM securities WHERE canonical_symbol IN ({})".format(",".join("?" for _ in symbols)),
        tuple(sorted(symbols)),
    ).fetchall()
    return {row[0]: row[1] for row in rows} == {symbol: status for symbol in symbols}


def distinct_security_ids(conn: sqlite3.Connection, symbols: list[str]) -> bool:
    rows = conn.execute(
        "SELECT canonical_security_id FROM securities WHERE canonical_symbol IN ({})".format(",".join("?" for _ in symbols)),
        tuple(symbols),
    ).fetchall()
    return len(rows) == len(symbols) and len({row[0] for row in rows}) == len(symbols)


def distinct_ibkr_con_ids(conn: sqlite3.Connection, symbols: list[str]) -> bool:
    rows = conn.execute(
        """
        SELECT i.ibkr_con_id
        FROM securities s JOIN ibkr_contracts i USING(canonical_security_id)
        WHERE s.canonical_symbol IN ({})
        """.format(",".join("?" for _ in symbols)),
        tuple(symbols),
    ).fetchall()
    values = [row[0] for row in rows if row[0]]
    return len(values) == len(symbols) and len(set(values)) == len(symbols)


def event_types_registered(conn: sqlite3.Connection, event_types: set[str]) -> bool:
    rows = conn.execute("SELECT event_type FROM corporate_event_type_definitions").fetchall()
    return event_types.issubset({row[0] for row in rows})


def critical_identifier_duplicates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT identifier_type, identifier_value, COUNT(DISTINCT canonical_security_id) AS securities
        FROM identifiers
        WHERE identifier_type IN ('iwb_symbol', 'massive_symbol', 'ibkr_con_id')
          AND identifier_value <> ''
        GROUP BY identifier_type, identifier_value
        HAVING securities > 1
        ORDER BY identifier_type, identifier_value
        """
    ).fetchall()
    return [
        {"identifier_type": row[0], "identifier_value": row[1], "securities": row[2]}
        for row in rows
    ]


def finalize_validation(paths: SecurityMasterPaths, checks: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    error_failures = [check for check in checks if not check["passed"] and check["severity"] == "error"]
    report = {
        "validated_at_utc": utc_now_text(),
        "ok": not error_failures,
        "checks": checks,
        "summary": summary,
        "database": str(paths.database),
        "production_runtime_changed": False,
        "corrected_dataset_written": False,
    }
    write_json_atomic(paths.validation_report, report)
    write_csv_atomic(paths.validation_csv, ["check", "passed", "severity", "details"], checks)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate the TradingbotR1000 Security Master")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iwb-file", type=Path, default=DEFAULT_IWB_FILE)
    parser.add_argument("--validate-only", action="store_true")
    return parser


def paths_from_args(args: argparse.Namespace) -> SecurityMasterPaths:
    output_dir = args.output_dir
    return SecurityMasterPaths(
        iwb_file=args.iwb_file,
        output_dir=output_dir,
        database=output_dir / "security_master.sqlite3",
        security_export=output_dir / "security_master_export.csv",
        identifiers_export=output_dir / "security_master_identifiers.csv",
        actions_export=output_dir / "security_master_corporate_actions.csv",
        manifest=output_dir / "security_master_manifest.json",
        validation_report=output_dir / "security_master_validation_report.json",
        validation_csv=output_dir / "security_master_validation_checks.csv",
    )

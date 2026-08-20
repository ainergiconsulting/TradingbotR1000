from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


class FlexNormalizationError(RuntimeError):
    pass


@dataclass
class NormalizedReport:
    source_path: Path
    sha256: str
    statement_from: str = ""
    statement_to: str = ""
    when_generated: str = ""
    base_currency: str = ""
    nav: list[dict[str, Any]] = field(default_factory=list)
    cash: list[dict[str, Any]] = field(default_factory=list)
    fx_rates: list[dict[str, Any]] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    symbol_pnl: list[dict[str, Any]] = field(default_factory=list)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal(value: str | None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None


def _float(value: str | None) -> float | None:
    number = _decimal(value)
    return None if number is None else float(number)


def _date(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    return text


def _attrs(elem: ET.Element) -> dict[str, str]:
    return {key: value for key, value in elem.attrib.items()}


def _symbol_pnl_identity(row: dict[str, str]) -> tuple[str, str, str]:
    symbol = (row.get("symbol") or row.get("underlyingSymbol") or "").strip()
    conid = (row.get("conid") or row.get("underlyingConid") or "").strip()
    description = (row.get("description") or "").strip()
    if symbol or conid:
        return symbol, conid or symbol, ""
    if description:
        return (
            "UNALLOCATED_ACCOUNT_LEVEL",
            "UNALLOCATED_ACCOUNT_LEVEL",
            f"IBKR Flex account-level performance summary row: {description}",
        )
    return (
        "UNALLOCATED_ACCOUNT_LEVEL",
        "UNALLOCATED_ACCOUNT_LEVEL",
        "IBKR Flex performance summary row had no symbol, conId, or description.",
    )


def dedupe_key(row: dict[str, Any]) -> tuple[str, str]:
    for field_name in ("ibExecID", "tradeID", "transactionID"):
        value = str(row.get(field_name) or "").strip()
        if value:
            return field_name, value
    parts = [
        str(row.get("accountId") or ""),
        str(row.get("tradeDate") or row.get("dateTime") or row.get("reportDate") or ""),
        str(row.get("conid") or ""),
        str(row.get("buySell") or ""),
        str(row.get("quantity") or ""),
        str(row.get("tradePrice") or ""),
        str(row.get("ibOrderID") or ""),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return "composite", digest


def _conversion_rate_for(report: NormalizedReport, from_currency: str, to_currency: str, report_date: str) -> float | None:
    if not from_currency or not to_currency or from_currency == to_currency:
        return 1.0
    for row in report.fx_rates:
        if (
            row.get("from_currency") == from_currency
            and row.get("to_currency") == to_currency
            and (not report_date or row.get("report_date") == report_date)
        ):
            return _float(row.get("rate"))
    for row in report.fx_rates:
        if row.get("from_currency") == from_currency and row.get("to_currency") == to_currency:
            return _float(row.get("rate"))
    return None


def _base_amount(value: float | None, currency: str, base_currency: str, fx_rate_to_base: float | None, report: NormalizedReport, report_date: str) -> tuple[float | None, bool]:
    if value is None:
        return None, False
    if not currency or not base_currency or currency == base_currency:
        return value, False
    rate = fx_rate_to_base or _conversion_rate_for(report, currency, base_currency, report_date)
    if rate is None:
        return None, True
    return value * rate, False


def parse_xml_report(path: Path) -> NormalizedReport:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise FlexNormalizationError(f"Invalid XML report: {path.name}") from error
    statement = root.find(".//FlexStatement")
    if statement is None:
        raise FlexNormalizationError(f"Missing FlexStatement: {path.name}")
    report = NormalizedReport(
        source_path=path,
        sha256=sha256_file(path),
        statement_from=_date(statement.attrib.get("fromDate")),
        statement_to=_date(statement.attrib.get("toDate")),
        when_generated=statement.attrib.get("whenGenerated", ""),
    )

    for elem in root.findall(".//ConversionRate"):
        row = _attrs(elem)
        report.fx_rates.append(
            {
                "report_date": _date(row.get("reportDate")),
                "from_currency": row.get("fromCurrency", ""),
                "to_currency": row.get("toCurrency", ""),
                "rate": _float(row.get("rate")),
            }
        )

    for elem in root.findall(".//ChangeInNAV"):
        row = _attrs(elem)
        report.base_currency = report.base_currency or row.get("currency", "")
        starting = _float(row.get("startingValue"))
        ending = _float(row.get("endingValue"))
        external_flow = sum(
            value or 0.0
            for value in (
                _float(row.get("depositsWithdrawals")),
                _float(row.get("assetTransfers")),
                _float(row.get("internalCashTransfers")),
            )
        )
        daily_pnl = None if starting is None or ending is None else ending - starting - external_flow
        daily_return_pct = None if daily_pnl is None or not starting else daily_pnl / starting
        report.nav.append(
            {
                "report_date": _date(row.get("toDate") or report.statement_to),
                "currency": row.get("currency", ""),
                "starting_value": starting,
                "ending_value": ending,
                "realized": _float(row.get("realized")),
                "change_unrealized": _float(row.get("changeInUnrealized")),
                "mtm": _float(row.get("mtm")),
                "commissions": _float(row.get("commissions")),
                "fx_translation": _float(row.get("fxTranslation")),
                "deposits_withdrawals": _float(row.get("depositsWithdrawals")),
                "daily_pnl": daily_pnl,
                "daily_return_pct": daily_return_pct,
            }
        )

    if not report.base_currency:
        equity = root.find(".//EquitySummaryByReportDateInBase")
        if equity is not None:
            report.base_currency = equity.attrib.get("currency", "")

    for elem in root.findall(".//CashReportCurrency"):
        row = _attrs(elem)
        report.cash.append(
            {
                "report_date": _date(row.get("toDate") or report.statement_to),
                "currency": row.get("currency", ""),
                "starting_cash": _float(row.get("startingCash")),
                "ending_cash": _float(row.get("endingCash")),
                "deposits": _float(row.get("deposits")),
                "withdrawals": _float(row.get("withdrawals")),
                "commissions": _float(row.get("commissions")),
                "net_trades_purchases": _float(row.get("netTradesPurchases")),
                "net_trades_sales": _float(row.get("netTradesSales")),
                "realized_vm": _float(row.get("realizedVm")),
                "realized_forex_vm": _float(row.get("realizedForexVm")),
                "fx_translation_gain_loss": _float(row.get("fxTranslationGainLoss")),
            }
        )

    for elem in root.findall(".//Trade"):
        row = _attrs(elem)
        key_field, key_value = dedupe_key(row)
        report_date = _date(row.get("tradeDate") or row.get("reportDate") or report.statement_to)
        currency = row.get("currency", "")
        fx_rate = _float(row.get("fxRateToBase"))
        realized = _float(row.get("fifoPnlRealized"))
        mtm = _float(row.get("mtmPnl"))
        commission = _float(row.get("ibCommission"))
        realized_base, unresolved_realized = _base_amount(realized, currency, report.base_currency, fx_rate, report, report_date)
        mtm_base, unresolved_mtm = _base_amount(mtm, currency, report.base_currency, fx_rate, report, report_date)
        commission_currency = row.get("ibCommissionCurrency", currency)
        commission_base, unresolved_commission = _base_amount(commission, commission_currency, report.base_currency, fx_rate, report, report_date)
        report.executions.append(
            {
                "dedupe_key": f"{key_field}:{key_value}",
                "dedupe_key_field": key_field,
                "ibExecID": row.get("ibExecID", ""),
                "ibOrderID": row.get("ibOrderID", ""),
                "tradeID": row.get("tradeID", ""),
                "transactionID": row.get("transactionID", ""),
                "trade_date": report_date,
                "date_time": row.get("dateTime", ""),
                "symbol": row.get("symbol", ""),
                "conid": row.get("conid", ""),
                "asset_category": row.get("assetCategory", ""),
                "buy_sell": row.get("buySell", ""),
                "quantity": _float(row.get("quantity")),
                "trade_price": _float(row.get("tradePrice")),
                "currency": currency,
                "fx_rate_to_base": fx_rate,
                "commission": commission,
                "commission_currency": commission_currency,
                "commission_base": commission_base,
                "realized_pnl": realized,
                "realized_pnl_base": realized_base,
                "mtm_pnl": mtm,
                "mtm_pnl_base": mtm_base,
                "net_cash": _float(row.get("netCash")),
                "proceeds": _float(row.get("proceeds")),
                "trade_money": _float(row.get("tradeMoney")),
                "is_api_order": row.get("isAPIOrder", ""),
                "order_type": row.get("orderType", ""),
                "exchange": row.get("exchange", ""),
                "listing_exchange": row.get("listingExchange", ""),
                "unresolved_fx": bool(unresolved_realized or unresolved_mtm or unresolved_commission),
            }
        )

    for elem in root.findall(".//FIFOPerformanceSummaryUnderlying"):
        row = _attrs(elem)
        symbol, conid, classification_reason = _symbol_pnl_identity(row)
        report.symbol_pnl.append(
            {
                "report_date": _date(row.get("reportDate") or report.statement_to),
                "symbol": symbol,
                "conid": conid,
                "method": "FIFO",
                "realized_pnl_base": _float(row.get("totalRealizedPnl")),
                "unrealized_pnl_base": _float(row.get("totalUnrealizedPnl")),
                "total_pnl_base": _float(row.get("totalFifoPnl")),
                "commissions_base": None,
                "classification_reason": classification_reason,
            }
        )
    for elem in root.findall(".//MTMPerformanceSummaryUnderlying"):
        row = _attrs(elem)
        symbol, conid, classification_reason = _symbol_pnl_identity(row)
        report.symbol_pnl.append(
            {
                "report_date": _date(row.get("reportDate") or report.statement_to),
                "symbol": symbol,
                "conid": conid,
                "method": "MTM",
                "realized_pnl_base": None,
                "unrealized_pnl_base": None,
                "total_pnl_base": _float(row.get("totalWithAccruals") or row.get("total")),
                "commissions_base": _float(row.get("commissions")),
                "classification_reason": classification_reason,
            }
        )
    if not report.nav:
        raise FlexNormalizationError(f"Daily Activity report has no NAV rows: {path.name}")
    return report


def parse_csv_report(path: Path) -> NormalizedReport:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise FlexNormalizationError(f"CSV report has no rows: {path.name}")
    raise FlexNormalizationError("CSV Daily Activity normalization is not implemented for this IBKR export format yet.")


def parse_report(path: Path) -> NormalizedReport:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return parse_xml_report(path)
    if suffix == ".csv":
        return parse_csv_report(path)
    raise FlexNormalizationError(f"Unsupported raw report extension: {path.name}")

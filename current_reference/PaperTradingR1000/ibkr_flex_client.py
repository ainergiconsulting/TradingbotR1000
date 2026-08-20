"""
Minimum IBKR Flex Web Service client for TradingbotR1000.

This module intentionally does not parse statement contents into project records.
Its only job is to prove the official reporting connection and save the raw
statement returned by IBKR without modification.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "flex_config.json"
DEFAULT_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
USER_AGENT = "TradingbotR1000-FlexClient/1.0"


class FlexConfigError(RuntimeError):
    pass


class FlexServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlexConfig:
    enabled: bool
    token: str
    activity_query_id: str
    trade_confirmation_query_id: str
    base_url: str = DEFAULT_BASE_URL
    output_dir: Path = BASE_DIR / "reports" / "flex_raw"
    wait_seconds: int = 20
    max_get_attempts: int = 5
    retry_seconds: int = 10

    def query_id_for(self, report_type: str) -> str:
        if report_type == "activity":
            return self.activity_query_id
        if report_type == "trade_confirmation":
            return self.trade_confirmation_query_id
        raise FlexConfigError(
            "Unsupported report type. Use 'activity' or 'trade_confirmation'."
        )


def load_config(path: Path | None = None) -> FlexConfig:
    config_path = Path(
        path
        or os.environ.get("IBKR_FLEX_CONFIG", "")
        or DEFAULT_CONFIG_PATH
    )

    if not config_path.exists():
        raise FlexConfigError(
            f"Missing Flex config file: {config_path}. "
            "Copy flex_config.example.json to flex_config.json and fill it locally."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    token = os.environ.get("IBKR_FLEX_TOKEN") or str(data.get("token", "")).strip()
    activity_query_id = (
        os.environ.get("IBKR_FLEX_ACTIVITY_QUERY_ID")
        or str(data.get("activity_query_id", "")).strip()
    )
    trade_confirmation_query_id = (
        os.environ.get("IBKR_FLEX_TRADE_CONFIRMATION_QUERY_ID")
        or str(data.get("trade_confirmation_query_id", "")).strip()
    )

    output_dir = Path(data.get("output_dir") or BASE_DIR / "reports" / "flex_raw")
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir

    return FlexConfig(
        enabled=bool(data.get("enabled", False)),
        token=token,
        activity_query_id=activity_query_id,
        trade_confirmation_query_id=trade_confirmation_query_id,
        base_url=str(data.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        output_dir=output_dir,
        wait_seconds=int(data.get("wait_seconds", 20)),
        max_get_attempts=int(data.get("max_get_attempts", 5)),
        retry_seconds=int(data.get("retry_seconds", 10)),
    )


def validate_config(config: FlexConfig, report_type: str) -> str:
    if not config.enabled:
        raise FlexConfigError(
            "Flex config is disabled. Set enabled=true only after the owner has "
            "created a PAPER Flex Web Service token and query ID."
        )
    if not config.token:
        raise FlexConfigError("Missing IBKR Flex token.")

    query_id = config.query_id_for(report_type)
    if not query_id:
        raise FlexConfigError(f"Missing IBKR Flex query ID for {report_type}.")
    return query_id


def _http_get_bytes(url: str, params: dict[str, str], timeout: int = 60) -> bytes:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(request_url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except URLError as error:
        raise FlexServiceError(f"Flex Web Service HTTP request failed: {error}") from error


def _parse_xml(payload: bytes) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as error:
        raise FlexServiceError("Flex Web Service returned non-XML response.") from error


def _child_text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    return "" if node is None or node.text is None else node.text.strip()


def _raise_if_fail(root: ET.Element, context: str) -> None:
    status = _child_text(root, "Status")
    if status != "Fail":
        return

    code = _child_text(root, "ErrorCode")
    message = _child_text(root, "ErrorMessage")
    raise FlexServiceError(
        f"{context} failed | error_code={code or 'UNKNOWN'} | "
        f"message={message or 'No message returned'}"
    )


def send_request(
    config: FlexConfig,
    query_id: str,
    http_get: Callable[[str, dict[str, str]], bytes] = _http_get_bytes,
) -> str:
    payload = http_get(
        f"{config.base_url}/SendRequest",
        {"t": config.token, "q": query_id, "v": "3"},
    )
    root = _parse_xml(payload)
    _raise_if_fail(root, "SendRequest")

    status = _child_text(root, "Status")
    reference_code = _child_text(root, "ReferenceCode")
    if status != "Success" or not reference_code:
        raise FlexServiceError("SendRequest did not return Success and ReferenceCode.")
    return reference_code


def get_statement(
    config: FlexConfig,
    reference_code: str,
    http_get: Callable[[str, dict[str, str]], bytes] = _http_get_bytes,
) -> bytes:
    return http_get(
        f"{config.base_url}/GetStatement",
        {"t": config.token, "q": reference_code, "v": "3"},
    )


def _looks_like_temporary_flex_error(payload: bytes) -> bool:
    try:
        root = _parse_xml(payload)
    except FlexServiceError:
        return False

    status = _child_text(root, "Status")
    code = _child_text(root, "ErrorCode")
    return status == "Fail" and code in {"1001", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"}


def save_raw_statement(
    payload: bytes,
    config: FlexConfig,
    report_type: str,
    reference_code: str,
) -> Path:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = config.output_dir / f"ibkr_flex_{report_type}_{timestamp}_{reference_code}.xml"
    with open(path, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    return path


def fetch_and_save_report(
    report_type: str,
    config_path: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    config = load_config(config_path)
    query_id = validate_config(config, report_type)

    reference_code = send_request(config, query_id)
    sleep(config.wait_seconds)

    payload = b""
    for attempt in range(1, config.max_get_attempts + 1):
        payload = get_statement(config, reference_code)
        if not _looks_like_temporary_flex_error(payload):
            break
        if attempt < config.max_get_attempts:
            sleep(config.retry_seconds)

    if _looks_like_temporary_flex_error(payload):
        root = _parse_xml(payload)
        _raise_if_fail(root, "GetStatement")

    return save_raw_statement(payload, config, report_type, reference_code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one raw IBKR Flex Web Service report."
    )
    parser.add_argument(
        "--report-type",
        choices=("activity", "trade_confirmation"),
        default="activity",
    )
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        output_path = fetch_and_save_report(args.report_type, args.config)
    except (FlexConfigError, FlexServiceError) as error:
        print(f"IBKR Flex fetch failed: {error}")
        return 2

    print(f"Saved raw IBKR Flex report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

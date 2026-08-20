from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .config import FlexAnalyticsConfig, validate_config


USER_AGENT = "TradingbotR1000-DailyFlexAnalytics/1.0"
TEMPORARY_FLEX_ERROR_CODES = {
    "1001",
    "1003",
    "1004",
    "1005",
    "1006",
    "1007",
    "1008",
    "1009",
    "1019",
    "1021",
}


class FlexAnalyticsDownloadError(RuntimeError):
    pass


class StatementNotReady(FlexAnalyticsDownloadError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    sha256: str
    reference_code: str
    content_type: str


def _http_get_bytes(url: str, params: dict[str, str], timeout: int = 60) -> bytes:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(request_url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except URLError as error:
        raise FlexAnalyticsDownloadError(f"Flex HTTPS request failed: {type(error).__name__}") from error


def _parse_xml(payload: bytes) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as error:
        raise FlexAnalyticsDownloadError("Flex response is not valid XML.") from error


def _child_text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _raise_for_flex_failure(root: ET.Element, context: str) -> None:
    status = _child_text(root, "Status")
    if status != "Fail":
        return
    code = _child_text(root, "ErrorCode") or "UNKNOWN"
    message = _child_text(root, "ErrorMessage") or "No message returned"
    if code in TEMPORARY_FLEX_ERROR_CODES:
        raise StatementNotReady(f"{context} not ready | error_code={code}")
    raise FlexAnalyticsDownloadError(f"{context} failed | error_code={code} | message={message}")


def send_request(
    config: FlexAnalyticsConfig,
    http_get: Callable[[str, dict[str, str]], bytes] = _http_get_bytes,
) -> str:
    validate_config(config)
    payload = http_get(
        f"{config.base_url}/SendRequest",
        {"t": config.token, "q": config.daily_activity_query_id, "v": "3"},
    )
    root = _parse_xml(payload)
    _raise_for_flex_failure(root, "SendRequest")
    reference_code = _child_text(root, "ReferenceCode")
    if _child_text(root, "Status") != "Success" or not reference_code:
        raise FlexAnalyticsDownloadError("SendRequest did not return Success and ReferenceCode.")
    return reference_code


def get_statement(
    config: FlexAnalyticsConfig,
    reference_code: str,
    http_get: Callable[[str, dict[str, str]], bytes] = _http_get_bytes,
) -> bytes:
    return http_get(
        f"{config.base_url}/GetStatement",
        {"t": config.token, "q": reference_code, "v": "3"},
    )


def validate_activity_payload(payload: bytes) -> str:
    stripped = payload.strip()
    if not stripped:
        raise FlexAnalyticsDownloadError("Flex payload is empty.")
    if stripped.startswith(b"<"):
        root = _parse_xml(stripped)
        _raise_for_flex_failure(root, "GetStatement")
        if root.find(".//FlexStatement") is None:
            raise FlexAnalyticsDownloadError("Flex payload does not contain a FlexStatement.")
        if root.find(".//ChangeInNAV") is None and root.find(".//EquitySummaryByReportDateInBase") is None:
            raise FlexAnalyticsDownloadError("Daily Activity payload is missing NAV/equity evidence.")
        return "xml"
    first_line = stripped.splitlines()[0].decode("utf-8", errors="replace")
    lower = first_line.lower()
    if "," in first_line and any(field in lower for field in ("trade", "nav", "cash", "reportdate", "accountid")):
        return "csv"
    raise FlexAnalyticsDownloadError("Flex payload is neither validated XML nor recognized CSV.")


def _safe_reference_code(reference_code: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", reference_code)
    return safe[:40] or "reference"


def save_immutable_raw(payload: bytes, config: FlexAnalyticsConfig, reference_code: str, content_type: str) -> DownloadResult:
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "csv" if content_type == "csv" else "xml"
    filename = f"daily_activity_{timestamp}_{_safe_reference_code(reference_code)}.{suffix}"
    path = config.raw_dir / filename
    sha = hashlib.sha256(payload).hexdigest()
    with open(path, "xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return DownloadResult(path=path, sha256=sha, reference_code=reference_code, content_type=content_type)


def download_daily_activity(
    config: FlexAnalyticsConfig,
    *,
    sleep: Callable[[float], None] = time.sleep,
    http_get: Callable[[str, dict[str, str]], bytes] = _http_get_bytes,
) -> DownloadResult:
    reference_code = send_request(config, http_get=http_get)
    sleep(config.wait_seconds)
    last_not_ready: StatementNotReady | None = None
    payload = b""
    for attempt in range(1, config.max_get_attempts + 1):
        payload = get_statement(config, reference_code, http_get=http_get)
        try:
            content_type = validate_activity_payload(payload)
            return save_immutable_raw(payload, config, reference_code, content_type)
        except StatementNotReady as error:
            last_not_ready = error
            if attempt < config.max_get_attempts:
                sleep(config.retry_seconds)
                continue
            break
    if last_not_ready is not None:
        raise last_not_ready
    validate_activity_payload(payload)
    raise FlexAnalyticsDownloadError("Unexpected Flex download state.")

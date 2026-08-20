"""Daily R1000 strategy-cycle scheduling helpers."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
from zoneinfo import ZoneInfo
from typing import Any

import config as cfg
from monitoring_io import atomic_write_json, utc_timestamp


NY_TZ = ZoneInfo(cfg.STRATEGY_CYCLE_TIMEZONE)


class SchedulerConfigError(ValueError):
    pass


def cycle_time() -> time:
    try:
        hour_text, minute_text = str(cfg.STRATEGY_CYCLE_TIME_ET).split(":", 1)
        return time(int(hour_text), int(minute_text))
    except Exception as exc:
        raise SchedulerConfigError(f"invalid_strategy_cycle_time_et:{cfg.STRATEGY_CYCLE_TIME_ET}") from exc


def load_scheduler_state() -> dict[str, Any]:
    try:
        data = json.loads(cfg.SCHEDULER_STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"bot": cfg.BOT_NAME, "cycle_time_et": cfg.STRATEGY_CYCLE_TIME_ET}
    if not isinstance(data, dict):
        return {"bot": cfg.BOT_NAME, "cycle_time_et": cfg.STRATEGY_CYCLE_TIME_ET}
    return data


def save_scheduler_state(**updates: Any) -> dict[str, Any]:
    state = load_scheduler_state()
    state.update(updates)
    state["bot"] = cfg.BOT_NAME
    state["cycle_time_et"] = cfg.STRATEGY_CYCLE_TIME_ET
    state["timezone"] = cfg.STRATEGY_CYCLE_TIMEZONE
    state["updated_at_utc"] = utc_timestamp()
    atomic_write_json(cfg.SCHEDULER_STATE_FILE, state)
    return state


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    current = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    actual = date(year, month, day)
    if actual.weekday() == 5:
        return actual - timedelta(days=1)
    if actual.weekday() == 6:
        return actual + timedelta(days=1)
    return actual


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def market_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 6, 19),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }
    next_new_year = _observed_fixed_holiday(year + 1, 1, 1)
    if next_new_year.year == year:
        holidays.add(next_new_year)
    return holidays


def is_market_session_day(day: date) -> bool:
    return day.weekday() < 5 and day not in market_holidays(day.year)


def _next_market_session(day: datetime) -> datetime:
    current = day
    while not is_market_session_day(current.date()):
        current += timedelta(days=1)
    return current


def next_cycle_time(now: datetime | None = None, state: dict[str, Any] | None = None) -> datetime:
    now_utc = now or datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY_TZ)
    target = cycle_time()
    candidate = now_ny.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if now_ny > candidate or now_ny.date().isoformat() == (state or load_scheduler_state()).get("last_cycle_date"):
        candidate += timedelta(days=1)
    candidate = _next_market_session(candidate)
    return candidate.astimezone(timezone.utc)


def is_cycle_due(now: datetime | None = None, state: dict[str, Any] | None = None) -> bool:
    state = state or load_scheduler_state()
    now_utc = now or datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY_TZ)
    if not is_market_session_day(now_ny.date()):
        return False
    if state.get("last_cycle_date") == now_ny.date().isoformat():
        return False
    target = cycle_time()
    return now_ny.time() >= target


def record_cycle_result(
    *,
    cycle_id: str,
    result: str,
    detail: str = "",
    now: datetime | None = None,
    cycle_time_utc: str | None = None,
) -> dict[str, Any]:
    now_utc = now or datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY_TZ)
    return save_scheduler_state(
        last_cycle_date=now_ny.date().isoformat(),
        last_cycle_id=cycle_id,
        last_cycle_time_utc=cycle_time_utc or utc_timestamp(),
        last_cycle_result=result,
        last_cycle_detail=detail,
    )


def runtime_summary(now: datetime | None = None) -> dict[str, Any]:
    state = load_scheduler_state()
    next_cycle = next_cycle_time(now, state)
    return {
        "cycle_time_et": cfg.STRATEGY_CYCLE_TIME_ET,
        "timezone": cfg.STRATEGY_CYCLE_TIMEZONE,
        "next_strategy_cycle_utc": next_cycle.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "last_strategy_cycle_utc": state.get("last_cycle_time_utc", ""),
        "last_strategy_cycle_result": state.get("last_cycle_result", "not_run"),
        "last_strategy_cycle_id": state.get("last_cycle_id", ""),
    }

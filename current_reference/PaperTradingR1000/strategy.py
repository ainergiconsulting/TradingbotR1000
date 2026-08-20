"""Approved TradingbotR1000 strategy rules.

This module is intentionally pure strategy logic. It does not choose a data
provider, universe provider, broker order type, or time-in-force because those
are not strategy rules in the approved final specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable, Sequence


STRATEGY_SPECIFICATION = "TradingbotR1000_Strategy_Specification_FINAL_v1.1.docx"
STRATEGY_VERSION = "1.1"


@dataclass(frozen=True)
class StrategyParameters:
    universe: str = "Russell 1000 stocks"
    timeframe: str = "daily"
    investable_capital_pct: float = 0.70
    liquidity_reserve_pct: float = 0.30
    position_allocation_pct: float = 0.20
    max_positions: int = 5
    leverage_allowed: bool = False
    moving_average_period: int = 200
    bollinger_period: int = 20
    bollinger_std_dev: float = 2.5
    buy_limit_multiplier: float = 0.97
    ranking_lookback_days: int = 150
    rsi_period: int = 2
    rsi_exit_cross_level: float = 50.0
    max_holding_trading_days: int = 10


APPROVED_PARAMETERS = StrategyParameters()


@dataclass(frozen=True)
class EntryEvaluation:
    symbol: str
    signal_day_close: float
    moving_average: float
    lower_bollinger_band: float
    ranking_return: float
    trend_condition: bool
    pullback_condition: bool

    @property
    def is_candidate(self) -> bool:
        return self.trend_condition and self.pullback_condition


@dataclass(frozen=True)
class CandidateSelection:
    selected: tuple[EntryEvaluation, ...]
    skipped: tuple[EntryEvaluation, ...]
    ranking_applied: bool


@dataclass(frozen=True)
class BuyOrderPlan:
    symbol: str
    limit_price: float
    allocation_value: float
    investable_capital: float
    liquidity_reserve: float
    intended_session: str = "next_trading_day"


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str | None
    timing: str | None


def simple_moving_average(values: Sequence[float], period: int) -> float:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        raise ValueError("not enough values for moving average")
    window = values[-period:]
    return sum(window) / period


def population_std_dev(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("values must not be empty")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return sqrt(variance)


def lower_bollinger_band(
    closes: Sequence[float],
    period: int = APPROVED_PARAMETERS.bollinger_period,
    std_dev_width: float = APPROVED_PARAMETERS.bollinger_std_dev,
) -> float:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(closes) < period:
        raise ValueError("not enough closes for Bollinger Band")
    window = closes[-period:]
    return simple_moving_average(window, period) - std_dev_width * population_std_dev(window)


def price_appreciation(closes: Sequence[float], lookback_days: int) -> float:
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if len(closes) <= lookback_days:
        raise ValueError("not enough closes for ranking lookback")
    start = closes[-lookback_days - 1]
    end = closes[-1]
    if start <= 0:
        raise ValueError("lookback start close must be positive")
    return (end / start) - 1.0


def evaluate_entry_candidate(
    symbol: str,
    closes: Sequence[float],
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> EntryEvaluation:
    required = max(params.moving_average_period, params.ranking_lookback_days + 1)
    if len(closes) < required:
        raise ValueError(f"at least {required} completed daily closes are required")

    signal_day_close = closes[-1]
    moving_average = simple_moving_average(closes, params.moving_average_period)
    lower_band = lower_bollinger_band(
        closes,
        params.bollinger_period,
        params.bollinger_std_dev,
    )
    ranking_return = price_appreciation(closes, params.ranking_lookback_days)

    return EntryEvaluation(
        symbol=symbol,
        signal_day_close=signal_day_close,
        moving_average=moving_average,
        lower_bollinger_band=lower_band,
        ranking_return=ranking_return,
        trend_condition=signal_day_close > moving_average,
        pullback_condition=signal_day_close < lower_band,
    )


def available_slots(
    open_positions: int,
    pending_buy_orders: int = 0,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> int:
    used_slots = open_positions + pending_buy_orders
    return max(params.max_positions - used_slots, 0)


def select_candidates(
    candidates: Iterable[EntryEvaluation],
    slots_available: int,
) -> CandidateSelection:
    eligible = [candidate for candidate in candidates if candidate.is_candidate]
    if slots_available <= 0:
        return CandidateSelection(
            selected=(),
            skipped=tuple(eligible),
            ranking_applied=False,
        )

    if len(eligible) <= slots_available:
        return CandidateSelection(
            selected=tuple(eligible),
            skipped=(),
            ranking_applied=False,
        )

    ranked = sorted(
        eligible,
        key=lambda item: (-item.ranking_return, item.symbol.upper(), item.symbol),
    )

    return CandidateSelection(
        selected=tuple(ranked[:slots_available]),
        skipped=tuple(ranked[slots_available:]),
        ranking_applied=True,
    )


def buy_limit_price(
    signal_day_close: float,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> float:
    if signal_day_close <= 0:
        raise ValueError("signal_day_close must be positive")
    return signal_day_close * params.buy_limit_multiplier


def position_allocation_value(
    net_liquidation_value: float,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> float:
    return investable_capital_value(net_liquidation_value, params) * params.position_allocation_pct


def investable_capital_value(
    net_liquidation_value: float,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> float:
    if net_liquidation_value < 0:
        raise ValueError("net_liquidation_value must not be negative")
    return net_liquidation_value * params.investable_capital_pct


def liquidity_reserve_value(
    net_liquidation_value: float,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> float:
    if net_liquidation_value < 0:
        raise ValueError("net_liquidation_value must not be negative")
    return net_liquidation_value * params.liquidity_reserve_pct


def build_buy_order_plan(
    candidate: EntryEvaluation,
    net_liquidation_value: float,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> BuyOrderPlan:
    return BuyOrderPlan(
        symbol=candidate.symbol,
        limit_price=buy_limit_price(candidate.signal_day_close, params),
        allocation_value=position_allocation_value(net_liquidation_value, params),
        investable_capital=investable_capital_value(net_liquidation_value, params),
        liquidity_reserve=liquidity_reserve_value(net_liquidation_value, params),
    )


def rsi_values(closes: Sequence[float], period: int = APPROVED_PARAMETERS.rsi_period) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(closes) < period + 1:
        raise ValueError("not enough closes for RSI")

    deltas = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    values: list[float] = []

    def to_rsi(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        relative_strength = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    values.append(to_rsi(average_gain, average_loss))
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        values.append(to_rsi(average_gain, average_loss))
    return values


def latest_rsi_cross_values(
    closes: Sequence[float],
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> tuple[float, float]:
    values = rsi_values(closes, params.rsi_period)
    if len(values) < 2:
        raise ValueError("at least two completed RSI values are required")
    return values[-2], values[-1]


def is_rsi_exit_cross(
    previous_rsi: float,
    current_rsi: float,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> bool:
    return previous_rsi <= params.rsi_exit_cross_level and current_rsi > params.rsi_exit_cross_level


def exit_decision(
    previous_rsi: float,
    current_rsi: float,
    holding_trading_days: int,
    params: StrategyParameters = APPROVED_PARAMETERS,
) -> ExitDecision:
    if holding_trading_days < 0:
        raise ValueError("holding_trading_days must not be negative")
    if is_rsi_exit_cross(previous_rsi, current_rsi, params):
        return ExitDecision(True, "rsi_cross_above_50", "next_market_open")
    if holding_trading_days >= params.max_holding_trading_days:
        return ExitDecision(True, "time_exit_10_trading_days", "next_market_open")
    return ExitDecision(False, None, None)

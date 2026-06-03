from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .config import BotConfig
from .indicators import atr
from .models import Direction, LiquiditySnapshot, MarketContext, SniperTrigger


class LiquidityAnalyzer:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def analyze(
        self,
        *,
        m1: pd.DataFrame,
        m5: pd.DataFrame,
        m15: pd.DataFrame,
        direction: Direction,
        trigger: SniperTrigger,
        spread: float,
        now: datetime,
    ) -> LiquiditySnapshot:
        trigger_row = _trigger_row(m1, trigger.timestamp)
        average_volume = _average_volume(m1, self.config.liquidity_volume_lookback)
        trigger_volume = float(trigger_row.get("tick_volume", 0.0))
        trigger_multiplier = _multiplier(trigger_volume, average_volume)
        sweep_multiplier = self._sweep_volume_multiplier(m1, direction, trigger, average_volume)

        spread_ok = spread <= self.config.max_liquidity_spread
        volume_ok = (
            trigger_multiplier >= self.config.min_trigger_volume_multiplier
            and sweep_multiplier >= self.config.min_sweep_volume_multiplier
        )
        smooth = self._smooth_price_action(m1)
        session = _session_label(now)
        session_ok = (not self.config.liquidity_session_filter_enabled) or session in {
            "london",
            "new_york",
            "london_new_york_overlap",
        }
        pools = self._liquidity_pools(m15, direction, trigger.entry_price)

        reason: list[str] = []
        if spread_ok:
            reason.append(f"Spread OK at {spread:.2f}")
        else:
            reason.append(
                f"Spread {spread:.2f} above max {self.config.max_liquidity_spread:.2f}"
            )
        if volume_ok:
            reason.append(
                f"Tick volume confirms entry ({trigger_multiplier:.2f}x trigger, "
                f"{sweep_multiplier:.2f}x sweep)"
            )
        else:
            reason.append(
                f"Tick volume weak ({trigger_multiplier:.2f}x trigger, "
                f"{sweep_multiplier:.2f}x sweep)"
            )
        reason.append(f"Session: {session}")
        reason.append("Price action smooth" if smooth else "Price action is jumpy")
        if pools:
            reason.append(f"Nearby liquidity pools: {'; '.join(pools[:3])}")

        passed = True
        if self.config.liquidity_filter_enabled:
            passed = spread_ok and volume_ok and smooth and session_ok

        return LiquiditySnapshot(
            spread=spread,
            spread_ok=spread_ok,
            session=session,
            session_ok=session_ok,
            trigger_volume=trigger_volume,
            average_volume=average_volume,
            trigger_volume_multiplier=trigger_multiplier,
            sweep_volume_multiplier=sweep_multiplier,
            volume_ok=volume_ok,
            smooth_price_action=smooth,
            liquidity_pools=pools,
            passed=passed,
            reason=reason,
        )

    def market_context(
        self,
        *,
        m1: pd.DataFrame,
        m15: pd.DataFrame,
        direction: Direction,
        spread: float,
        now: datetime,
    ) -> MarketContext:
        average_volume = _average_volume(m1, self.config.liquidity_volume_lookback)
        current_volume = _current_volume(m1)
        current_multiplier = _multiplier(current_volume, average_volume)
        spread_ok = spread <= self.config.max_liquidity_spread
        smooth = self._smooth_price_action(m1)
        session = _session_label(now)
        current_price = _current_price(m1)
        pools = self._liquidity_pools(m15, direction, current_price)

        reason = [
            f"Spread {'OK' if spread_ok else 'wide'} at {spread:.2f}",
            f"Current M1 tick volume {current_multiplier:.2f}x average",
            f"Session: {session}",
            "Price action smooth" if smooth else "Price action is jumpy",
        ]
        if pools:
            reason.append(f"Nearby liquidity pools: {'; '.join(pools[:3])}")

        return MarketContext(
            spread=spread,
            spread_ok=spread_ok,
            session=session,
            current_volume=current_volume,
            average_volume=average_volume,
            current_volume_multiplier=current_multiplier,
            smooth_price_action=smooth,
            liquidity_pools=pools,
            reason=reason,
        )

    def _sweep_volume_multiplier(
        self,
        m1: pd.DataFrame,
        direction: Direction,
        trigger: SniperTrigger,
        average_volume: float,
    ) -> float:
        recent = m1.tail(12)
        if direction == Direction.BUY:
            sweep_rows = recent[
                (recent["low"] <= trigger.swept_level)
                & (recent["close"] > trigger.swept_level)
            ]
        else:
            sweep_rows = recent[
                (recent["high"] >= trigger.swept_level)
                & (recent["close"] < trigger.swept_level)
            ]
        if sweep_rows.empty:
            return 0.0
        return _multiplier(float(sweep_rows.iloc[-1].get("tick_volume", 0.0)), average_volume)

    def _smooth_price_action(self, m1: pd.DataFrame) -> bool:
        if len(m1) < max(self.config.liquidity_smooth_lookback, self.config.atr_period) + 2:
            return True
        frame = m1.copy()
        frame["atr"] = atr(frame, self.config.atr_period)
        recent = frame.tail(self.config.liquidity_smooth_lookback)
        valid_atr = frame["atr"].dropna()
        if valid_atr.empty:
            return True
        latest_atr = float(valid_atr.iloc[-1])
        if latest_atr <= 0:
            return True
        max_range = float((recent["high"] - recent["low"]).max())
        return max_range <= latest_atr * self.config.max_liquidity_candle_atr_multiplier

    def _liquidity_pools(
        self,
        m15: pd.DataFrame,
        direction: Direction,
        current_price: float | None = None,
    ) -> list[str]:
        recent = m15.tail(self.config.liquidity_pool_lookback)
        if recent.empty:
            return []

        candidates = [
            _Pool("previous high", float(recent["high"].max()), "high"),
            _Pool("previous low", float(recent["low"].min()), "low"),
        ]
        candidates.extend(_equal_levels(recent, "high", self.config.equal_level_tolerance))
        candidates.extend(_equal_levels(recent, "low", self.config.equal_level_tolerance))

        last_12 = recent.tail(12)
        box_high = float(last_12["high"].max())
        box_low = float(last_12["low"].min())
        box_range = box_high - box_low
        avg_range = float((recent["high"] - recent["low"]).tail(20).mean())
        if avg_range > 0 and box_range <= avg_range * 3:
            candidates.append(
                _Pool(
                    "consolidation range",
                    box_low if direction == Direction.BUY else box_high,
                    "range",
                    high=box_high,
                    low=box_low,
                )
            )

        if direction == Direction.BUY:
            pools = [
                pool
                for pool in candidates
                if pool.kind in {"low", "range"} and _pool_below_price(pool, current_price)
            ]
        else:
            pools = [
                pool
                for pool in candidates
                if pool.kind in {"high", "range"} and _pool_above_price(pool, current_price)
            ]
        return [pool.label for pool in pools[:5]]


class _Pool:
    def __init__(
        self,
        name: str,
        price: float,
        kind: str,
        *,
        high: float | None = None,
        low: float | None = None,
    ) -> None:
        self.name = name
        self.price = price
        self.kind = kind
        self.high = high
        self.low = low

    @property
    def label(self) -> str:
        if self.kind == "range" and self.low is not None and self.high is not None:
            return f"{self.name} {self.low:.2f}-{self.high:.2f}"
        return f"{self.name} {self.price:.2f}"


def _trigger_row(m1: pd.DataFrame, timestamp: datetime) -> pd.Series:
    times = pd.to_datetime(m1["time"], utc=True)
    target = pd.Timestamp(timestamp)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    matches = m1[times == target]
    if not matches.empty:
        return matches.iloc[-1]
    return m1.iloc[-1]


def _average_volume(m1: pd.DataFrame, lookback: int) -> float:
    volumes = m1["tick_volume"].tail(max(lookback, 1))
    if volumes.empty:
        return 0.0
    return float(volumes.mean())


def _current_volume(m1: pd.DataFrame) -> float:
    if m1.empty:
        return 0.0
    return float(m1.iloc[-1].get("tick_volume", 0.0))


def _current_price(m1: pd.DataFrame) -> float | None:
    if m1.empty:
        return None
    return float(m1.iloc[-1].get("close", 0.0))


def _multiplier(value: float, average: float) -> float:
    if average <= 0:
        return 0.0
    return value / average


def _equal_levels(df: pd.DataFrame, column: str, tolerance: float) -> list[_Pool]:
    levels: list[_Pool] = []
    values = [float(value) for value in df[column].tail(30)]
    for idx, value in enumerate(values):
        matches = [other for other in values[idx + 1 :] if abs(other - value) <= tolerance]
        if len(matches) >= 1:
            name = "equal highs near" if column == "high" else "equal lows near"
            levels.append(_Pool(name, value, column))
            break
    return levels


def _pool_below_price(pool: _Pool, current_price: float | None) -> bool:
    if current_price is None:
        return True
    if pool.kind == "range" and pool.low is not None:
        return pool.low <= current_price
    return pool.price <= current_price


def _pool_above_price(pool: _Pool, current_price: float | None) -> bool:
    if current_price is None:
        return True
    if pool.kind == "range" and pool.high is not None:
        return pool.high >= current_price
    return pool.price >= current_price


def _session_label(now: datetime) -> str:
    utc_hour = now.astimezone(timezone.utc).hour
    if 12 <= utc_hour < 16:
        return "london_new_york_overlap"
    if 7 <= utc_hour < 12:
        return "london"
    if 16 <= utc_hour < 21:
        return "new_york"
    if 23 <= utc_hour or utc_hour < 7:
        return "asia"
    return "other"

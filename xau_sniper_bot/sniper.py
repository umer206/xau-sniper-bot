from __future__ import annotations

import pandas as pd

from .config import BotConfig
from .indicators import atr, body_size, ema, lower_wick, upper_wick
from .models import Direction, SniperTrigger, TargetLevel, Zone


class M1SniperScanner:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def scan(
        self,
        df: pd.DataFrame,
        zone: Zone,
        target_levels: list[TargetLevel] | None,
    ) -> SniperTrigger | None:
        if len(df) < max(40, self.config.m1_sweep_lookback + self.config.m1_bos_lookback + 5):
            return None

        frame = df.copy()
        frame["atr"] = atr(frame, self.config.atr_period)
        last = frame.iloc[-1]
        if not _recent_zone_touch(frame.tail(self.config.m1_zone_touch_lookback), zone):
            return None

        m1_atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
        if not self._atr_allowed(m1_atr):
            return None

        if zone.direction == Direction.BUY:
            return self._scan_buy(frame, zone, target_levels or [], m1_atr)
        return self._scan_sell(frame, zone, target_levels or [], m1_atr)

    def continuation_zone(
        self,
        df: pd.DataFrame,
        direction: Direction,
        current_price: float,
    ) -> Zone | None:
        if not self.config.continuation_mode_enabled or len(df) < 60:
            return None

        frame = df.copy()
        frame["atr"] = atr(frame, self.config.atr_period)
        frame["ema20"] = ema(frame["close"], 20)
        latest_atr = _latest_atr(frame)
        if not self._atr_allowed(latest_atr):
            return None

        recent = frame.tail(max(self.config.continuation_lookback_bars, 20))
        if direction == Direction.BUY:
            return self._buy_continuation_zone(recent, current_price, latest_atr)
        return self._sell_continuation_zone(recent, current_price, latest_atr)

    def _scan_buy(
        self,
        frame: pd.DataFrame,
        zone: Zone,
        target_levels: list[TargetLevel],
        m1_atr: float,
    ) -> SniperTrigger | None:
        sweep = self._find_buy_sweep(frame)
        if sweep is None:
            return None

        sweep_index, swept_level = sweep
        post_sweep = frame.loc[sweep_index:]
        last = frame.iloc[-1]
        pre_sweep = frame.loc[:sweep_index].tail(self.config.m1_bos_lookback + 1).iloc[:-1]
        if pre_sweep.empty:
            return None

        bos_level = float(pre_sweep["high"].max())
        closes_back_above = float(post_sweep.iloc[0]["close"]) > swept_level
        broke_structure = float(last["close"]) > bos_level
        displacement = self._bullish_displacement(last, m1_atr)
        rejection = self._buy_rejection(post_sweep.iloc[0])

        if not all([closes_back_above, broke_structure, displacement, rejection]):
            return None

        stop_loss = min(float(post_sweep["low"].min()), swept_level) - max(
            m1_atr * 0.25,
            0.01,
        )
        entry_price = float(last["close"])
        target_1, target_2 = _target_pair(
            Direction.BUY,
            entry_price,
            stop_loss,
            target_levels,
            self.config.risk_reward_floor,
        )
        risk_reward = _risk_reward(Direction.BUY, entry_price, stop_loss, target_1.price)
        if risk_reward < self.config.risk_reward_floor:
            return None

        return SniperTrigger(
            symbol=self.config.symbol,
            direction=Direction.BUY,
            timestamp=_to_datetime(last["time"]),
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            swept_level=swept_level,
            bos_level=bos_level,
            atr=m1_atr,
            risk_reward=risk_reward,
            reason=[
                "M1 swept sell-side liquidity below recent low",
                "M1 closed back above swept low",
                "M1 broke minor structure upward",
                "Bullish displacement and rejection filters passed",
            ],
        )

    def _scan_sell(
        self,
        frame: pd.DataFrame,
        zone: Zone,
        target_levels: list[TargetLevel],
        m1_atr: float,
    ) -> SniperTrigger | None:
        sweep = self._find_sell_sweep(frame)
        if sweep is None:
            return None

        sweep_index, swept_level = sweep
        post_sweep = frame.loc[sweep_index:]
        last = frame.iloc[-1]
        pre_sweep = frame.loc[:sweep_index].tail(self.config.m1_bos_lookback + 1).iloc[:-1]
        if pre_sweep.empty:
            return None

        bos_level = float(pre_sweep["low"].min())
        closes_back_below = float(post_sweep.iloc[0]["close"]) < swept_level
        broke_structure = float(last["close"]) < bos_level
        displacement = self._bearish_displacement(last, m1_atr)
        rejection = self._sell_rejection(post_sweep.iloc[0])

        if not all([closes_back_below, broke_structure, displacement, rejection]):
            return None

        stop_loss = max(float(post_sweep["high"].max()), swept_level) + max(
            m1_atr * 0.25,
            0.01,
        )
        entry_price = float(last["close"])
        target_1, target_2 = _target_pair(
            Direction.SELL,
            entry_price,
            stop_loss,
            target_levels,
            self.config.risk_reward_floor,
        )
        risk_reward = _risk_reward(Direction.SELL, entry_price, stop_loss, target_1.price)
        if risk_reward < self.config.risk_reward_floor:
            return None

        return SniperTrigger(
            symbol=self.config.symbol,
            direction=Direction.SELL,
            timestamp=_to_datetime(last["time"]),
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            swept_level=swept_level,
            bos_level=bos_level,
            atr=m1_atr,
            risk_reward=risk_reward,
            reason=[
                "M1 swept buy-side liquidity above recent high",
                "M1 closed back below swept high",
                "M1 broke minor structure downward",
                "Bearish displacement and rejection filters passed",
            ],
        )

    def _buy_continuation_zone(
        self,
        recent: pd.DataFrame,
        current_price: float,
        latest_atr: float,
    ) -> Zone | None:
        last = recent.iloc[-1]
        above_ema = float(last["close"]) > float(last["ema20"])
        bullish_displacement = any(
            self._bullish_displacement(row, latest_atr)
            for _, row in recent.tail(self.config.continuation_displacement_lookback).iterrows()
        )
        broke_high = _recent_m1_breakout(recent)
        if not (above_ema and (bullish_displacement or broke_high)):
            return None

        pullback = recent.tail(self.config.continuation_pullback_lookback)
        pullback_low = float(pullback["low"].min())
        if current_price - pullback_low > self.config.continuation_max_zone_distance_points:
            return None

        width = latest_atr * self.config.continuation_zone_atr_width
        return Zone(
            symbol=self.config.symbol,
            direction=Direction.BUY,
            timeframe="M1",
            low=pullback_low - width,
            high=pullback_low + max(width * 0.35, 0.01),
            anchor_time=_to_datetime(pullback.iloc[pullback["low"].argmin()]["time"]),
            created_at=_to_datetime(last["time"]),
            reason=[
                "M1 bullish continuation pullback zone",
                "M1 momentum is above EMA20 with breakout/displacement",
            ],
            strength=0.75,
            setup_type="continuation",
        )

    def _sell_continuation_zone(
        self,
        recent: pd.DataFrame,
        current_price: float,
        latest_atr: float,
    ) -> Zone | None:
        last = recent.iloc[-1]
        below_ema = float(last["close"]) < float(last["ema20"])
        bearish_displacement = any(
            self._bearish_displacement(row, latest_atr)
            for _, row in recent.tail(self.config.continuation_displacement_lookback).iterrows()
        )
        broke_low = _recent_m1_breakdown(recent)
        if not (below_ema and (bearish_displacement or broke_low)):
            return None

        pullback = recent.tail(self.config.continuation_pullback_lookback)
        pullback_high = float(pullback["high"].max())
        if pullback_high - current_price > self.config.continuation_max_zone_distance_points:
            return None

        width = latest_atr * self.config.continuation_zone_atr_width
        return Zone(
            symbol=self.config.symbol,
            direction=Direction.SELL,
            timeframe="M1",
            low=pullback_high - max(width * 0.35, 0.01),
            high=pullback_high + width,
            anchor_time=_to_datetime(pullback.iloc[pullback["high"].argmax()]["time"]),
            created_at=_to_datetime(last["time"]),
            reason=[
                "M1 bearish continuation pullback zone",
                "M1 momentum is below EMA20 with breakdown/displacement",
            ],
            strength=0.75,
            setup_type="continuation",
        )

    def _find_buy_sweep(self, frame: pd.DataFrame) -> tuple[int, float] | None:
        search = frame.tail(8)
        for index in reversed(search.index.tolist()):
            before = frame.loc[:index].tail(self.config.m1_sweep_lookback + 1).iloc[:-1]
            if before.empty:
                continue
            swept_level = float(before["low"].min())
            candle = frame.loc[index]
            if float(candle["low"]) < swept_level and float(candle["close"]) > swept_level:
                return int(index), swept_level
        return None

    def _find_sell_sweep(self, frame: pd.DataFrame) -> tuple[int, float] | None:
        search = frame.tail(8)
        for index in reversed(search.index.tolist()):
            before = frame.loc[:index].tail(self.config.m1_sweep_lookback + 1).iloc[:-1]
            if before.empty:
                continue
            swept_level = float(before["high"].max())
            candle = frame.loc[index]
            if float(candle["high"]) > swept_level and float(candle["close"]) < swept_level:
                return int(index), swept_level
        return None

    def _atr_allowed(self, value: float) -> bool:
        if self.config.min_m1_atr > 0 and value < self.config.min_m1_atr:
            return False
        if self.config.max_m1_atr > 0 and value > self.config.max_m1_atr:
            return False
        return value > 0

    def _bullish_displacement(self, row: pd.Series, m1_atr: float) -> bool:
        return (
            float(row["close"]) > float(row["open"])
            and body_size(row) >= m1_atr * self.config.min_displacement_atr
        )

    def _bearish_displacement(self, row: pd.Series, m1_atr: float) -> bool:
        return (
            float(row["close"]) < float(row["open"])
            and body_size(row) >= m1_atr * self.config.min_displacement_atr
        )

    def _buy_rejection(self, row: pd.Series) -> bool:
        return lower_wick(row) >= max(body_size(row), 0.01) * self.config.rejection_wick_ratio

    def _sell_rejection(self, row: pd.Series) -> bool:
        return upper_wick(row) >= max(body_size(row), 0.01) * self.config.rejection_wick_ratio


def _risk_reward(direction: Direction, entry: float, stop: float, target: float) -> float:
    if direction == Direction.BUY:
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target
    if risk <= 0:
        return 0.0
    return reward / risk


def _target_pair(
    direction: Direction,
    entry: float,
    stop: float,
    target_levels: list[TargetLevel],
    risk_reward_floor: float,
) -> tuple[TargetLevel, TargetLevel]:
    risk = abs(entry - stop)
    if direction == Direction.BUY:
        minimum_t1 = entry + (risk * risk_reward_floor)
        projected_t2 = entry + (risk * risk_reward_floor * 2)
    else:
        minimum_t1 = entry - (risk * risk_reward_floor)
        projected_t2 = entry - (risk * risk_reward_floor * 2)

    target_1 = (
        target_levels[0]
        if target_levels
        else TargetLevel(
            price=minimum_t1,
            label="minimum configured risk/reward projection",
            timeframe="M1",
        )
    )
    target_2 = (
        target_levels[1]
        if len(target_levels) > 1
        else TargetLevel(
            price=projected_t2,
            label="projected extension after target 1",
            timeframe="M1",
        )
    )
    return target_1, target_2


def _recent_zone_touch(df: pd.DataFrame, zone: Zone) -> bool:
    return bool(((df["low"] <= zone.high) & (df["high"] >= zone.low)).any())


def _latest_atr(frame: pd.DataFrame) -> float:
    valid_atr = frame["atr"].dropna()
    if valid_atr.empty:
        return 0.0
    return float(valid_atr.iloc[-1])


def _recent_m1_breakout(frame: pd.DataFrame) -> bool:
    if len(frame) < 12:
        return False
    recent = frame.tail(6)
    prior = frame.iloc[:-6].tail(12)
    if prior.empty:
        return False
    return bool((recent["close"] > float(prior["high"].max())).any())


def _recent_m1_breakdown(frame: pd.DataFrame) -> bool:
    if len(frame) < 12:
        return False
    recent = frame.tail(6)
    prior = frame.iloc[:-6].tail(12)
    if prior.empty:
        return False
    return bool((recent["close"] < float(prior["low"].min())).any())


def _to_datetime(value: object):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.to_pydatetime()

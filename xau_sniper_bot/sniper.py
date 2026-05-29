from __future__ import annotations

import pandas as pd

from .config import BotConfig
from .indicators import atr, body_size, lower_wick, upper_wick
from .models import Direction, SniperTrigger, Zone


class M1SniperScanner:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def scan(self, df: pd.DataFrame, zone: Zone, take_profit: float | None) -> SniperTrigger | None:
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
            return self._scan_buy(frame, zone, take_profit, m1_atr)
        return self._scan_sell(frame, zone, take_profit, m1_atr)

    def _scan_buy(
        self,
        frame: pd.DataFrame,
        zone: Zone,
        take_profit: float | None,
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
        target = take_profit or entry_price + (
            (entry_price - stop_loss) * self.config.risk_reward_floor
        )
        risk_reward = _risk_reward(Direction.BUY, entry_price, stop_loss, target)
        if risk_reward < self.config.risk_reward_floor:
            return None

        return SniperTrigger(
            symbol=self.config.symbol,
            direction=Direction.BUY,
            timestamp=_to_datetime(last["time"]),
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=target,
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
        take_profit: float | None,
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
        target = take_profit or entry_price - (
            (stop_loss - entry_price) * self.config.risk_reward_floor
        )
        risk_reward = _risk_reward(Direction.SELL, entry_price, stop_loss, target)
        if risk_reward < self.config.risk_reward_floor:
            return None

        return SniperTrigger(
            symbol=self.config.symbol,
            direction=Direction.SELL,
            timestamp=_to_datetime(last["time"]),
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=target,
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


def _recent_zone_touch(df: pd.DataFrame, zone: Zone) -> bool:
    return bool(((df["low"] <= zone.high) & (df["high"] >= zone.low)).any())


def _to_datetime(value: object):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.to_pydatetime()

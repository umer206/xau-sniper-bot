from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .config import BotConfig
from .indicators import atr, body_size, ema
from .models import ConfirmationSnapshot, Direction, Zone


class M5ConfirmationEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def confirm(self, df: pd.DataFrame, zone: Zone) -> ConfirmationSnapshot:
        if len(df) < 60:
            return self._snapshot(zone.direction, False, ["Need at least 60 M5 bars"])

        frame = df.copy()
        frame["atr"] = atr(frame, self.config.atr_period)
        frame["ema20"] = ema(frame["close"], 20)
        recent = frame.tail(self.config.m5_zone_touch_lookback)
        touched_zone = _touched_zone(recent, zone)
        if not touched_zone:
            return self._snapshot(zone.direction, False, ["M5 has not recently touched setup zone"])

        if zone.direction == Direction.BUY:
            return self._confirm_buy(frame, zone)
        return self._confirm_sell(frame, zone)

    def continuation_candidate(
        self,
        df: pd.DataFrame,
        direction: Direction,
        current_price: float,
    ) -> tuple[Zone, ConfirmationSnapshot] | None:
        if not self.config.continuation_mode_enabled or len(df) < 60:
            return None

        frame = df.copy()
        frame["atr"] = atr(frame, self.config.atr_period)
        frame["ema20"] = ema(frame["close"], 20)
        frame["ema50"] = ema(frame["close"], 50)

        latest_atr = _latest_atr(frame)
        if latest_atr <= 0:
            return None

        lookback = max(self.config.continuation_lookback_bars, 8)
        recent = frame.tail(lookback)
        if direction == Direction.BUY:
            return self._buy_continuation(recent, current_price, latest_atr)
        return self._sell_continuation(recent, current_price, latest_atr)

    def _confirm_buy(self, frame: pd.DataFrame, zone: Zone) -> ConfirmationSnapshot:
        last = frame.iloc[-1]
        recent = frame.tail(8)
        displacement = any(
            _bullish_displacement(row, self.config.min_displacement_atr)
            for _, row in recent.iterrows()
        )
        above_ema = float(last["close"]) > float(last["ema20"])
        held_zone = float(recent["low"].min()) >= zone.low

        reason: list[str] = []
        if displacement:
            reason.append("M5 has bullish displacement after zone interaction")
        if above_ema:
            reason.append("M5 close is above EMA20")
        if held_zone:
            reason.append("M5 has not invalidated demand zone low")

        confirmed = displacement and above_ema and held_zone
        if not confirmed:
            reason.append("M5 bullish confirmation is incomplete")
        return self._snapshot(Direction.BUY, confirmed, reason)

    def _confirm_sell(self, frame: pd.DataFrame, zone: Zone) -> ConfirmationSnapshot:
        last = frame.iloc[-1]
        recent = frame.tail(8)
        displacement = any(
            _bearish_displacement(row, self.config.min_displacement_atr)
            for _, row in recent.iterrows()
        )
        below_ema = float(last["close"]) < float(last["ema20"])
        held_zone = float(recent["high"].max()) <= zone.high

        reason: list[str] = []
        if displacement:
            reason.append("M5 has bearish displacement after zone interaction")
        if below_ema:
            reason.append("M5 close is below EMA20")
        if held_zone:
            reason.append("M5 has not invalidated supply zone high")

        confirmed = displacement and below_ema and held_zone
        if not confirmed:
            reason.append("M5 bearish confirmation is incomplete")
        return self._snapshot(Direction.SELL, confirmed, reason)

    def _buy_continuation(
        self,
        recent: pd.DataFrame,
        current_price: float,
        latest_atr: float,
    ) -> tuple[Zone, ConfirmationSnapshot] | None:
        last = recent.iloc[-1]
        displacement = any(
            _bullish_displacement(row, self.config.min_displacement_atr)
            for _, row in recent.tail(self.config.continuation_displacement_lookback).iterrows()
        )
        above_emas = float(last["close"]) > float(last["ema20"]) > float(last["ema50"])
        broke_minor_high = _recent_breakout(recent)
        if not (displacement and above_emas and broke_minor_high):
            return None

        pullback = recent.tail(self.config.continuation_pullback_lookback)
        pullback_low = float(pullback["low"].min())
        distance = pullback_low - current_price
        if distance < 0:
            distance = 0.0
        if distance > self.config.continuation_max_zone_distance_points:
            return None

        zone_width = latest_atr * self.config.continuation_zone_atr_width
        zone = Zone(
            symbol=self.config.symbol,
            direction=Direction.BUY,
            timeframe="M5",
            low=pullback_low - zone_width,
            high=pullback_low + max(zone_width * 0.35, 0.01),
            anchor_time=_to_datetime(pullback.iloc[pullback["low"].argmin()]["time"]),
            created_at=datetime.now(timezone.utc),
            reason=[
                "M5 bullish continuation after breakout",
                "Minor pullback/support zone created from recent M5 low",
            ],
            strength=1.0,
            setup_type="continuation",
        )
        confirmation = self._snapshot(
            Direction.BUY,
            True,
            [
                "M5 bullish continuation is active",
                "M5 close is above EMA20 and EMA50",
                "M5 recently broke minor structure upward",
            ],
        )
        return zone, confirmation

    def _sell_continuation(
        self,
        recent: pd.DataFrame,
        current_price: float,
        latest_atr: float,
    ) -> tuple[Zone, ConfirmationSnapshot] | None:
        last = recent.iloc[-1]
        displacement = any(
            _bearish_displacement(row, self.config.min_displacement_atr)
            for _, row in recent.tail(self.config.continuation_displacement_lookback).iterrows()
        )
        below_emas = float(last["close"]) < float(last["ema20"]) < float(last["ema50"])
        broke_minor_low = _recent_breakdown(recent)
        if not (displacement and below_emas and broke_minor_low):
            return None

        pullback = recent.tail(self.config.continuation_pullback_lookback)
        pullback_high = float(pullback["high"].max())
        distance = current_price - pullback_high
        if distance < 0:
            distance = pullback_high - current_price
        if distance > self.config.continuation_max_zone_distance_points:
            return None

        zone_width = latest_atr * self.config.continuation_zone_atr_width
        zone = Zone(
            symbol=self.config.symbol,
            direction=Direction.SELL,
            timeframe="M5",
            low=pullback_high - max(zone_width * 0.35, 0.01),
            high=pullback_high + zone_width,
            anchor_time=_to_datetime(pullback.iloc[pullback["high"].argmax()]["time"]),
            created_at=datetime.now(timezone.utc),
            reason=[
                "M5 bearish continuation after breakdown",
                "Minor pullback/resistance zone created from recent M5 high",
            ],
            strength=1.0,
            setup_type="continuation",
        )
        confirmation = self._snapshot(
            Direction.SELL,
            True,
            [
                "M5 bearish continuation is active",
                "M5 close is below EMA20 and EMA50",
                "M5 recently broke minor structure downward",
            ],
        )
        return zone, confirmation

    def _snapshot(
        self,
        direction: Direction,
        confirmed: bool,
        reason: list[str],
    ) -> ConfirmationSnapshot:
        return ConfirmationSnapshot(
            symbol=self.config.symbol,
            timeframe="M5",
            direction=direction,
            confirmed=confirmed,
            updated_at=datetime.now(timezone.utc),
            reason=reason,
        )


def _touched_zone(df: pd.DataFrame, zone: Zone) -> bool:
    return bool(((df["low"] <= zone.high) & (df["high"] >= zone.low)).any())


def _latest_atr(frame: pd.DataFrame) -> float:
    valid_atr = frame["atr"].dropna()
    if valid_atr.empty:
        return 0.0
    return float(valid_atr.iloc[-1])


def _recent_breakout(frame: pd.DataFrame) -> bool:
    if len(frame) < 8:
        return False
    recent = frame.tail(6)
    prior = frame.iloc[:-6].tail(12)
    if prior.empty:
        return False
    return bool((recent["close"] > float(prior["high"].max())).any())


def _recent_breakdown(frame: pd.DataFrame) -> bool:
    if len(frame) < 8:
        return False
    recent = frame.tail(6)
    prior = frame.iloc[:-6].tail(12)
    if prior.empty:
        return False
    return bool((recent["close"] < float(prior["low"].min())).any())


def _bullish_displacement(row: pd.Series, multiplier: float) -> bool:
    row_atr = float(row.get("atr", 0.0))
    if pd.isna(row_atr) or row_atr <= 0:
        return False
    return float(row["close"]) > float(row["open"]) and body_size(row) >= row_atr * multiplier


def _bearish_displacement(row: pd.Series, multiplier: float) -> bool:
    row_atr = float(row.get("atr", 0.0))
    if pd.isna(row_atr) or row_atr <= 0:
        return False
    return float(row["close"]) < float(row["open"]) and body_size(row) >= row_atr * multiplier


def _to_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.to_pydatetime()

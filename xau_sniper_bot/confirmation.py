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

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .config import BotConfig
from .indicators import atr, ema
from .models import Bias, BiasSnapshot, Direction, Zone


def detect_swing_highs(df: pd.DataFrame, window: int) -> pd.Series:
    highs = df["high"]
    is_swing = pd.Series(True, index=df.index)
    for offset in range(1, window + 1):
        is_swing &= highs > highs.shift(offset)
        is_swing &= highs >= highs.shift(-offset)
    return is_swing.fillna(False)


def detect_swing_lows(df: pd.DataFrame, window: int) -> pd.Series:
    lows = df["low"]
    is_swing = pd.Series(True, index=df.index)
    for offset in range(1, window + 1):
        is_swing &= lows < lows.shift(offset)
        is_swing &= lows <= lows.shift(-offset)
    return is_swing.fillna(False)


class H1BiasEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def analyze(self, df: pd.DataFrame) -> BiasSnapshot:
        _require_bars(df, 220, "H1")
        frame = df.copy()
        frame["ema50"] = ema(frame["close"], 50)
        frame["ema200"] = ema(frame["close"], 200)

        swing_highs = frame[detect_swing_highs(frame, self.config.swing_window)]
        swing_lows = frame[detect_swing_lows(frame, self.config.swing_window)]
        last = frame.iloc[-1]
        recent_highs = swing_highs.tail(3)["high"].tolist()
        recent_lows = swing_lows.tail(3)["low"].tolist()

        higher_highs = len(recent_highs) >= 2 and recent_highs[-1] > recent_highs[-2]
        higher_lows = len(recent_lows) >= 2 and recent_lows[-1] > recent_lows[-2]
        lower_highs = len(recent_highs) >= 2 and recent_highs[-1] < recent_highs[-2]
        lower_lows = len(recent_lows) >= 2 and recent_lows[-1] < recent_lows[-2]

        bullish_ema = float(last["close"]) > float(last["ema50"]) > float(last["ema200"])
        bearish_ema = float(last["close"]) < float(last["ema50"]) < float(last["ema200"])

        reason: list[str] = []
        if bullish_ema:
            reason.append("H1 close above EMA50 and EMA200 with bullish EMA stack")
        if bearish_ema:
            reason.append("H1 close below EMA50 and EMA200 with bearish EMA stack")
        if higher_highs and higher_lows:
            reason.append("Recent H1 swings show higher high and higher low")
        if lower_highs and lower_lows:
            reason.append("Recent H1 swings show lower high and lower low")

        mode = self.config.h1_bias_mode.lower()
        if mode not in {"strict", "balanced"}:
            raise ValueError("h1_bias_mode must be either 'strict' or 'balanced'")

        if self._bullish_bias(mode, bullish_ema, higher_highs, higher_lows):
            bias = Bias.BULLISH
        elif self._bearish_bias(mode, bearish_ema, lower_highs, lower_lows):
            bias = Bias.BEARISH
        else:
            bias = Bias.NEUTRAL
            reason.append("H1 trend filters are mixed")

        return BiasSnapshot(
            symbol=self.config.symbol,
            timeframe="H1",
            bias=bias,
            updated_at=_utcnow(),
            last_close=float(last["close"]),
            reason=reason,
            swing_high=float(recent_highs[-1]) if recent_highs else None,
            swing_low=float(recent_lows[-1]) if recent_lows else None,
        )

    def _bullish_bias(
        self,
        mode: str,
        bullish_ema: bool,
        higher_highs: bool,
        higher_lows: bool,
    ) -> bool:
        if mode == "strict":
            return bullish_ema and (higher_lows or higher_highs)
        return bullish_ema or (higher_highs and higher_lows)

    def _bearish_bias(
        self,
        mode: str,
        bearish_ema: bool,
        lower_highs: bool,
        lower_lows: bool,
    ) -> bool:
        if mode == "strict":
            return bearish_ema and (lower_highs or lower_lows)
        return bearish_ema or (lower_highs and lower_lows)


class M15ZoneEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def find_zones(self, df: pd.DataFrame, bias: BiasSnapshot) -> list[Zone]:
        _require_bars(df, 80, "M15")
        if bias.bias == Bias.NEUTRAL:
            return []

        frame = df.copy()
        frame["atr"] = atr(frame, self.config.atr_period)
        zones: list[Zone] = []
        if bias.bias == Bias.BULLISH:
            zones.extend(self._find_demand_zones(frame))
        elif bias.bias == Bias.BEARISH:
            zones.extend(self._find_supply_zones(frame))

        zones.sort(key=lambda zone: zone.strength, reverse=True)
        return zones[:3]

    def nearest_target(
        self,
        m15: pd.DataFrame,
        h1: pd.DataFrame,
        direction: Direction,
        entry_price: float,
    ) -> float | None:
        levels: list[float] = []
        for df in (m15, h1):
            highs = df[detect_swing_highs(df, self.config.swing_window)]["high"].tail(12)
            lows = df[detect_swing_lows(df, self.config.swing_window)]["low"].tail(12)
            if direction == Direction.BUY:
                levels.extend(float(level) for level in highs if float(level) > entry_price)
            else:
                levels.extend(float(level) for level in lows if float(level) < entry_price)

        if not levels:
            return None
        return min(levels) if direction == Direction.BUY else max(levels)

    def _find_demand_zones(self, frame: pd.DataFrame) -> list[Zone]:
        zones: list[Zone] = []
        recent = frame.tail(self.config.zone_max_age_bars)
        swing_lows = recent[detect_swing_lows(recent, self.config.swing_window)]

        for index, row in swing_lows.tail(8).iterrows():
            after = recent.loc[index:].head(8)
            if after.empty:
                continue
            local_high = float(recent.loc[:index].tail(12)["high"].max())
            displaced = after["close"].max() > local_high
            bullish_push = float(after.iloc[-1]["close"]) > float(row["close"])
            if not (displaced or bullish_push):
                continue

            padding = _safe_atr(row) * self.config.zone_atr_padding
            zone = Zone(
                symbol=self.config.symbol,
                direction=Direction.BUY,
                timeframe="M15",
                low=float(row["low"]) - padding,
                high=min(float(row["open"]), float(row["close"])) + padding,
                anchor_time=_to_datetime(row["time"]),
                created_at=_utcnow(),
                reason=["M15 demand/support formed from swing low and bullish reaction"],
                strength=_zone_strength(row, after),
            )
            zones.append(zone)
        return zones

    def _find_supply_zones(self, frame: pd.DataFrame) -> list[Zone]:
        zones: list[Zone] = []
        recent = frame.tail(self.config.zone_max_age_bars)
        swing_highs = recent[detect_swing_highs(recent, self.config.swing_window)]

        for index, row in swing_highs.tail(8).iterrows():
            after = recent.loc[index:].head(8)
            if after.empty:
                continue
            local_low = float(recent.loc[:index].tail(12)["low"].min())
            displaced = after["close"].min() < local_low
            bearish_push = float(after.iloc[-1]["close"]) < float(row["close"])
            if not (displaced or bearish_push):
                continue

            padding = _safe_atr(row) * self.config.zone_atr_padding
            zone = Zone(
                symbol=self.config.symbol,
                direction=Direction.SELL,
                timeframe="M15",
                low=max(float(row["open"]), float(row["close"])) - padding,
                high=float(row["high"]) + padding,
                anchor_time=_to_datetime(row["time"]),
                created_at=_utcnow(),
                reason=["M15 supply/resistance formed from swing high and bearish reaction"],
                strength=_zone_strength(row, after),
            )
            zones.append(zone)
        return zones


def _zone_strength(row: pd.Series, after: pd.DataFrame) -> float:
    if after.empty:
        return 0.0
    move = abs(float(after["close"].iloc[-1]) - float(row["close"]))
    base = max(abs(float(row["high"]) - float(row["low"])), 0.0001)
    return move / base


def _safe_atr(row: pd.Series) -> float:
    value = row.get("atr", 0.0)
    if pd.isna(value):
        return 0.0
    return float(value)


def _require_bars(df: pd.DataFrame, minimum: int, timeframe: str) -> None:
    if len(df) < minimum:
        raise ValueError(f"Need at least {minimum} {timeframe} bars, got {len(df)}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_datetime(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.to_pydatetime()

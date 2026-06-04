from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

import pandas as pd

from .config import BotConfig
from .indicators import ema, macd, rsi, sma
from .models import Bias, BiasSnapshot, Direction
from .structure import detect_swing_highs, detect_swing_lows


ANALYSIS_TIMEFRAMES = ("W1", "D1", "H4", "H1", "M15")
TIMEFRAME_WEIGHTS = {
    "W1": 3.0,
    "D1": 2.0,
    "H4": 1.5,
    "H1": 1.0,
    "M15": 0.5,
}
LEVEL_TIMEFRAME_WEIGHTS = {
    "W1": 35,
    "D1": 25,
    "H4": 18,
    "H1": 12,
    "M15": 8,
}


@dataclass(frozen=True)
class TimeframeAnalysis:
    timeframe: str
    last_close: float
    trend: str
    structure_score: float
    bos: str
    choch: str
    ma50: float | None
    ma200: float | None
    price_vs_ma: str
    ma_cross: str
    ma50_slope: str
    ma200_slope: str
    ma_score: float
    rsi_value: float | None
    rsi_signal: float | None
    rsi_score: float
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    macd_score: float
    raw_score: float
    weighted_score: float
    bias: str
    reasons: list[str]

    @property
    def direction(self) -> str | None:
        return _direction_from_bias(self.bias)


@dataclass(frozen=True)
class LevelAnalysis:
    price: float
    label: str
    side: str
    timeframe: str
    confidence: float
    touches: int
    recency_bars: int


@dataclass(frozen=True)
class DxyAnalysis:
    enabled: bool
    required: bool
    available: bool
    symbol: str
    pressure: str
    score: float
    correlation: float | None
    confirms: bool
    reasons: list[str]
    timeframe_reports: dict[str, TimeframeAnalysis]


@dataclass(frozen=True)
class SetupPlan:
    direction: str
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    target_3: float
    rr1: float
    rr2: float
    rr3: float
    reasons: list[str]


@dataclass(frozen=True)
class FrameworkAnalysis:
    symbol: str
    analyzed_at: datetime
    current_price: float
    bias_score: float
    bias: str
    direction: str | None
    tradeable: bool
    confidence: float
    confirmations: int
    total_checks: int
    hard_blocks: list[str]
    reasons: list[str]
    timeframe_reports: dict[str, TimeframeAnalysis]
    dxy: DxyAnalysis
    support_levels: list[LevelAnalysis]
    resistance_levels: list[LevelAnalysis]
    ma_stack: list[LevelAnalysis]
    setup: SetupPlan | None

    @property
    def blocked(self) -> bool:
        return bool(self.hard_blocks)

    def allows_direction(self, direction: Direction) -> bool:
        expected = "LONG" if direction == Direction.BUY else "SHORT"
        return self.tradeable and self.direction == expected

    def to_bias_snapshot(self) -> BiasSnapshot:
        if self.direction == "LONG" and not self.blocked:
            bias = Bias.BULLISH
        elif self.direction == "SHORT" and not self.blocked:
            bias = Bias.BEARISH
        else:
            bias = Bias.NEUTRAL

        reasons = [
            f"Framework bias {self.bias} score {self.bias_score:.1f}",
            f"Confidence {self.confidence:.0f}%",
        ]
        reasons.extend(self.reasons[:5])
        reasons.extend(self.hard_blocks[:3])
        return BiasSnapshot(
            symbol=self.symbol,
            timeframe="W1-D1-H4-H1-M15",
            bias=bias,
            updated_at=self.analyzed_at,
            last_close=self.current_price,
            reason=reasons,
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


class AnalysisFrameworkEngine:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def analyze(
        self,
        gold_frames: dict[str, pd.DataFrame],
        *,
        dxy_frames: dict[str, pd.DataFrame] | None = None,
        dxy_error: str | None = None,
        now: datetime | None = None,
    ) -> FrameworkAnalysis:
        analyzed_at = _utcnow() if now is None else now.astimezone(timezone.utc)
        timeframe_reports = {
            timeframe: self._analyze_timeframe(timeframe, frame)
            for timeframe, frame in gold_frames.items()
            if timeframe in ANALYSIS_TIMEFRAMES and _usable_frame(frame)
        }
        if not timeframe_reports:
            raise ValueError("No usable gold frames were provided for framework analysis")

        current_price = _current_price(gold_frames, timeframe_reports)
        support_levels, resistance_levels = self._support_resistance_levels(
            gold_frames,
            timeframe_reports,
            current_price,
        )
        ma_stack = self._ma_stack(timeframe_reports, current_price)
        sr_score = self._sr_position_score(support_levels, resistance_levels, current_price)

        weighted_total = sum(report.weighted_score for report in timeframe_reports.values())
        pre_dxy_score = weighted_total + sr_score
        pre_dxy_bias = _bias_label(pre_dxy_score)
        pre_dxy_direction = _direction_from_bias(pre_dxy_bias)

        dxy = self._dxy_analysis(
            gold_frames,
            dxy_frames or {},
            pre_dxy_direction,
            dxy_error,
        )
        final_score = pre_dxy_score + dxy.score
        final_bias = _bias_label(final_score)
        final_direction = _direction_from_bias(final_bias)

        hard_blocks = self._hard_blocks(
            timeframe_reports,
            dxy,
            final_direction,
            analyzed_at,
        )
        hard_blocks.extend(self._weekly_override_blocks(timeframe_reports, final_direction))

        confirmations = self._confirmation_count(
            timeframe_reports,
            dxy,
            support_levels,
            resistance_levels,
            ma_stack,
            final_direction,
        )
        total_checks = 8
        confidence = _calculate_probability(confirmations, total_checks)
        setup = self._setup_plan(
            final_bias,
            final_direction,
            current_price,
            support_levels,
            resistance_levels,
            ma_stack,
        )
        tradeable = (
            final_direction is not None
            and _moderate_or_strong(final_bias)
            and not hard_blocks
            and setup is not None
        )

        reasons = self._summary_reasons(
            timeframe_reports,
            dxy,
            sr_score,
            final_bias,
            final_score,
        )
        return FrameworkAnalysis(
            symbol=self.config.symbol,
            analyzed_at=analyzed_at,
            current_price=current_price,
            bias_score=final_score,
            bias=final_bias,
            direction=final_direction,
            tradeable=tradeable,
            confidence=confidence,
            confirmations=confirmations,
            total_checks=total_checks,
            hard_blocks=hard_blocks,
            reasons=reasons,
            timeframe_reports=timeframe_reports,
            dxy=dxy,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            ma_stack=ma_stack,
            setup=setup,
        )

    def _analyze_timeframe(self, timeframe: str, df: pd.DataFrame) -> TimeframeAnalysis:
        frame = df.copy().reset_index(drop=True)
        ma50 = _moving_average(frame["close"], 50, self.config.analysis_ma_type)
        ma200 = _moving_average(frame["close"], 200, self.config.analysis_ma_type)
        rsi_values = rsi(frame["close"], 14)
        rsi_signal = ema(rsi_values, 9)
        macd_line, macd_signal, macd_histogram = macd(frame["close"], 12, 26, 9)

        close = float(frame.iloc[-1]["close"])
        latest_ma50 = _latest_float(ma50)
        latest_ma200 = _latest_float(ma200)
        price_vs_ma = _price_vs_ma(close, latest_ma50, latest_ma200)
        ma_cross = _ma_cross(ma50, ma200)
        ma50_slope = _slope(ma50)
        ma200_slope = _slope(ma200)
        ma_score = _ma_score(price_vs_ma, ma_cross, ma50_slope, ma200_slope)

        trend, structure_score, bos, choch, structure_reasons = self._structure(frame)
        rsi_score, rsi_reasons = _rsi_score(rsi_values, rsi_signal)
        macd_score, macd_reasons = _macd_score(macd_line, macd_signal, macd_histogram)

        raw_score = structure_score + ma_score + rsi_score + macd_score
        weighted_score = raw_score * TIMEFRAME_WEIGHTS.get(timeframe, 1.0)
        reasons = []
        reasons.extend(structure_reasons)
        reasons.extend(_ma_reasons(price_vs_ma, ma_cross, ma50_slope, ma200_slope))
        reasons.extend(rsi_reasons)
        reasons.extend(macd_reasons)

        return TimeframeAnalysis(
            timeframe=timeframe,
            last_close=close,
            trend=trend,
            structure_score=structure_score,
            bos=bos,
            choch=choch,
            ma50=latest_ma50,
            ma200=latest_ma200,
            price_vs_ma=price_vs_ma,
            ma_cross=ma_cross,
            ma50_slope=ma50_slope,
            ma200_slope=ma200_slope,
            ma_score=ma_score,
            rsi_value=_latest_float(rsi_values),
            rsi_signal=_latest_float(rsi_signal),
            rsi_score=rsi_score,
            macd_line=_latest_float(macd_line),
            macd_signal=_latest_float(macd_signal),
            macd_histogram=_latest_float(macd_histogram),
            macd_score=macd_score,
            raw_score=raw_score,
            weighted_score=weighted_score,
            bias=_bias_label(raw_score),
            reasons=reasons[:8],
        )

    def _structure(self, frame: pd.DataFrame) -> tuple[str, float, str, str, list[str]]:
        window = max(1, min(self.config.analysis_swing_window, max((len(frame) - 1) // 2, 1)))
        swing_highs = frame[detect_swing_highs(frame, window)]
        swing_lows = frame[detect_swing_lows(frame, window)]
        high_values = swing_highs.tail(3)["high"].tolist()
        low_values = swing_lows.tail(3)["low"].tolist()
        last_close = float(frame.iloc[-1]["close"])

        higher_highs = len(high_values) >= 2 and high_values[-1] > high_values[-2]
        higher_lows = len(low_values) >= 2 and low_values[-1] > low_values[-2]
        lower_highs = len(high_values) >= 2 and high_values[-1] < high_values[-2]
        lower_lows = len(low_values) >= 2 and low_values[-1] < low_values[-2]

        if higher_highs and higher_lows:
            trend = "BULLISH"
            score = 2.0
            reasons = ["Swing structure is HH/HL"]
        elif lower_highs and lower_lows:
            trend = "BEARISH"
            score = -2.0
            reasons = ["Swing structure is LH/LL"]
        else:
            trend = "RANGING"
            score = 0.0
            reasons = ["Swing structure is mixed/ranging"]

        bos = "NO_BOS"
        choch = "NO_CHOCH"
        previous_high = high_values[-2] if len(high_values) >= 2 else (high_values[-1] if high_values else None)
        previous_low = low_values[-2] if len(low_values) >= 2 else (low_values[-1] if low_values else None)
        if previous_high is not None and last_close > float(previous_high):
            bos = "BULLISH_BOS"
            score += 1.0
            reasons.append("Close broke above previous swing high")
            if trend == "BEARISH":
                choch = "BULLISH_CHOCH"
        if previous_low is not None and last_close < float(previous_low):
            bos = "BEARISH_BOS"
            score -= 1.0
            reasons.append("Close broke below previous swing low")
            if trend == "BULLISH":
                choch = "BEARISH_CHOCH"

        return trend, _clamp(score, -3.0, 3.0), bos, choch, reasons

    def _support_resistance_levels(
        self,
        frames: dict[str, pd.DataFrame],
        reports: dict[str, TimeframeAnalysis],
        current_price: float,
    ) -> tuple[list[LevelAnalysis], list[LevelAnalysis]]:
        supports: list[LevelAnalysis] = []
        resistances: list[LevelAnalysis] = []
        tolerance = self.config.analysis_level_tolerance_points
        for timeframe, frame in frames.items():
            if timeframe not in ANALYSIS_TIMEFRAMES or not _usable_frame(frame):
                continue
            recent = frame.reset_index(drop=True)
            window = max(1, min(self.config.analysis_swing_window, max((len(recent) - 1) // 2, 1)))
            swing_highs = recent[detect_swing_highs(recent, window)].tail(8)
            swing_lows = recent[detect_swing_lows(recent, window)].tail(8)
            for index, row in swing_highs.iterrows():
                resistances.append(
                    self._level(
                        float(row["high"]),
                        f"{timeframe} swing high",
                        "resistance",
                        timeframe,
                        recent,
                        len(recent) - int(index) - 1,
                        tolerance,
                    )
                )
            for index, row in swing_lows.iterrows():
                supports.append(
                    self._level(
                        float(row["low"]),
                        f"{timeframe} swing low",
                        "support",
                        timeframe,
                        recent,
                        len(recent) - int(index) - 1,
                        tolerance,
                    )
                )

            supports.extend(self._previous_period_levels(recent, timeframe, "support", tolerance))
            resistances.extend(
                self._previous_period_levels(recent, timeframe, "resistance", tolerance)
            )
            support_fvgs, resistance_fvgs = self._fair_value_gap_levels(
                recent,
                timeframe,
                current_price,
                tolerance,
            )
            supports.extend(support_fvgs)
            resistances.extend(resistance_fvgs)

        for report in reports.values():
            for label, price in (("MA50", report.ma50), ("MA200", report.ma200)):
                if price is None:
                    continue
                side = "support" if price <= current_price else "resistance"
                level = LevelAnalysis(
                    price=price,
                    label=f"{report.timeframe} {label} dynamic {side}",
                    side=side,
                    timeframe=report.timeframe,
                    confidence=LEVEL_TIMEFRAME_WEIGHTS.get(report.timeframe, 8),
                    touches=0,
                    recency_bars=0,
                )
                if side == "support":
                    supports.append(level)
                else:
                    resistances.append(level)

        psych_supports, psych_resistances = self._psych_levels(current_price)
        supports.extend(psych_supports)
        resistances.extend(psych_resistances)

        supports = _dedupe_levels([level for level in supports if level.price <= current_price])
        resistances = _dedupe_levels(
            [level for level in resistances if level.price >= current_price]
        )
        supports.sort(key=lambda level: (-level.confidence, abs(current_price - level.price)))
        resistances.sort(key=lambda level: (-level.confidence, abs(level.price - current_price)))
        return supports[:10], resistances[:10]

    def _psych_levels(self, current_price: float) -> tuple[list[LevelAnalysis], list[LevelAnalysis]]:
        supports: list[LevelAnalysis] = []
        resistances: list[LevelAnalysis] = []
        anchor = int(current_price // 100) * 100
        for offset in range(-5, 6):
            price = float(anchor + offset * 100)
            if price <= 0:
                continue
            major = int(price) % 500 == 0
            side = "support" if price <= current_price else "resistance"
            level = LevelAnalysis(
                price=price,
                label=("major" if major else "minor") + " psychological round number",
                side=side,
                timeframe="PSYCH",
                confidence=30.0 if major else 18.0,
                touches=0,
                recency_bars=0,
            )
            if side == "support":
                supports.append(level)
            else:
                resistances.append(level)
        return supports, resistances

    def _level(
        self,
        price: float,
        label: str,
        side: str,
        timeframe: str,
        frame: pd.DataFrame,
        recency_bars: int,
        tolerance: float,
    ) -> LevelAnalysis:
        touches = _touches(frame, price, tolerance)
        confidence = _level_confidence(touches, timeframe, recency_bars)
        return LevelAnalysis(
            price=price,
            label=label,
            side=side,
            timeframe=timeframe,
            confidence=confidence,
            touches=touches,
            recency_bars=recency_bars,
        )

    def _previous_period_levels(
        self,
        frame: pd.DataFrame,
        timeframe: str,
        side: str,
        tolerance: float,
    ) -> list[LevelAnalysis]:
        if timeframe not in {"D1", "W1"} or len(frame) < 2:
            return []
        previous = frame.iloc[-2]
        label_prefix = "previous day" if timeframe == "D1" else "previous week"
        column = "low" if side == "support" else "high"
        price = float(previous[column])
        return [
            self._level(
                price,
                f"{label_prefix} {column}",
                side,
                timeframe,
                frame,
                1,
                tolerance,
            )
        ]

    def _fair_value_gap_levels(
        self,
        frame: pd.DataFrame,
        timeframe: str,
        current_price: float,
        tolerance: float,
    ) -> tuple[list[LevelAnalysis], list[LevelAnalysis]]:
        supports: list[LevelAnalysis] = []
        resistances: list[LevelAnalysis] = []
        recent = frame.tail(80).reset_index(drop=True)
        for index in range(2, len(recent)):
            first = recent.iloc[index - 2]
            third = recent.iloc[index]
            if float(first["high"]) < float(third["low"]):
                price = (float(first["high"]) + float(third["low"])) / 2.0
                level = self._level(
                    price,
                    f"{timeframe} bullish FVG midpoint",
                    "support" if price <= current_price else "resistance",
                    timeframe,
                    frame,
                    len(recent) - index - 1,
                    tolerance,
                )
                if price <= current_price:
                    supports.append(level)
                else:
                    resistances.append(level)
            if float(first["low"]) > float(third["high"]):
                price = (float(first["low"]) + float(third["high"])) / 2.0
                level = self._level(
                    price,
                    f"{timeframe} bearish FVG midpoint",
                    "support" if price <= current_price else "resistance",
                    timeframe,
                    frame,
                    len(recent) - index - 1,
                    tolerance,
                )
                if price <= current_price:
                    supports.append(level)
                else:
                    resistances.append(level)
        return supports[-5:], resistances[-5:]

    def _ma_stack(
        self,
        reports: dict[str, TimeframeAnalysis],
        current_price: float,
    ) -> list[LevelAnalysis]:
        levels: list[LevelAnalysis] = []
        for report in reports.values():
            for label, price in (("MA50", report.ma50), ("MA200", report.ma200)):
                if price is None:
                    continue
                side = "support" if price <= current_price else "resistance"
                levels.append(
                    LevelAnalysis(
                        price=price,
                        label=f"{report.timeframe} {label}",
                        side=side,
                        timeframe=report.timeframe,
                        confidence=LEVEL_TIMEFRAME_WEIGHTS.get(report.timeframe, 8),
                        touches=0,
                        recency_bars=0,
                    )
                )
        levels.sort(key=lambda level: abs(level.price - current_price))
        return _dedupe_levels(levels)[:12]

    def _sr_position_score(
        self,
        supports: list[LevelAnalysis],
        resistances: list[LevelAnalysis],
        current_price: float,
    ) -> float:
        nearest_support = min(
            supports,
            key=lambda level: current_price - level.price,
            default=None,
        )
        nearest_resistance = min(
            resistances,
            key=lambda level: level.price - current_price,
            default=None,
        )
        near_threshold = max(self.config.analysis_level_tolerance_points * 2.0, 5.0)
        score = 0.0
        if nearest_support is not None:
            support_distance = current_price - nearest_support.price
            if support_distance <= near_threshold:
                score += 1.0
        if nearest_resistance is not None:
            resistance_distance = nearest_resistance.price - current_price
            if resistance_distance <= near_threshold:
                score -= 1.0
        return _clamp(score, -2.0, 2.0)

    def _dxy_analysis(
        self,
        gold_frames: dict[str, pd.DataFrame],
        dxy_frames: dict[str, pd.DataFrame],
        final_direction: str | None,
        dxy_error: str | None,
    ) -> DxyAnalysis:
        enabled = self.config.dxy_enabled
        required = self.config.dxy_confirmation_required
        if not enabled:
            return DxyAnalysis(
                enabled=False,
                required=required,
                available=False,
                symbol=self.config.dxy_symbol,
                pressure="DISABLED",
                score=0.0,
                correlation=None,
                confirms=not required,
                reasons=["DXY layer disabled in config"],
                timeframe_reports={},
            )

        reports = {
            timeframe: self._analyze_timeframe(timeframe, frame)
            for timeframe, frame in dxy_frames.items()
            if timeframe in ANALYSIS_TIMEFRAMES and _usable_frame(frame)
        }
        if not reports:
            reason = dxy_error or "DXY frames are unavailable"
            return DxyAnalysis(
                enabled=True,
                required=required,
                available=False,
                symbol=self.config.dxy_symbol,
                pressure="UNAVAILABLE",
                score=0.0,
                correlation=None,
                confirms=not required,
                reasons=[reason],
                timeframe_reports={},
            )

        dxy_weighted = sum(report.weighted_score for report in reports.values())
        if dxy_weighted > 8:
            pressure = "STRONG_GOLD_BEARISH"
            score = -2.0
        elif dxy_weighted > 4:
            pressure = "MODERATE_GOLD_BEARISH"
            score = -1.0
        elif dxy_weighted < -8:
            pressure = "STRONG_GOLD_BULLISH"
            score = 2.0
        elif dxy_weighted < -4:
            pressure = "MODERATE_GOLD_BULLISH"
            score = 1.0
        else:
            pressure = "NEUTRAL"
            score = 0.0

        correlation = _correlation(gold_frames, dxy_frames)
        confirms = _dxy_confirms(score, final_direction, required)
        reasons = [f"DXY weighted score {dxy_weighted:.1f} implies {pressure}"]
        if correlation is not None:
            reasons.append(f"XAU/DXY return correlation {correlation:.2f}")
        if not confirms and required and final_direction is not None:
            reasons.append("DXY confirmation does not align with final gold direction")

        return DxyAnalysis(
            enabled=True,
            required=required,
            available=True,
            symbol=self.config.dxy_symbol,
            pressure=pressure,
            score=score,
            correlation=correlation,
            confirms=confirms,
            reasons=reasons,
            timeframe_reports=reports,
        )

    def _hard_blocks(
        self,
        reports: dict[str, TimeframeAnalysis],
        dxy: DxyAnalysis,
        final_direction: str | None,
        now: datetime,
    ) -> list[str]:
        blocks: list[str] = []
        sandwich_timeframes = [
            timeframe
            for timeframe in self.config.analysis_ma_sandwich_timeframes
            if timeframe in reports and reports[timeframe].price_vs_ma.startswith("SANDWICHED")
        ]
        if sandwich_timeframes:
            blocks.append(
                "MA sandwich zone active on "
                + ", ".join(sandwich_timeframes)
                + "; framework rule blocks entries"
            )

        if self._in_thin_liquidity(now):
            blocks.append("Asian thin-liquidity window 00:00-06:00 UTC blocks entries")

        news_reason = self._news_window_reason(now)
        if news_reason:
            blocks.append(news_reason)

        if (
            self.config.dxy_enabled
            and self.config.dxy_confirmation_required
            and final_direction is not None
            and not dxy.confirms
        ):
            blocks.append("DXY confirmation is required and not aligned")
        return blocks

    def _weekly_override_blocks(
        self,
        reports: dict[str, TimeframeAnalysis],
        final_direction: str | None,
    ) -> list[str]:
        weekly = reports.get("W1")
        if weekly is None or weekly.direction is None or final_direction is None:
            return []
        if weekly.direction != final_direction and abs(weekly.raw_score) >= 4:
            return [
                (
                    "Weekly bias overrides lower timeframes: "
                    f"W1 is {weekly.bias}, final lower-timeframe direction is {final_direction}"
                )
            ]
        return []

    def _confirmation_count(
        self,
        reports: dict[str, TimeframeAnalysis],
        dxy: DxyAnalysis,
        supports: list[LevelAnalysis],
        resistances: list[LevelAnalysis],
        ma_stack: list[LevelAnalysis],
        direction: str | None,
    ) -> int:
        if direction is None:
            return 0
        checks = [
            reports.get("W1") is not None and reports["W1"].direction == direction,
            reports.get("D1") is not None and reports["D1"].direction == direction,
            reports.get("H4") is not None and reports["H4"].direction == direction,
            reports.get("H1") is not None and reports["H1"].direction == direction,
            reports.get("M15") is not None and reports["M15"].direction == direction,
            dxy.confirms,
            bool(supports if direction == "LONG" else resistances),
            bool(ma_stack),
        ]
        return sum(1 for check in checks if check)

    def _setup_plan(
        self,
        bias: str,
        direction: str | None,
        current_price: float,
        supports: list[LevelAnalysis],
        resistances: list[LevelAnalysis],
        ma_stack: list[LevelAnalysis],
    ) -> SetupPlan | None:
        if direction is None or not _moderate_or_strong(bias):
            return None

        support_candidates = [level for level in supports + ma_stack if level.price < current_price]
        resistance_candidates = [
            level for level in resistances + ma_stack if level.price > current_price
        ]
        support_candidates = _dedupe_levels(support_candidates)
        resistance_candidates = _dedupe_levels(resistance_candidates)

        if direction == "LONG":
            support_candidates.sort(key=lambda level: current_price - level.price)
            resistance_candidates.sort(key=lambda level: level.price - current_price)
            entry_level = support_candidates[0] if support_candidates else None
            entry = entry_level.price if entry_level else current_price
            stop = entry - (entry * 0.0015)
            risk = entry - stop
            targets = [level.price for level in resistance_candidates[:3]]
            targets = _pad_targets(targets, entry, risk, Direction.BUY)
            reasons = [
                "Long plan uses nearest support/MA stack as entry zone",
                entry_level.label if entry_level else "No nearby support found; current price used",
            ]
        else:
            resistance_candidates.sort(key=lambda level: level.price - current_price)
            support_candidates.sort(key=lambda level: current_price - level.price)
            entry_level = resistance_candidates[0] if resistance_candidates else None
            entry = entry_level.price if entry_level else current_price
            stop = entry + (entry * 0.0015)
            risk = stop - entry
            targets = [level.price for level in support_candidates[:3]]
            targets = _pad_targets(targets, entry, risk, Direction.SELL)
            reasons = [
                "Short plan uses nearest resistance/MA stack as entry zone",
                entry_level.label if entry_level else "No nearby resistance found; current price used",
            ]

        rr1 = _setup_rr(direction, entry, stop, targets[0])
        rr2 = _setup_rr(direction, entry, stop, targets[1])
        rr3 = _setup_rr(direction, entry, stop, targets[2])
        return SetupPlan(
            direction=direction,
            entry=entry,
            stop_loss=stop,
            target_1=targets[0],
            target_2=targets[1],
            target_3=targets[2],
            rr1=rr1,
            rr2=rr2,
            rr3=rr3,
            reasons=reasons,
        )

    def _summary_reasons(
        self,
        reports: dict[str, TimeframeAnalysis],
        dxy: DxyAnalysis,
        sr_score: float,
        final_bias: str,
        final_score: float,
    ) -> list[str]:
        reasons = [f"Final framework bias is {final_bias} ({final_score:.1f})"]
        for timeframe in ANALYSIS_TIMEFRAMES:
            report = reports.get(timeframe)
            if report is None:
                continue
            reasons.append(
                f"{timeframe}: {report.bias} trend={report.trend} "
                f"MA={report.price_vs_ma} RSI={_fmt(report.rsi_value)} "
                f"MACD={_fmt(report.macd_histogram)}"
            )
        reasons.append(f"S/R position score {sr_score:.1f}")
        reasons.extend(dxy.reasons[:3])
        return reasons

    def _in_thin_liquidity(self, now: datetime) -> bool:
        if not self.config.asian_thin_liquidity_filter_enabled:
            return False
        hour = now.astimezone(timezone.utc).hour
        start = self.config.asian_thin_liquidity_start_hour_utc
        end = self.config.asian_thin_liquidity_end_hour_utc
        return _hour_in_window(hour, start, end)

    def _news_window_reason(self, now: datetime) -> str | None:
        if not self.config.high_impact_news_filter_enabled:
            return None
        for window in self.config.high_impact_news_windows_utc:
            start = _parse_datetime(window.get("start"))
            end = _parse_datetime(window.get("end"))
            if start is None or end is None:
                continue
            if start <= now.astimezone(timezone.utc) <= end:
                label = window.get("label") or window.get("name") or "high-impact news"
                return f"{label} news window blocks entries"
        return None


def _moving_average(series: pd.Series, period: int, ma_type: str) -> pd.Series:
    if ma_type.lower() == "sma":
        return sma(series, period)
    if ma_type.lower() != "ema":
        raise ValueError("analysis_ma_type must be 'ema' or 'sma'")
    return ema(series, period)


def _usable_frame(frame: pd.DataFrame) -> bool:
    required = {"time", "open", "high", "low", "close"}
    return len(frame) >= 60 and required.issubset(set(frame.columns))


def _current_price(
    frames: dict[str, pd.DataFrame],
    reports: dict[str, TimeframeAnalysis],
) -> float:
    for timeframe in ("M15", "H1", "H4", "D1", "W1"):
        frame = frames.get(timeframe)
        if frame is not None and not frame.empty:
            return float(frame.iloc[-1]["close"])
        report = reports.get(timeframe)
        if report is not None:
            return report.last_close
    return next(iter(reports.values())).last_close


def _latest_float(series: pd.Series) -> float | None:
    if series.empty:
        return None
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    value = float(value)
    return value if isfinite(value) else None


def _price_vs_ma(price: float, ma50: float | None, ma200: float | None) -> str:
    if ma50 is None or ma200 is None:
        return "UNKNOWN"
    if price > ma50 and price > ma200:
        return "FULLY_BULLISH"
    if price < ma50 and price < ma200:
        return "FULLY_BEARISH"
    if ma200 < price < ma50:
        return "SANDWICHED_BEARISH"
    if ma50 < price < ma200:
        return "SANDWICHED_BULLISH"
    return "SANDWICHED_NEUTRAL"


def _ma_cross(ma_fast: pd.Series, ma_slow: pd.Series) -> str:
    if len(ma_fast) < 2 or len(ma_slow) < 2:
        return "NO_CROSS"
    fast_now = ma_fast.iloc[-1]
    slow_now = ma_slow.iloc[-1]
    fast_prev = ma_fast.iloc[-2]
    slow_prev = ma_slow.iloc[-2]
    if any(pd.isna(value) for value in (fast_now, slow_now, fast_prev, slow_prev)):
        return "NO_CROSS"
    if fast_now > slow_now and fast_prev <= slow_prev:
        return "GOLDEN_CROSS"
    if fast_now < slow_now and fast_prev >= slow_prev:
        return "DEATH_CROSS"
    return "NO_CROSS"


def _slope(series: pd.Series, lookback: int = 5) -> str:
    valid = series.dropna()
    if len(valid) <= lookback:
        return "unknown"
    latest = float(valid.iloc[-1])
    previous = float(valid.iloc[-lookback - 1])
    tolerance = max(abs(latest) * 0.0001, 0.01)
    if latest - previous > tolerance:
        return "rising"
    if previous - latest > tolerance:
        return "falling"
    return "flat"


def _ma_score(
    price_vs_ma: str,
    cross: str,
    ma50_slope: str,
    ma200_slope: str,
) -> float:
    score = 0.0
    if price_vs_ma == "FULLY_BULLISH":
        score += 2.0
    elif price_vs_ma == "FULLY_BEARISH":
        score -= 2.0
    elif price_vs_ma.startswith("SANDWICHED"):
        score += 0.0

    if cross == "GOLDEN_CROSS":
        score += 1.0
    elif cross == "DEATH_CROSS":
        score -= 1.0

    if ma50_slope == "rising" and ma200_slope in {"rising", "flat"}:
        score += 0.5
    elif ma50_slope == "falling" and ma200_slope in {"falling", "flat"}:
        score -= 0.5
    return _clamp(score, -3.0, 3.0)


def _ma_reasons(price_vs_ma: str, cross: str, ma50_slope: str, ma200_slope: str) -> list[str]:
    reasons = [f"Price/MA state: {price_vs_ma}"]
    if cross != "NO_CROSS":
        reasons.append(f"MA cross detected: {cross}")
    reasons.append(f"MA slopes: MA50 {ma50_slope}, MA200 {ma200_slope}")
    return reasons


def _rsi_score(rsi_values: pd.Series, signal: pd.Series) -> tuple[float, list[str]]:
    if len(rsi_values) < 2 or len(signal) < 2:
        return 0.0, ["RSI unavailable"]
    value = float(rsi_values.iloc[-1])
    previous = float(rsi_values.iloc[-2])
    signal_now = float(signal.iloc[-1])
    signal_prev = float(signal.iloc[-2])
    rising = value > previous
    falling = value < previous
    crossed_above = value > signal_now and previous <= signal_prev
    crossed_below = value < signal_now and previous >= signal_prev

    if value < 40 and falling:
        score = -3.0
        reason = "RSI below 40 and falling"
    elif value > 50 and rising:
        score = 2.0
        reason = "RSI above 50 and rising"
    elif value < 50 and falling:
        score = -2.0
        reason = "RSI below 50 and falling"
    elif crossed_above:
        score = 1.0
        reason = "RSI crossed above signal"
    elif crossed_below:
        score = -1.0
        reason = "RSI crossed below signal"
    else:
        score = 0.0
        reason = "RSI neutral/flat"

    reasons = [reason]
    if value > 70:
        reasons.append("RSI overbought; watch reversal risk")
    elif value < 30:
        reasons.append("RSI oversold; watch bounce risk")
    return score, reasons


def _macd_score(
    line: pd.Series,
    signal: pd.Series,
    histogram: pd.Series,
) -> tuple[float, list[str]]:
    if len(line) < 2 or len(signal) < 2 or len(histogram) < 2:
        return 0.0, ["MACD unavailable"]
    line_now = float(line.iloc[-1])
    line_prev = float(line.iloc[-2])
    signal_now = float(signal.iloc[-1])
    signal_prev = float(signal.iloc[-2])
    hist_now = float(histogram.iloc[-1])
    hist_prev = float(histogram.iloc[-2])
    crossed_above = line_now > signal_now and line_prev <= signal_prev
    crossed_below = line_now < signal_now and line_prev >= signal_prev

    if hist_now < 0 and hist_now < hist_prev:
        return -3.0, ["MACD histogram expanding negative"]
    if line_now > 0 and line_now > signal_now:
        return 2.0, ["MACD line above zero and signal"]
    if line_now < 0 and line_now < signal_now:
        return -2.0, ["MACD line below zero and signal"]
    if crossed_above:
        return 1.0, ["MACD bullish crossover"]
    if crossed_below:
        return -1.0, ["MACD bearish crossover"]
    if abs(line_now) <= 0.05:
        return 0.0, ["MACD near zero"]
    return 0.0, ["MACD neutral"]


def _bias_label(score: float) -> str:
    if score > 8:
        return "STRONG BULLISH"
    if score > 4:
        return "MODERATE BULLISH"
    if score > 0:
        return "MILD BULLISH"
    if score == 0:
        return "NEUTRAL"
    if score > -4:
        return "MILD BEARISH"
    if score > -8:
        return "MODERATE BEARISH"
    return "STRONG BEARISH"


def _direction_from_bias(bias: str) -> str | None:
    if "BULLISH" in bias:
        return "LONG"
    if "BEARISH" in bias:
        return "SHORT"
    return None


def _moderate_or_strong(bias: str) -> bool:
    return bias.startswith("MODERATE") or bias.startswith("STRONG")


def _calculate_probability(confirmations: int, total_checks: int) -> float:
    _ = total_checks
    base = 50.0
    score = base + confirmations * 5.0
    return _clamp(score, 30.0, 85.0)


def _level_confidence(touches: int, timeframe: str, recency_bars: int) -> float:
    score = touches * 15.0
    score += LEVEL_TIMEFRAME_WEIGHTS.get(timeframe, 8)
    if recency_bars <= 10:
        score += 20.0
    elif recency_bars <= 40:
        score += 10.0
    score -= min(recency_bars / 8.0, 20.0)
    return _clamp(score, 0.0, 100.0)


def _touches(frame: pd.DataFrame, price: float, tolerance: float) -> int:
    return int(((frame["low"] - tolerance <= price) & (frame["high"] + tolerance >= price)).sum())


def _dedupe_levels(levels: list[LevelAnalysis]) -> list[LevelAnalysis]:
    deduped: list[LevelAnalysis] = []
    seen: set[float] = set()
    for level in levels:
        key = round(level.price, 2)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(level)
    return deduped


def _pad_targets(
    targets: list[float],
    entry: float,
    risk: float,
    direction: Direction,
) -> list[float]:
    padded = list(targets[:3])
    while len(padded) < 3:
        multiple = 1.5 * (len(padded) + 1)
        if direction == Direction.BUY:
            padded.append(entry + risk * multiple)
        else:
            padded.append(entry - risk * multiple)
    return padded


def _setup_rr(direction: str, entry: float, stop: float, target: float) -> float:
    if direction == "LONG":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target
    if risk <= 0:
        return 0.0
    return reward / risk


def _dxy_confirms(score: float, direction: str | None, required: bool) -> bool:
    if direction is None:
        return not required
    if direction == "LONG":
        return score > 0
    if direction == "SHORT":
        return score < 0
    return not required


def _correlation(
    gold_frames: dict[str, pd.DataFrame],
    dxy_frames: dict[str, pd.DataFrame],
) -> float | None:
    for timeframe in ("H1", "H4", "D1"):
        gold = gold_frames.get(timeframe)
        dxy = dxy_frames.get(timeframe)
        if gold is None or dxy is None or len(gold) < 10 or len(dxy) < 10:
            continue
        merged = pd.merge(
            gold[["time", "close"]],
            dxy[["time", "close"]],
            on="time",
            suffixes=("_gold", "_dxy"),
        )
        if len(merged) >= 10:
            gold_returns = merged["close_gold"].pct_change().tail(80)
            dxy_returns = merged["close_dxy"].pct_change().tail(80)
        else:
            length = min(len(gold), len(dxy), 80)
            gold_returns = gold["close"].tail(length).pct_change()
            dxy_returns = dxy["close"].tail(length).pct_change()
        value = gold_returns.corr(dxy_returns)
        if pd.isna(value):
            return None
        return float(value)
    return None


def _hour_in_window(hour: int, start: int, end: int) -> bool:
    start = start % 24
    end = end % 24
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value

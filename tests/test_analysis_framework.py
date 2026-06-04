from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

import pandas as pd

from xau_sniper_bot.analysis_framework import AnalysisFrameworkEngine
from xau_sniper_bot.config import BotConfig


class AnalysisFrameworkTests(TestCase):
    def test_bullish_gold_with_bearish_dxy_is_tradeable(self) -> None:
        config = BotConfig(
            symbol="XAUUSD",
            asian_thin_liquidity_filter_enabled=False,
            high_impact_news_filter_enabled=False,
        )
        engine = AnalysisFrameworkEngine(config)
        gold = {
            "W1": _trend_frame("2021-01-01", "W", 1850.0, 1.6),
            "D1": _trend_frame("2025-01-01", "D", 1900.0, 1.2),
            "H4": _trend_frame("2026-01-01", "4h", 2000.0, 0.8),
            "H1": _trend_frame("2026-02-01", "h", 2050.0, 0.45),
            "M15": _trend_frame("2026-03-01", "15min", 2100.0, 0.18),
        }
        dxy = {
            "W1": _trend_frame("2021-01-01", "W", 110.0, -0.04),
            "D1": _trend_frame("2025-01-01", "D", 108.0, -0.03),
            "H4": _trend_frame("2026-01-01", "4h", 106.0, -0.02),
            "H1": _trend_frame("2026-02-01", "h", 105.0, -0.01),
            "M15": _trend_frame("2026-03-01", "15min", 104.0, -0.005),
        }

        analysis = engine.analyze(
            gold,
            dxy_frames=dxy,
            now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(analysis.direction, "LONG")
        self.assertEqual(analysis.bias, "STRONG BULLISH")
        self.assertTrue(analysis.dxy.confirms)
        self.assertTrue(analysis.tradeable)
        self.assertLessEqual(analysis.confidence, 85.0)
        self.assertIsNotNone(analysis.setup)
        self.assertTrue(
            any("psychological" in level.label for level in analysis.support_levels)
            or any("psychological" in level.label for level in analysis.resistance_levels)
        )

    def test_ma_sandwich_zone_blocks_entries(self) -> None:
        config = BotConfig(
            symbol="XAUUSD",
            analysis_ma_type="sma",
            analysis_ma_sandwich_timeframes=["H1"],
            dxy_enabled=False,
            asian_thin_liquidity_filter_enabled=False,
            high_impact_news_filter_enabled=False,
        )
        engine = AnalysisFrameworkEngine(config)

        analysis = engine.analyze(
            {"H1": _sandwich_frame()},
            now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(analysis.blocked)
        self.assertIn("MA sandwich zone", " ".join(analysis.hard_blocks))

    def test_news_window_blocks_entries(self) -> None:
        config = BotConfig(
            symbol="XAUUSD",
            dxy_enabled=False,
            asian_thin_liquidity_filter_enabled=False,
            high_impact_news_windows_utc=[
                {
                    "label": "NFP",
                    "start": "2026-01-01T12:00:00+00:00",
                    "end": "2026-01-01T13:00:00+00:00",
                }
            ],
        )
        engine = AnalysisFrameworkEngine(config)

        analysis = engine.analyze(
            {"H1": _trend_frame("2026-02-01", "h", 2050.0, 0.45)},
            now=datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc),
        )

        self.assertTrue(analysis.blocked)
        self.assertIn("NFP news window", " ".join(analysis.hard_blocks))


def _trend_frame(start: str, freq: str, base: float, step: float) -> pd.DataFrame:
    rows = []
    times = pd.date_range(start, periods=260, freq=freq, tz="UTC")
    for index, timestamp in enumerate(times):
        close = base + index * step
        open_price = close - step * 0.35
        high = max(open_price, close) + abs(step) * 1.5 + 0.20
        low = min(open_price, close) - abs(step) * 1.5 - 0.20
        rows.append(
            {
                "time": timestamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": 100 + index,
            }
        )
    return pd.DataFrame(rows)


def _sandwich_frame() -> pd.DataFrame:
    rows = []
    times = pd.date_range("2026-01-01", periods=220, freq="h", tz="UTC")
    closes = [100.0] * 170 + [90.0] * 49 + [95.0]
    for timestamp, close in zip(times, closes):
        rows.append(
            {
                "time": timestamp,
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "tick_volume": 100,
            }
        )
    return pd.DataFrame(rows)

from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

import pandas as pd

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.liquidity import LiquidityAnalyzer
from xau_sniper_bot.models import Direction, SniperTrigger, TargetLevel


class LiquidityAnalyzerTests(TestCase):
    def test_passes_when_spread_and_tick_volume_confirm(self) -> None:
        config = BotConfig(
            min_trigger_volume_multiplier=1.20,
            min_sweep_volume_multiplier=1.10,
        )
        analyzer = LiquidityAnalyzer(config)
        m1 = _m1_frame(trigger_volume=220, sweep_volume=180)
        trigger = _trigger(m1.iloc[-1]["time"])

        snapshot = analyzer.analyze(
            m1=m1,
            m5=m1,
            m15=_m15_frame(),
            direction=Direction.BUY,
            trigger=trigger,
            spread=0.20,
            now=datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(snapshot.spread_ok)
        self.assertTrue(snapshot.volume_ok)
        self.assertTrue(snapshot.passed)
        self.assertGreater(snapshot.trigger_volume_multiplier, 1.20)

    def test_fails_when_tick_volume_is_weak(self) -> None:
        config = BotConfig(
            min_trigger_volume_multiplier=1.50,
            min_sweep_volume_multiplier=1.50,
        )
        analyzer = LiquidityAnalyzer(config)
        m1 = _m1_frame(trigger_volume=100, sweep_volume=100)
        trigger = _trigger(m1.iloc[-1]["time"])

        snapshot = analyzer.analyze(
            m1=m1,
            m5=m1,
            m15=_m15_frame(),
            direction=Direction.BUY,
            trigger=trigger,
            spread=0.20,
            now=datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc),
        )

        self.assertFalse(snapshot.volume_ok)
        self.assertFalse(snapshot.passed)

    def test_market_context_reports_current_volume_and_pools(self) -> None:
        analyzer = LiquidityAnalyzer(BotConfig())
        m1 = _m1_frame(trigger_volume=180, sweep_volume=130)

        context = analyzer.market_context(
            m1=m1,
            m15=_m15_frame(),
            direction=Direction.BUY,
            spread=0.20,
            now=datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(context.spread_ok)
        self.assertEqual(context.current_volume, 180.0)
        self.assertGreater(context.current_volume_multiplier, 1.0)
        self.assertTrue(context.liquidity_pools)

    def test_buy_context_filters_liquidity_pools_above_current_price(self) -> None:
        analyzer = LiquidityAnalyzer(BotConfig())
        m1 = _m1_frame(trigger_volume=180, sweep_volume=130)

        context = analyzer.market_context(
            m1=m1,
            m15=_m15_frame_with_equal_lows_above_price(),
            direction=Direction.BUY,
            spread=0.20,
            now=datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc),
        )

        self.assertIn("previous low 95.00", context.liquidity_pools)
        self.assertNotIn("equal lows near 110.00", context.liquidity_pools)


def _m1_frame(trigger_volume: int, sweep_volume: int) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 12:00", periods=40, freq="min", tz="UTC")
    rows = []
    for idx, timestamp in enumerate(times):
        rows.append(
            {
                "time": timestamp,
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.2,
                "tick_volume": 100,
            }
        )
    rows[-2].update({"low": 98.9, "close": 99.4, "tick_volume": sweep_volume})
    rows[-1].update({"open": 99.4, "high": 102.0, "low": 99.2, "close": 101.8})
    rows[-1]["tick_volume"] = trigger_volume
    return pd.DataFrame(rows)


def _m15_frame() -> pd.DataFrame:
    times = pd.date_range("2026-01-01 08:00", periods=60, freq="15min", tz="UTC")
    rows = []
    for idx, timestamp in enumerate(times):
        rows.append(
            {
                "time": timestamp,
                "open": 100.0 + idx * 0.1,
                "high": 102.0 + idx * 0.1,
                "low": 98.0 + idx * 0.1,
                "close": 101.0 + idx * 0.1,
                "tick_volume": 100,
            }
        )
    return pd.DataFrame(rows)


def _m15_frame_with_equal_lows_above_price() -> pd.DataFrame:
    times = pd.date_range("2026-01-01 08:00", periods=60, freq="15min", tz="UTC")
    rows = []
    for idx, timestamp in enumerate(times):
        rows.append(
            {
                "time": timestamp,
                "open": 100.0,
                "high": 120.0 + idx * 0.1,
                "low": 90.0 + idx * 0.5,
                "close": 101.0,
                "tick_volume": 100,
            }
        )
    rows[-8]["low"] = 110.0
    rows[-3]["low"] = 110.1
    return pd.DataFrame(rows)


def _trigger(timestamp: object) -> SniperTrigger:
    return SniperTrigger(
        symbol="XAUUSD",
        direction=Direction.BUY,
        timestamp=pd.Timestamp(timestamp).to_pydatetime(),
        entry_price=101.8,
        stop_loss=98.8,
        target_1=TargetLevel(106.0, "nearest high", "M15"),
        target_2=TargetLevel(110.0, "extended high", "H1"),
        swept_level=99.0,
        bos_level=101.0,
        atr=1.0,
        reason=["test"],
        risk_reward=1.4,
    )

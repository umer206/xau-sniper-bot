from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

import pandas as pd

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.models import Direction, TargetLevel, Zone
from xau_sniper_bot.sniper import M1SniperScanner


class M1SniperScannerTests(TestCase):
    def test_buy_trigger_after_sweep_reclaim_and_bos(self) -> None:
        config = BotConfig(symbol="XAUUSD", risk_reward_floor=1.25)
        scanner = M1SniperScanner(config)
        zone = Zone(
            symbol="XAUUSD",
            direction=Direction.BUY,
            timeframe="M15",
            low=1999.30,
            high=2000.20,
            anchor_time=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            reason=["test demand"],
        )

        rows = []
        times = pd.date_range("2026-01-01", periods=60, freq="min", tz="UTC")
        for i, timestamp in enumerate(times):
            rows.append(
                {
                    "time": timestamp,
                    "open": 2000.40,
                    "high": 2001.00,
                    "low": 2000.00,
                    "close": 2000.50,
                    "tick_volume": 100 + i,
                }
            )

        rows[55].update({"open": 2000.40, "high": 2000.80, "low": 1999.50, "close": 2000.20})
        rows[56].update({"open": 2000.20, "high": 2000.90, "low": 2000.10, "close": 2000.70})
        rows[57].update({"open": 2000.70, "high": 2001.00, "low": 2000.40, "close": 2000.80})
        rows[58].update({"open": 2000.80, "high": 2001.10, "low": 2000.50, "close": 2000.90})
        rows[59].update({"open": 2000.90, "high": 2002.60, "low": 2000.70, "close": 2002.30})

        trigger = scanner.scan(
            pd.DataFrame(rows),
            zone,
            [
                TargetLevel(
                    price=2008.00,
                    label="nearest M15 swing high liquidity",
                    timeframe="M15",
                )
            ],
        )

        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.direction, Direction.BUY)
        self.assertGreater(trigger.entry_price, trigger.bos_level)
        self.assertLess(trigger.stop_loss, trigger.swept_level)
        self.assertEqual(trigger.target_1.price, 2008.00)
        self.assertEqual(trigger.take_profit, 2008.00)
        self.assertGreaterEqual(trigger.risk_reward, config.risk_reward_floor)

    def test_sell_continuation_zone_uses_near_m1_pullback(self) -> None:
        scanner = M1SniperScanner(BotConfig(symbol="XAUUSD"))
        frame = _bearish_m1_frame()

        zone = scanner.continuation_zone(
            frame,
            Direction.SELL,
            current_price=float(frame.iloc[-1]["close"]),
        )

        self.assertIsNotNone(zone)
        assert zone is not None
        self.assertEqual(zone.direction, Direction.SELL)
        self.assertEqual(zone.timeframe, "M1")
        self.assertEqual(zone.setup_type, "continuation")
        self.assertLess(zone.low, zone.high)


def _bearish_m1_frame() -> pd.DataFrame:
    rows = []
    times = pd.date_range("2026-01-01 10:00", periods=80, freq="min", tz="UTC")
    price = 101.0
    for timestamp in times:
        rows.append(
            {
                "time": timestamp,
                "open": price,
                "high": price + 0.10,
                "low": price - 0.12,
                "close": price - 0.05,
                "tick_volume": 100,
            }
        )
        price -= 0.02

    rows[70].update({"open": 99.20, "high": 99.35, "low": 98.80, "close": 98.90})
    rows[71].update({"open": 98.90, "high": 99.05, "low": 98.20, "close": 98.30})
    rows[72].update({"open": 98.30, "high": 98.40, "low": 97.80, "close": 97.90})
    rows[73].update({"open": 97.90, "high": 98.15, "low": 97.70, "close": 98.00})
    rows[74].update({"open": 98.00, "high": 98.25, "low": 97.60, "close": 97.70})
    rows[75].update({"open": 97.70, "high": 97.85, "low": 97.10, "close": 97.20})
    rows[76].update({"open": 97.20, "high": 97.35, "low": 96.80, "close": 96.90})
    rows[77].update({"open": 96.90, "high": 97.05, "low": 96.50, "close": 96.65})
    rows[78].update({"open": 96.65, "high": 96.80, "low": 96.20, "close": 96.35})
    rows[79].update({"open": 96.35, "high": 96.55, "low": 96.00, "close": 96.10})
    return pd.DataFrame(rows)

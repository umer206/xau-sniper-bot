from __future__ import annotations

from unittest import TestCase

import pandas as pd

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.confirmation import M5ConfirmationEngine
from xau_sniper_bot.models import Direction


class M5ConfirmationTests(TestCase):
    def test_sell_continuation_candidate_uses_minor_pullback_zone(self) -> None:
        engine = M5ConfirmationEngine(BotConfig(symbol="XAUUSD"))

        zone, confirmation = engine.continuation_candidate(
            _bearish_m5_frame(),
            Direction.SELL,
            current_price=95.20,
        )

        self.assertTrue(confirmation.confirmed)
        self.assertEqual(zone.direction, Direction.SELL)
        self.assertEqual(zone.timeframe, "M5")
        self.assertEqual(zone.setup_type, "continuation")
        self.assertLess(zone.low, zone.high)
        self.assertIn("bearish continuation", " ".join(zone.reason))


def _bearish_m5_frame() -> pd.DataFrame:
    times = pd.date_range("2026-01-01 08:00", periods=70, freq="5min", tz="UTC")
    rows = []
    price = 105.0
    for timestamp in times:
        rows.append(
            {
                "time": timestamp,
                "open": price,
                "high": price + 0.45,
                "low": price - 0.35,
                "close": price - 0.15,
                "tick_volume": 100,
            }
        )
        price -= 0.08

    for idx in range(58, 64):
        rows[idx].update(
            {
                "open": 99.0,
                "high": 99.4,
                "low": 98.4,
                "close": 98.8,
            }
        )
    rows[64].update({"open": 98.9, "high": 99.8, "low": 98.2, "close": 99.2})
    rows[65].update({"open": 99.2, "high": 99.5, "low": 97.8, "close": 98.0})
    rows[66].update({"open": 98.0, "high": 98.2, "low": 96.4, "close": 96.7})
    rows[67].update({"open": 96.7, "high": 97.0, "low": 95.6, "close": 95.9})
    rows[68].update({"open": 95.9, "high": 96.2, "low": 95.0, "close": 95.4})
    rows[69].update({"open": 95.4, "high": 95.8, "low": 94.8, "close": 95.2})
    return pd.DataFrame(rows)

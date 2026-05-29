from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

import pandas as pd

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.models import Direction, Zone
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

        trigger = scanner.scan(pd.DataFrame(rows), zone, take_profit=2008.00)

        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.direction, Direction.BUY)
        self.assertGreater(trigger.entry_price, trigger.bos_level)
        self.assertLess(trigger.stop_loss, trigger.swept_level)
        self.assertGreaterEqual(trigger.risk_reward, config.risk_reward_floor)


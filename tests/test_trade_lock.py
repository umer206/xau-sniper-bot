from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.models import (
    Bias,
    BiasSnapshot,
    ConfirmationSnapshot,
    Direction,
    Signal,
    SniperTrigger,
    TargetLevel,
    ValidationResult,
    Zone,
)
from xau_sniper_bot.trade_lock import TradeLock


class TradeLockTests(TestCase):
    def test_records_and_detects_duplicate_setup(self) -> None:
        with TemporaryDirectory() as tmp:
            lock = TradeLock(
                BotConfig(
                    trade_lock_enabled=True,
                    trade_lock_path=str(Path(tmp) / "trade_lock.json"),
                )
            )
            signal = _signal()
            setup_id = lock.setup_id(signal)

            locked_before, _ = lock.is_locked(setup_id)
            lock.record(setup_id, signal, "placed")
            locked_after, payload = lock.is_locked(setup_id)

            self.assertFalse(locked_before)
            self.assertTrue(locked_after)
            assert payload is not None
            self.assertEqual(payload["setup_id"], setup_id)
            self.assertEqual(payload["execution_status"], "placed")

    def test_expired_lock_is_removed(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "trade_lock.json"
            lock = TradeLock(
                BotConfig(
                    trade_lock_enabled=True,
                    trade_lock_path=str(path),
                    trade_lock_ttl_minutes=1,
                )
            )
            setup_id = lock.setup_id(_signal())
            old_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            path.write_text(
                json.dumps({setup_id: {"created_at": old_time.isoformat()}}),
                encoding="utf-8",
            )

            locked, payload = lock.is_locked(setup_id)

            self.assertFalse(locked)
            self.assertIsNone(payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})


def _signal() -> Signal:
    now = datetime.now(timezone.utc)
    return Signal(
        symbol="XAUUSD",
        bias=BiasSnapshot("XAUUSD", "H1", Bias.BULLISH, now, 4560.0, ["bullish"]),
        zone=Zone("XAUUSD", Direction.BUY, "M15", 4550.0, 4555.0, now, now, ["demand"]),
        confirmation=ConfirmationSnapshot("XAUUSD", "M5", Direction.BUY, True, now, ["ok"]),
        trigger=SniperTrigger(
            symbol="XAUUSD",
            direction=Direction.BUY,
            timestamp=now,
            entry_price=4555.0,
            stop_loss=4550.0,
            target_1=TargetLevel(4562.5, "nearest M15 swing high", "M15", now),
            target_2=TargetLevel(4570.0, "extended H1 swing high", "H1", now),
            swept_level=4551.0,
            bos_level=4554.0,
            atr=1.0,
            reason=["trigger"],
            risk_reward=1.5,
        ),
        validation=ValidationResult("approve", 0.7, [], [], "openai_disabled"),
    )

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.execution import MT5TradeExecutor
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


class ExecutionTests(TestCase):
    def test_dry_run_does_not_send_order(self) -> None:
        mt5_client = SimpleNamespace(mt5=SimpleNamespace())
        executor = MT5TradeExecutor(
            BotConfig(dry_run=True, trade_execution_enabled=True),
            mt5_client,
        )

        result = executor.execute(_signal())

        self.assertEqual(result.status, "dry_run")
        self.assertIn("not sent", result.message)

    def test_disabled_execution_does_not_lock_trade(self) -> None:
        mt5_client = SimpleNamespace(mt5=SimpleNamespace())
        executor = MT5TradeExecutor(
            BotConfig(dry_run=False, trade_execution_enabled=False),
            mt5_client,
        )

        result = executor.execute(_signal())

        self.assertEqual(result.status, "disabled")


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

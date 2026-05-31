from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from xau_sniper_bot.models import (
    Bias,
    BiasSnapshot,
    ConfirmationSnapshot,
    Direction,
    MarketContext,
    Signal,
    SniperTrigger,
    TargetLevel,
    ValidationResult,
    Zone,
)
from xau_sniper_bot.output import format_trade_setup
from xau_sniper_bot.output import format_no_trade_setup


class OutputFormatterTests(TestCase):
    def test_trade_setup_block_matches_requested_shape(self) -> None:
        signal = Signal(
            symbol="XAUUSD",
            bias=BiasSnapshot(
                symbol="XAUUSD",
                timeframe="H1",
                bias=Bias.BULLISH,
                updated_at=_dt("2026-01-01T14:00:00+00:00"),
                last_close=4531.75,
                reason=["Recent H1 swings show higher high and higher low"],
            ),
            zone=Zone(
                symbol="XAUUSD",
                direction=Direction.BUY,
                timeframe="M15",
                low=4525.95,
                high=4528.10,
                anchor_time=_dt("2026-01-01T14:28:00+00:00"),
                created_at=_dt("2026-01-01T14:28:00+00:00"),
                reason=["M15 demand/support formed from swing low and bullish reaction"],
            ),
            confirmation=ConfirmationSnapshot(
                symbol="XAUUSD",
                timeframe="M5",
                direction=Direction.BUY,
                confirmed=True,
                updated_at=_dt("2026-01-01T14:35:00+00:00"),
                reason=["M5 has bullish displacement after zone interaction"],
            ),
            trigger=SniperTrigger(
                symbol="XAUUSD",
                direction=Direction.BUY,
                timestamp=_dt("2026-01-01T14:38:00+00:00"),
                entry_price=4527.92,
                stop_loss=4525.95,
                target_1=TargetLevel(
                    price=4530.95,
                    label="nearest M15 swing high liquidity",
                    timeframe="M15",
                    anchor_time=_dt("2026-01-01T13:30:00+00:00"),
                ),
                target_2=TargetLevel(
                    price=4535.37,
                    label="extended H1 swing high liquidity",
                    timeframe="H1",
                    anchor_time=_dt("2026-01-01T13:50:00+00:00"),
                ),
                swept_level=4526.10,
                bos_level=4528.80,
                atr=0.80,
                reason=["M1 swept sell-side liquidity below recent low"],
                risk_reward=1.54,
            ),
            validation=ValidationResult(
                decision="approve",
                confidence=0.65,
                risk_notes=[],
                execution_notes=[],
                source="openai_disabled",
            ),
            generated_at=_dt("2026-01-01T14:39:00+00:00"),
        )

        text = format_trade_setup(signal)

        self.assertIn("=== TRADE SETUP ===", text)
        self.assertIn("Direction : LONG", text)
        self.assertIn("Entry     : 4527.92", text)
        self.assertIn("Target 1  : 4530.95", text)
        self.assertIn("Target 2  : 4535.37", text)
        self.assertIn("R:R       : 1:1.5", text)
        self.assertIn("Confluence:", text)

    def test_no_trade_block_explains_waiting_zone(self) -> None:
        text = format_no_trade_setup(
            symbol="XAUUSD",
            reason="M1 sniper trigger incomplete.",
            current_price=4563.04,
            bias=BiasSnapshot(
                symbol="XAUUSD",
                timeframe="H1",
                bias=Bias.BULLISH,
                updated_at=_dt("2026-01-01T14:00:00+00:00"),
                last_close=4563.04,
                reason=["Recent H1 swings show higher high and higher low"],
            ),
            zones=[
                Zone(
                    symbol="XAUUSD",
                    direction=Direction.BUY,
                    timeframe="M15",
                    low=4508.19,
                    high=4516.57,
                    anchor_time=_dt("2026-01-01T13:30:00+00:00"),
                    created_at=_dt("2026-01-01T13:30:00+00:00"),
                    reason=["M15 demand/support"],
                )
            ],
            external_analysis=None,
            market_context=MarketContext(
                spread=0.20,
                spread_ok=True,
                session="london_new_york_overlap",
                current_volume=180.0,
                average_volume=120.0,
                current_volume_multiplier=1.5,
                smooth_price_action=True,
                liquidity_pools=["previous low 4508.19"],
                reason=["test"],
            ),
        )

        self.assertIn("Direction : NO TRADE", text)
        self.assertIn("Current XAUUSD price is 4563.04", text)
        self.assertIn("Volume    : current M1 tick volume 1.50x average", text)
        self.assertIn("Liquidity : spread 0.20 (OK)", text)
        self.assertIn("Aligned plan: waiting for price to enter the buy zone", text)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)

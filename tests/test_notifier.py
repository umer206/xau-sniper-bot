from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.models import Bias, BiasSnapshot, Direction, Zone
from xau_sniper_bot.notifier import PushoverNotifier, _truncate


class PushoverNotifierTests(TestCase):
    def test_disabled_notifier_does_not_send(self) -> None:
        result = PushoverNotifier(BotConfig(pushover_enabled=False)).send(
            "Title",
            "Message",
        )

        self.assertFalse(result.sent)
        self.assertEqual(result.message, "Pushover disabled")

    def test_missing_credentials_are_reported(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = PushoverNotifier(BotConfig(pushover_enabled=True)).send(
                "Title",
                "Message",
            )

        self.assertFalse(result.sent)
        self.assertEqual(result.message, "Missing Pushover token or user key")

    def test_message_is_truncated_to_pushover_limit(self) -> None:
        self.assertLessEqual(len(_truncate("x" * 2000)), 1024)

    def test_scan_summary_can_be_disabled(self) -> None:
        now = datetime.now(timezone.utc)
        result = PushoverNotifier(
            BotConfig(
                pushover_enabled=True,
                pushover_alert_scan_summary=False,
            )
        ).notify_scan_summary(
            symbol="XAUUSD",
            reason="Waiting for entry trigger",
            current_price=4560.0,
            bias=BiasSnapshot("XAUUSD", "H1", Bias.BULLISH, now, 4560.0, []),
            zones=[
                Zone("XAUUSD", Direction.BUY, "M15", 4550.0, 4555.0, now, now, [])
            ],
            external_analysis=None,
        )

        self.assertFalse(result.sent)
        self.assertEqual(result.message, "Scan summary alerts disabled")

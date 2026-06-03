from __future__ import annotations

from unittest import TestCase

from xau_sniper_bot.external_analyzer import _groq_summary, _normalize_groq_direction


class ExternalAnalyzerTests(TestCase):
    def test_normalizes_groq_direction_from_trade_setup_text(self) -> None:
        self.assertEqual(_normalize_groq_direction("Direction : SHORT"), "SHORT")
        self.assertEqual(_normalize_groq_direction("Direction : LONG"), "LONG")
        self.assertEqual(_normalize_groq_direction("Direction : NO TRADE"), "NO TRADE")

    def test_groq_summary_keeps_key_trade_lines(self) -> None:
        summary = _groq_summary(
            "\n".join(
                [
                    "=== TRADE SETUP ===",
                    "Direction : SHORT",
                    "Entry     : 4520.00",
                    "Stop Loss : 4524.00",
                    "Target 1  : 4514.00",
                ]
            )
        )

        self.assertIn("Direction : SHORT", summary)
        self.assertIn("Entry     : 4520.00", summary)

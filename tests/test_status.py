from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from xau_sniper_bot.config import BotConfig
from xau_sniper_bot.status import StatusWriter


class StatusWriterTests(TestCase):
    def test_writes_running_status_file(self) -> None:
        with TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "status.json"
            writer = StatusWriter(
                BotConfig(
                    symbol="XAUUSD",
                    status_file_path=str(status_path),
                    dry_run=True,
                    trade_execution_enabled=True,
                )
            )

            writer.running("Scanning market", reason="test")

            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "running")
            self.assertEqual(payload["message"], "Scanning market")
            self.assertEqual(payload["symbol"], "XAUUSD")
            self.assertTrue(payload["dry_run"])
            self.assertTrue(payload["trade_execution_enabled"])
            self.assertEqual(payload["reason"], "test")


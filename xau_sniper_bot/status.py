from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BotConfig


class StatusWriter:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.path = Path(config.status_file_path)

    def running(self, message: str, **extra: Any) -> None:
        self.write("running", message, **extra)

    def stopped(self, message: str, **extra: Any) -> None:
        self.write("stopped", message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        self.write("error", message, **extra)

    def write(self, status: str, message: str, **extra: Any) -> None:
        payload = {
            "status": status,
            "message": message,
            "symbol": self.config.symbol,
            "dry_run": self.config.dry_run,
            "trade_execution_enabled": self.config.trade_execution_enabled,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)


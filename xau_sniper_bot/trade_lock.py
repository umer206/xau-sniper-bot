from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import BotConfig
from .models import Signal


class TradeLock:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.path = Path(config.trade_lock_path)

    def setup_id(self, signal: Signal) -> str:
        payload = {
            "symbol": signal.symbol,
            "direction": signal.trigger.direction.value,
            "zone_low": round(signal.zone.low, 2),
            "zone_high": round(signal.zone.high, 2),
            "entry": round(signal.trigger.entry_price, 2),
            "stop_loss": round(signal.trigger.stop_loss, 2),
            "target_1": round(signal.trigger.target_1.price, 2),
            "swept_level": round(signal.trigger.swept_level, 2),
            "bos_level": round(signal.trigger.bos_level, 2),
            "sweep_time": signal.trigger.timestamp.isoformat(timespec="minutes"),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def is_locked(self, setup_id: str) -> tuple[bool, dict[str, Any] | None]:
        if not self.config.trade_lock_enabled:
            return False, None

        data = self._read()
        lock = data.get(setup_id)
        if lock is None:
            return False, None

        created_at = _parse_datetime(lock.get("created_at"))
        if created_at is None:
            return True, lock

        ttl = timedelta(minutes=self.config.trade_lock_ttl_minutes)
        if datetime.now(timezone.utc) - created_at > ttl:
            data.pop(setup_id, None)
            self._write(data)
            return False, None

        return True, lock

    def record(self, setup_id: str, signal: Signal, execution_status: str) -> None:
        if not self.config.trade_lock_enabled:
            return

        data = self._read()
        data[setup_id] = {
            "setup_id": setup_id,
            "symbol": signal.symbol,
            "direction": signal.trigger.direction.value,
            "entry": signal.trigger.entry_price,
            "stop_loss": signal.trigger.stop_loss,
            "target_1": signal.trigger.target_1.price,
            "execution_status": execution_status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write(data)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


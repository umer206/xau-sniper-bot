from __future__ import annotations

import json
from pathlib import Path

from .config import BotConfig
from .models import Signal


class OutputWriter:
    def __init__(self, config: BotConfig, chart_bridge_path: Path | None = None) -> None:
        self.config = config
        self.output_path = Path(config.output_jsonl_path)
        self.chart_bridge_path = self._resolve_chart_bridge_path(chart_bridge_path)

    def write_signal(self, signal: Signal) -> None:
        payload = signal.to_dict()
        self._write_console(signal)
        self._write_jsonl(payload)
        self._write_chart_bridge(payload)

    def _write_console(self, signal: Signal) -> None:
        trigger = signal.trigger
        validation = signal.validation
        print(
            "\n"
            f"[{signal.generated_at.isoformat()}] {signal.symbol} "
            f"{trigger.direction.value.upper()} "
            f"{validation.decision.upper()} confidence={validation.confidence:.2f}\n"
            f"entry={trigger.entry_price:.2f} sl={trigger.stop_loss:.2f} "
            f"tp={trigger.take_profit:.2f} rr={trigger.risk_reward:.2f}\n"
            f"zone={signal.zone.low:.2f}-{signal.zone.high:.2f} "
            f"bias={signal.bias.bias.value} m5={signal.confirmation.confirmed} "
            f"source={validation.source}\n"
            f"notes={' | '.join(validation.execution_notes or trigger.reason)}"
        )

    def _write_jsonl(self, payload: dict) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _write_chart_bridge(self, payload: dict) -> None:
        if self.chart_bridge_path is None:
            return
        self.chart_bridge_path.parent.mkdir(parents=True, exist_ok=True)
        self.chart_bridge_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def _resolve_chart_bridge_path(self, default_path: Path | None) -> Path | None:
        if not self.config.mt5_chart_bridge_enabled:
            return None
        if self.config.mt5_chart_bridge_path:
            return Path(self.config.mt5_chart_bridge_path)
        return default_path

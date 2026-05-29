from __future__ import annotations

import json
from pathlib import Path

from .config import BotConfig
from .models import Direction, Signal, TargetLevel


class OutputWriter:
    def __init__(self, config: BotConfig, chart_bridge_path: Path | None = None) -> None:
        self.config = config
        self.output_path = Path(config.output_jsonl_path)
        self.chart_bridge_path = self._resolve_chart_bridge_path(chart_bridge_path)

    def write_signal(self, signal: Signal) -> None:
        payload = signal.to_dict()
        payload["trade_setup_text"] = format_trade_setup(signal)
        self._write_console(signal)
        self._write_jsonl(payload)
        self._write_chart_bridge(payload)

    def _write_console(self, signal: Signal) -> None:
        print("\n" + format_trade_setup(signal))

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


def format_trade_setup(signal: Signal) -> str:
    trigger = signal.trigger
    direction = "LONG" if trigger.direction == Direction.BUY else "SHORT"
    zone_name = _zone_name(trigger.direction)
    choch = _choch_name(trigger.direction)
    stop_side = "below" if trigger.direction == Direction.BUY else "above"
    swept_side = (
        "sell-side liquidity sweep low"
        if trigger.direction == Direction.BUY
        else "buy-side liquidity sweep high"
    )

    return "\n".join(
        [
            "=== TRADE SETUP ===",
            f"Direction : {direction}",
            (
                f"Entry     : {trigger.entry_price:.2f}, based on the {zone_name} "
                f"@ {_time_label(signal.zone.anchor_time)} and the {choch} "
                f"@ {_time_label(trigger.timestamp)}."
            ),
            (
                f"Stop Loss : {trigger.stop_loss:.2f}, {stop_side} the {swept_side} "
                f"@ {trigger.swept_level:.2f}."
            ),
            f"Target 1  : {_target_line(trigger.target_1)}",
            f"Target 2  : {_target_line(trigger.target_2)}",
            f"R:R       : 1:{trigger.risk_reward:.1f}",
            _external_line(signal),
            f"Confluence: {_confluence(signal)}",
        ]
    )


def _target_line(target: TargetLevel) -> str:
    suffix = f" @ {_time_label(target.anchor_time)}" if target.anchor_time else ""
    return f"{target.price:.2f}, {target.label}{suffix}."


def _zone_name(direction: Direction) -> str:
    if direction == Direction.BUY:
        return "bullish OB / demand zone"
    return "bearish OB / supply zone"


def _choch_name(direction: Direction) -> str:
    if direction == Direction.BUY:
        return "bullish CHOCH/BOS"
    return "bearish CHOCH/BOS"


def _confluence(signal: Signal) -> str:
    direction_word = "Bullish" if signal.trigger.direction == Direction.BUY else "Bearish"
    zone_word = (
        "demand/support"
        if signal.trigger.direction == Direction.BUY
        else "supply/resistance"
    )
    pieces = [
        f"{direction_word} H1 bias",
        f"M15 {zone_word} zone",
        "M5 confirmation",
        "M1 liquidity sweep",
        "rejection candle",
        "CHOCH/BOS",
        "displacement candle",
    ]
    if signal.validation.source == "openai" and signal.validation.approved:
        pieces.append("OpenAI validation")
    if signal.external_analysis and signal.external_analysis.tradeable:
        pieces.append(
            f"external analyzer aligned {signal.external_analysis.direction} "
            f"({signal.external_analysis.bull_score}/"
            f"{signal.external_analysis.bear_score})"
        )
    return ", ".join(pieces) + "."


def _external_line(signal: Signal) -> str:
    analysis = signal.external_analysis
    if analysis is None:
        return "Second AI : Disabled."
    if analysis.direction == "ERROR":
        return f"Second AI : ERROR - {'; '.join(analysis.reason)}"
    status = "ALIGNED" if _external_direction_matches(signal) else "NOT ALIGNED"
    return (
        f"Second AI : {analysis.direction} ({status}) | "
        f"Bull {analysis.bull_score} / Bear {analysis.bear_score}."
    )


def _external_direction_matches(signal: Signal) -> bool:
    analysis = signal.external_analysis
    if analysis is None or not analysis.tradeable:
        return False
    expected = "LONG" if signal.trigger.direction == Direction.BUY else "SHORT"
    return analysis.direction == expected


def _time_label(value: object) -> str:
    if value is None:
        return "n/a"
    return value.strftime("%H:%M")

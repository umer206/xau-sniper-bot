from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from pathlib import Path

from .config import BotConfig
from .models import BiasSnapshot, Direction, ExternalAnalysis, Signal, TargetLevel, Zone


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

    def write_no_trade(
        self,
        *,
        symbol: str,
        reason: str,
        current_price: float | None = None,
        bias: BiasSnapshot | None = None,
        zones: list[Zone] | None = None,
        external_analysis: ExternalAnalysis | None = None,
    ) -> None:
        text = format_no_trade_setup(
            symbol=symbol,
            reason=reason,
            current_price=current_price,
            bias=bias,
            zones=zones or [],
            external_analysis=external_analysis,
        )
        payload = {
            "type": "no_trade",
            "symbol": symbol,
            "reason": reason,
            "current_price": current_price,
            "bias": _payload_safe(asdict(bias)) if bias else None,
            "zones": [_payload_safe(asdict(zone)) for zone in zones or []],
            "external_analysis": _payload_safe(asdict(external_analysis))
            if external_analysis
            else None,
            "trade_setup_text": text,
        }
        print("\n" + text)
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
            _execution_line(signal),
            f"Confluence: {_confluence(signal)}",
        ]
    )


def format_no_trade_setup(
    *,
    symbol: str,
    reason: str,
    current_price: float | None,
    bias: BiasSnapshot | None,
    zones: list[Zone],
    external_analysis: ExternalAnalysis | None,
) -> str:
    zone_text = _zone_wait_text(zones, current_price, bias)
    bias_text = bias.bias.value if bias else "unknown"
    price_text = f"{current_price:.2f}" if current_price is not None else "n/a"
    return "\n".join(
        [
            "=== TRADE SETUP ===",
            "Direction : NO TRADE",
            f"Entry     : Waiting. Current {symbol} price is {price_text}. {zone_text}",
            "Stop Loss : N/A",
            "Target 1  : N/A",
            "Target 2  : N/A",
            "R:R       : N/A",
            _external_no_trade_line(external_analysis),
            f"Confluence: H1 bias is {bias_text}. {reason}",
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


def _zone_wait_text(
    zones: list[Zone],
    current_price: float | None,
    bias: BiasSnapshot | None,
) -> str:
    if not zones:
        return "No active setup zone is available."

    aligned_direction = _direction_for_bias(bias)
    aligned_zones = (
        [zone for zone in zones if zone.direction == aligned_direction]
        if aligned_direction
        else zones
    )
    opposite_zones = (
        [zone for zone in zones if zone.direction != aligned_direction]
        if aligned_direction
        else []
    )

    parts: list[str] = []
    if aligned_zones:
        zone = _nearest_zone(aligned_zones, current_price)
        direction = "buy" if zone.direction == Direction.BUY else "sell"
        if current_price is not None and zone.low <= current_price <= zone.high:
            parts.append(
                f"Aligned plan: price is inside the {direction} zone "
                f"{zone.low:.2f}-{zone.high:.2f}."
            )
        else:
            parts.append(
                f"Aligned plan: waiting for price to enter the {direction} zone "
                f"{zone.low:.2f}-{zone.high:.2f}."
            )
    else:
        parts.append("No setup zone aligns with the active H1 bias.")

    if opposite_zones:
        opposite = _nearest_zone(opposite_zones, current_price)
        opposite_direction = "buy" if opposite.direction == Direction.BUY else "sell"
        parts.append(
            f"Opposite {opposite_direction} zone exists at "
            f"{opposite.low:.2f}-{opposite.high:.2f}, but it needs H1 reversal "
            "or explicit reversal confirmation."
        )
    return " ".join(parts)


def _direction_for_bias(bias: BiasSnapshot | None) -> Direction | None:
    if bias is None:
        return None
    if bias.bias.value == "bullish":
        return Direction.BUY
    if bias.bias.value == "bearish":
        return Direction.SELL
    return None


def _nearest_zone(zones: list[Zone], current_price: float | None) -> Zone:
    if current_price is None:
        return zones[0]
    return min(zones, key=lambda zone: abs(zone.midpoint - current_price))


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


def _external_no_trade_line(analysis: ExternalAnalysis | None) -> str:
    if analysis is None:
        return "Second AI : Not called; primary setup is not near-valid yet."
    if analysis.direction == "ERROR":
        return f"Second AI : ERROR - {'; '.join(analysis.reason)}"
    status = "TRADEABLE" if analysis.tradeable else "NO TRADE"
    return (
        f"Second AI : {analysis.direction} ({status}) | "
        f"Bull {analysis.bull_score} / Bear {analysis.bear_score}."
    )


def _execution_line(signal: Signal) -> str:
    execution = signal.execution
    if execution is None:
        return "Execution : Not attempted."
    return f"Execution : {execution.status.upper()} - {execution.message}"


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


def _payload_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_payload_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _payload_safe(item) for key, item in value.items()}
    return value

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BotConfig:
    symbol: str = "XAUUSD"
    h1_bars: int = 350
    m15_bars: int = 500
    m5_bars: int = 300
    m1_bars: int = 240
    h1_check_minutes: int = 60
    m15_check_minutes: int = 15
    m5_check_minutes: int = 5
    m1_check_seconds: int = 60
    h1_bias_mode: str = "balanced"
    swing_window: int = 2
    atr_period: int = 14
    zone_atr_padding: float = 0.20
    zone_max_age_bars: int = 120
    m5_zone_touch_lookback: int = 24
    m1_zone_touch_lookback: int = 10
    m1_sweep_lookback: int = 20
    m1_bos_lookback: int = 12
    min_displacement_atr: float = 0.55
    rejection_wick_ratio: float = 1.15
    min_m1_atr: float = 0.0
    max_m1_atr: float = 0.0
    risk_reward_floor: float = 1.25
    external_analyzer_enabled: bool = False
    external_analyzer_path: str = r"C:\2026\CodexAlyzer\main.py"
    external_analyzer_require_alignment: bool = True
    openai_enabled: bool = False
    openai_model: str = "gpt-5.2"
    openai_min_confidence: float = 0.70
    openai_cooldown_minutes: int = 10
    output_jsonl_path: str = "signals/xau_sniper_signals.jsonl"
    mt5_chart_bridge_enabled: bool = False
    mt5_chart_bridge_path: str = ""
    dry_run: bool = True


def load_config(path: str | Path | None = None) -> BotConfig:
    config_path = Path(path or os.getenv("XAU_SNIPER_CONFIG", "config.json"))
    if not config_path.exists():
        fallback = Path("config.example.json")
        config_path = fallback if fallback.exists() else config_path

    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))

    allowed = {field.name for field in fields(BotConfig)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"Unknown config keys in {config_path}: {', '.join(unknown)}")

    return BotConfig(**raw)

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
    zone_stale_after_hours: float = 12.0
    zone_expire_after_hours: float = 36.0
    zone_near_threshold_points: float = 5.0
    m5_zone_touch_lookback: int = 24
    m1_zone_touch_lookback: int = 10
    m1_sweep_lookback: int = 20
    m1_bos_lookback: int = 12
    min_displacement_atr: float = 0.55
    rejection_wick_ratio: float = 1.15
    min_m1_atr: float = 0.0
    max_m1_atr: float = 0.0
    risk_reward_floor: float = 1.25
    continuation_mode_enabled: bool = True
    continuation_lookback_bars: int = 24
    continuation_displacement_lookback: int = 8
    continuation_pullback_lookback: int = 12
    continuation_zone_atr_width: float = 0.80
    continuation_max_zone_distance_points: float = 20.0
    liquidity_filter_enabled: bool = True
    liquidity_session_filter_enabled: bool = False
    max_liquidity_spread: float = 0.50
    liquidity_volume_lookback: int = 20
    min_trigger_volume_multiplier: float = 1.25
    min_sweep_volume_multiplier: float = 1.10
    liquidity_smooth_lookback: int = 10
    max_liquidity_candle_atr_multiplier: float = 2.50
    liquidity_pool_lookback: int = 50
    equal_level_tolerance: float = 0.30
    external_analyzer_enabled: bool = False
    external_analyzer_path: str = ""
    external_analyzer_require_alignment: bool = True
    external_analyzer_use_groq: bool = False
    external_analyzer_groq_min_interval_minutes: int = 5
    external_analyzer_groq_api_key: str = ""
    trade_execution_enabled: bool = False
    trade_volume: float = 0.01
    trade_take_profit_target: int = 1
    trade_max_spread: float = 0.50
    trade_deviation_points: int = 20
    trade_magic: int = 260529
    trade_comment: str = "xau-sniper-bot"
    trade_allow_existing_position: bool = False
    trade_filling_mode: str = "auto"
    trade_lock_enabled: bool = True
    trade_lock_path: str = "runtime/trade_lock.json"
    trade_lock_ttl_minutes: int = 180
    openai_enabled: bool = False
    openai_model: str = "gpt-5.2"
    openai_min_confidence: float = 0.70
    openai_cooldown_minutes: int = 10
    output_jsonl_path: str = "signals/xau_sniper_signals.jsonl"
    log_to_file: bool = True
    log_file_path: str = "logs/bot.log"
    status_file_path: str = "runtime/status.json"
    status_stale_seconds: int = 180
    pushover_enabled: bool = True
    pushover_app_token: str = ""
    pushover_user_key: str = ""
    pushover_device: str = ""
    pushover_priority: int = 0
    pushover_sound: str = ""
    pushover_alert_signals: bool = True
    pushover_alert_no_trade: bool = False
    pushover_alert_scan_summary: bool = True
    pushover_scan_summary_min_interval_minutes: int = 15
    pushover_alert_status: bool = True
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

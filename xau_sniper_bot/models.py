from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Bias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Direction(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class BiasSnapshot:
    symbol: str
    timeframe: str
    bias: Bias
    updated_at: datetime
    last_close: float
    reason: list[str]
    swing_high: float | None = None
    swing_low: float | None = None


@dataclass(frozen=True)
class Zone:
    symbol: str
    direction: Direction
    timeframe: str
    low: float
    high: float
    anchor_time: datetime
    created_at: datetime
    reason: list[str]
    strength: float = 0.0

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True)
class ConfirmationSnapshot:
    symbol: str
    timeframe: str
    direction: Direction
    confirmed: bool
    updated_at: datetime
    reason: list[str]


@dataclass(frozen=True)
class TargetLevel:
    price: float
    label: str
    timeframe: str
    anchor_time: datetime | None = None


@dataclass(frozen=True)
class SniperTrigger:
    symbol: str
    direction: Direction
    timestamp: datetime
    entry_price: float
    stop_loss: float
    target_1: TargetLevel
    target_2: TargetLevel
    swept_level: float
    bos_level: float
    atr: float
    reason: list[str]
    risk_reward: float

    @property
    def take_profit(self) -> float:
        return self.target_1.price


@dataclass(frozen=True)
class ValidationResult:
    decision: str
    confidence: float
    risk_notes: list[str]
    execution_notes: list[str]
    source: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.decision == "approve"


@dataclass(frozen=True)
class ExternalAnalysis:
    name: str
    path: str
    direction: str
    tradeable: bool
    bull_score: int
    bear_score: int
    analyzed_at: datetime
    reason: list[str]
    details: list[str]


@dataclass(frozen=True)
class LiquiditySnapshot:
    spread: float
    spread_ok: bool
    session: str
    session_ok: bool
    trigger_volume: float
    average_volume: float
    trigger_volume_multiplier: float
    sweep_volume_multiplier: float
    volume_ok: bool
    smooth_price_action: bool
    liquidity_pools: list[str]
    passed: bool
    reason: list[str]


@dataclass(frozen=True)
class MarketContext:
    spread: float
    spread_ok: bool
    session: str
    current_volume: float
    average_volume: float
    current_volume_multiplier: float
    smooth_price_action: bool
    liquidity_pools: list[str]
    reason: list[str]


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    message: str
    order_id: int | None = None
    retcode: int | None = None
    price: float | None = None
    volume: float | None = None
    target_used: str | None = None


@dataclass(frozen=True)
class Signal:
    symbol: str
    bias: BiasSnapshot
    zone: Zone
    confirmation: ConfirmationSnapshot
    trigger: SniperTrigger
    validation: ValidationResult
    external_analysis: ExternalAnalysis | None = None
    liquidity: LiquiditySnapshot | None = None
    execution: ExecutionResult | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value

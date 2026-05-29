from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import BotConfig
from .models import (
    BiasSnapshot,
    ConfirmationSnapshot,
    Signal,
    SniperTrigger,
    ValidationResult,
    Zone,
)


VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "reject", "watch"]},
        "confidence": {"type": "number"},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
        "execution_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "confidence", "risk_notes", "execution_notes"],
    "additionalProperties": False,
}


class OpenAIValidator:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._last_call_at: datetime | None = None
        self._client = None

    def validate(
        self,
        bias: BiasSnapshot,
        zone: Zone,
        confirmation: ConfirmationSnapshot,
        trigger: SniperTrigger,
    ) -> ValidationResult:
        if not self.config.openai_enabled:
            return self._heuristic_validation(trigger, "openai_disabled")

        if self._in_cooldown():
            return self._heuristic_validation(trigger, "openai_cooldown")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return ValidationResult(
                decision="watch",
                confidence=0.0,
                risk_notes=["OPENAI_API_KEY is not set"],
                execution_notes=["Skipped OpenAI validation"],
                source="openai_missing_key",
            )

        try:
            response = self._client_with_key(api_key).responses.create(
                model=self.config.openai_model,
                instructions=(
                    "You are a strict trading setup validator for XAUUSD. "
                    "Return JSON only. Validate whether the proposed setup follows the "
                    "provided H1/M15/M1 rules. Do not add new trade ideas."
                ),
                input=json.dumps(
                    {
                        "bias": _json_safe(asdict(bias)),
                        "zone": _json_safe(asdict(zone)),
                        "confirmation": _json_safe(asdict(confirmation)),
                        "trigger": _json_safe(asdict(trigger)),
                        "rules": {
                            "buy": [
                                "H1/M15 bullish bias",
                                "Price in demand/support",
                                "M5 confirms bullish continuation after zone interaction",
                                "M1 sell-side sweep",
                                "Close back above swept low",
                                "Minor bullish BOS",
                                "SL below swept low",
                                "TP at higher timeframe liquidity",
                            ],
                            "sell": [
                                "H1/M15 bearish bias",
                                "Price in supply/resistance",
                                "M5 confirms bearish continuation after zone interaction",
                                "M1 buy-side sweep",
                                "Close back below swept high",
                                "Minor bearish BOS",
                                "SL above swept high",
                                "TP at higher timeframe liquidity",
                            ],
                        },
                    }
                ),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "xau_setup_validation",
                        "strict": True,
                        "schema": VALIDATION_SCHEMA,
                    }
                },
                max_output_tokens=450,
            )
            self._last_call_at = datetime.now(timezone.utc)
            parsed = json.loads(response.output_text)
            return ValidationResult(
                decision=str(parsed["decision"]),
                confidence=float(parsed["confidence"]),
                risk_notes=list(parsed["risk_notes"]),
                execution_notes=list(parsed["execution_notes"]),
                source="openai",
                raw=parsed,
            )
        except Exception as exc:
            return ValidationResult(
                decision="watch",
                confidence=0.0,
                risk_notes=[f"OpenAI validation failed: {exc}"],
                execution_notes=["Skipped signal approval because validation failed"],
                source="openai_error",
            )

    def should_emit(self, signal: Signal) -> bool:
        if signal.validation.source == "openai":
            return (
                signal.validation.approved
                and signal.validation.confidence >= self.config.openai_min_confidence
            )
        return signal.validation.decision in {"approve", "watch"}

    def _client_with_key(self, api_key: str):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key)
        return self._client

    def _in_cooldown(self) -> bool:
        if self._last_call_at is None:
            return False
        cooldown = timedelta(minutes=self.config.openai_cooldown_minutes)
        return datetime.now(timezone.utc) - self._last_call_at < cooldown

    def _heuristic_validation(self, trigger: SniperTrigger, source: str) -> ValidationResult:
        if trigger.risk_reward >= self.config.risk_reward_floor:
            return ValidationResult(
                decision="approve",
                confidence=0.65,
                risk_notes=["Heuristic approval only; OpenAI did not validate this setup"],
                execution_notes=["Use dry-run output unless live execution is explicitly enabled"],
                source=source,
            )
        return ValidationResult(
            decision="reject",
            confidence=0.8,
            risk_notes=["Risk/reward is below configured floor"],
            execution_notes=["No signal emitted"],
            source=source,
        )


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value

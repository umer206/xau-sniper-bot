from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

from .config import BotConfig
from .models import Direction, ExternalAnalysis


class ExternalAnalyzer:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._module: ModuleType | None = None
        self._last_groq_call_at: datetime | None = None
        self._last_groq_analysis: ExternalAnalysis | None = None

    def analyze(self, use_groq: bool = False) -> ExternalAnalysis | None:
        if not self.config.external_analyzer_enabled:
            return None

        if not self.config.external_analyzer_path.strip():
            return self._error("External analyzer path is not configured")

        path = Path(self.config.external_analyzer_path)
        if not path.exists():
            return self._error(f"External analyzer not found: {path}")

        try:
            module = self._load_module(path)
            data = module.get_market_data(self.config.symbol)
            smc_10m = module.detect_smc(data["candles"].get("10m", []))
            smc_1m = module.detect_smc(data["candles"].get("1m", []))
            confluence = module.score_confluence(smc_10m, smc_1m)
            analysis = ExternalAnalysis(
                name="CodexAlyzer Groq/SMC",
                path=str(path),
                direction=str(confluence.get("bias", "NO TRADE")),
                tradeable=bool(confluence.get("tradeable", False)),
                bull_score=int(confluence.get("bull", 0)),
                bear_score=int(confluence.get("bear", 0)),
                analyzed_at=datetime.now(timezone.utc),
                reason=[
                    (
                        "External SMC confluence is tradeable"
                        if confluence.get("tradeable")
                        else "External SMC confluence is not tradeable"
                    )
                ],
                details=_details_from_smc(smc_10m, smc_1m),
            )
            if use_groq and self.config.external_analyzer_use_groq:
                return self._with_groq(module, data, confluence, analysis)
            return analysis
        except Exception as exc:
            return self._error(f"External analyzer failed: {exc}")

    def aligns_with(self, analysis: ExternalAnalysis | None, direction: Direction) -> bool:
        if analysis is None:
            return not self.config.external_analyzer_require_alignment
        if analysis.direction == "ERROR":
            return not self.config.external_analyzer_require_alignment
        expected = "LONG" if direction == Direction.BUY else "SHORT"
        if not analysis.tradeable:
            return not self.config.external_analyzer_require_alignment
        return analysis.direction == expected

    def _load_module(self, path: Path) -> ModuleType:
        if self._module is not None:
            return self._module

        spec = importlib.util.spec_from_file_location("codex_alyzer_external", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load external analyzer from {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._module = module
        return module

    def _error(self, message: str) -> ExternalAnalysis:
        return ExternalAnalysis(
            name="CodexAlyzer Groq/SMC",
            path=self.config.external_analyzer_path,
            direction="ERROR",
            tradeable=False,
            bull_score=0,
            bear_score=0,
            analyzed_at=datetime.now(timezone.utc),
            reason=[message],
            details=[],
        )

    def _with_groq(
        self,
        module: ModuleType,
        data: dict,
        confluence: dict,
        local_analysis: ExternalAnalysis,
    ) -> ExternalAnalysis:
        if self._groq_in_cooldown():
            if self._last_groq_analysis is not None:
                return _replace_external(
                    self._last_groq_analysis,
                    analyzed_at=datetime.now(timezone.utc),
                    reason=local_analysis.reason + ["Groq reused: cooldown active"],
                )
            return _replace_external(
                local_analysis,
                direction="ERROR",
                tradeable=False,
                reason=local_analysis.reason + ["Groq skipped: cooldown active"],
            )

        api_key = self._groq_api_key(module)
        if not api_key:
            return _replace_external(
                local_analysis,
                direction="ERROR",
                tradeable=False,
                reason=local_analysis.reason + ["Groq skipped: GROQ_API_KEY is not set"],
            )

        try:
            prompt = module.build_prompt(data, confluence)
            client = module.Groq(api_key=api_key)
            groq_text = module.ask_groq(client, prompt)
            parsed = module.parse_last_trade(groq_text)
            if hasattr(module, "last_trade"):
                module.last_trade = parsed

            direction = _normalize_groq_direction(parsed.get("direction"))
            tradeable = direction in {"LONG", "SHORT"}
            self._last_groq_call_at = datetime.now(timezone.utc)
            summary = _groq_summary(groq_text)
            groq_analysis = _replace_external(
                local_analysis,
                direction=direction,
                tradeable=tradeable,
                reason=local_analysis.reason + [f"Groq verdict: {direction}"],
                details=(local_analysis.details + [summary])[-8:],
                groq_called=True,
                groq_summary=summary,
            )
            self._last_groq_analysis = groq_analysis
            return groq_analysis
        except Exception as exc:
            return _replace_external(
                local_analysis,
                direction="ERROR",
                tradeable=False,
                reason=local_analysis.reason + [f"Groq failed: {exc}"],
            )

    def _groq_in_cooldown(self) -> bool:
        if self._last_groq_call_at is None:
            return False
        cooldown = timedelta(minutes=self.config.external_analyzer_groq_min_interval_minutes)
        return datetime.now(timezone.utc) - self._last_groq_call_at < cooldown

    def _groq_api_key(self, module: ModuleType) -> str:
        configured = self.config.external_analyzer_groq_api_key.strip()
        if configured:
            return configured
        env_key = os.getenv("GROQ_API_KEY", "").strip()
        if env_key:
            return env_key
        return str(getattr(module, "GROQ_API_KEY", "")).strip()


def _details_from_smc(smc_10m: dict, smc_1m: dict) -> list[str]:
    details: list[str] = []
    for label, smc in (("10m", smc_10m), ("1m", smc_1m)):
        if not smc:
            continue
        for key, name in (
            ("bos", "BOS"),
            ("choch", "CHOCH"),
        ):
            value = smc.get(key)
            if value:
                details.append(f"{label} {name}: {value}")
        for key, name in (
            ("order_blocks", "OB"),
            ("fvg", "FVG"),
            ("liquidity", "Sweep"),
        ):
            for value in smc.get(key, [])[-2:]:
                details.append(f"{label} {name}: {value}")
    return details[-8:]


def _replace_external(analysis: ExternalAnalysis, **changes: object) -> ExternalAnalysis:
    values = {
        "name": analysis.name,
        "path": analysis.path,
        "direction": analysis.direction,
        "tradeable": analysis.tradeable,
        "bull_score": analysis.bull_score,
        "bear_score": analysis.bear_score,
        "analyzed_at": analysis.analyzed_at,
        "reason": analysis.reason,
        "details": analysis.details,
        "groq_called": analysis.groq_called,
        "groq_summary": analysis.groq_summary,
    }
    values.update(changes)
    return ExternalAnalysis(**values)


def _normalize_groq_direction(value: object) -> str:
    text = str(value or "NO TRADE").upper()
    if "LONG" in text:
        return "LONG"
    if "SHORT" in text:
        return "SHORT"
    return "NO TRADE"


def _groq_summary(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    interesting = [
        line
        for line in lines
        if line.startswith(("Direction", "Entry", "Stop Loss", "Target 1", "Warning"))
    ]
    return "; ".join(interesting[:3]) or "Groq analysis returned"

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from .config import BotConfig
from .models import Direction, ExternalAnalysis


class ExternalAnalyzer:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._module: ModuleType | None = None

    def analyze(self) -> ExternalAnalysis | None:
        if not self.config.external_analyzer_enabled:
            return None

        path = Path(self.config.external_analyzer_path)
        if not path.exists():
            return self._error(f"External analyzer not found: {path}")

        try:
            module = self._load_module(path)
            data = module.get_market_data(self.config.symbol)
            smc_10m = module.detect_smc(data["candles"].get("10m", []))
            smc_1m = module.detect_smc(data["candles"].get("1m", []))
            confluence = module.score_confluence(smc_10m, smc_1m)
            return ExternalAnalysis(
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


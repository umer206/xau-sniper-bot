from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import BotConfig, load_config
from .confirmation import M5ConfirmationEngine
from .external_analyzer import ExternalAnalyzer
from .execution import MT5TradeExecutor
from .logging_setup import tee_console_to_log
from .models import Bias, BiasSnapshot, Direction, ExternalAnalysis, Signal, Zone
from .mt5_client import MT5Client
from .notifier import PushoverNotifier
from .openai_validator import OpenAIValidator
from .output import OutputWriter
from .sniper import M1SniperScanner
from .status import StatusWriter
from .structure import H1BiasEngine, M15ZoneEngine


@dataclass
class MarketState:
    h1: pd.DataFrame | None = None
    m15: pd.DataFrame | None = None
    m5: pd.DataFrame | None = None
    bias: BiasSnapshot | None = None
    zones: list[Zone] | None = None
    h1_updated_at: datetime | None = None
    m15_updated_at: datetime | None = None
    m5_updated_at: datetime | None = None


class XauSniperBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.mt5 = MT5Client(config.symbol)
        self.bias_engine = H1BiasEngine(config)
        self.zone_engine = M15ZoneEngine(config)
        self.confirmation_engine = M5ConfirmationEngine(config)
        self.external_analyzer = ExternalAnalyzer(config)
        self.trade_executor = MT5TradeExecutor(config, self.mt5)
        self.scanner = M1SniperScanner(config)
        self.validator = OpenAIValidator(config)
        self.status = StatusWriter(config)
        self.notifier = PushoverNotifier(config)
        self.state = MarketState()
        self.output: OutputWriter | None = None

    def start(self) -> None:
        self.status.running("Starting bot and connecting to MT5")
        self.mt5.connect()
        chart_path = self.mt5.default_chart_bridge_path()
        self.output = OutputWriter(self.config, chart_path)
        self.status.running("Connected to MT5")
        self._notify_status("XAU bot started", "Connected to MT5 and watching market.")
        print(f"Connected to MT5. Watching {self.config.symbol}. Dry run: {self.config.dry_run}")

    def stop(self) -> None:
        self.mt5.shutdown()
        self.status.stopped("Bot stopped gracefully")
        self._notify_status("XAU bot stopped", "Bot stopped gracefully.", priority=-1)

    def run_forever(self) -> None:
        self.start()
        try:
            while True:
                self.run_once()
                time.sleep(self.config.m1_check_seconds)
        finally:
            self.stop()

    def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        self.status.running("Scanning market")
        self._refresh_h1_if_due(now)
        self._refresh_m15_if_due(now)
        self._refresh_m5_if_due(now)

        if self.state.bias is None or self.state.bias.bias == Bias.NEUTRAL:
            self._write_no_trade(
                "No directional H1 bias yet; standing aside.",
                current_price=self.state.bias.last_close if self.state.bias else None,
                zones=[],
            )
            self.status.running("No directional H1 bias yet")
            return
        if not self.state.zones:
            self._write_no_trade(
                f"{self.config.symbol} {self.state.bias.bias.value} bias, but no M15 zone.",
                current_price=self.state.bias.last_close,
                zones=[],
            )
            self.status.running("No M15 zone available")
            return

        m1 = self.mt5.rates("M1", self.config.m1_bars)
        current_price = float(m1.iloc[-1]["close"])
        direction_for_bias = _direction_for_bias(self.state.bias.bias)
        matching_zones = [
            zone for zone in self.state.zones if zone.direction == direction_for_bias
        ]
        if not matching_zones:
            self._write_no_trade(
                "No M15 setup zone aligns with the H1 bias.",
                current_price=current_price,
                zones=self.state.zones,
            )
            self.status.running("No M15 setup zone aligns with H1 bias")
            return

        wait_reasons: list[str] = []
        for zone in matching_zones:
            if self.state.m5 is None:
                wait_reasons.append("M5 confirmation data is not available yet.")
                continue
            confirmation = self.confirmation_engine.confirm(self.state.m5, zone)
            if not confirmation.confirmed:
                wait_reasons.append(
                    f"M5 not confirmed for {zone.low:.2f}-{zone.high:.2f}: "
                    f"{'; '.join(confirmation.reason)}"
                )
                continue
            targets = self.zone_engine.target_levels(
                self.state.m15,
                self.state.h1,
                zone.direction,
                float(m1.iloc[-1]["close"]),
            )
            trigger = self.scanner.scan(m1, zone, targets)
            if trigger is None:
                wait_reasons.append(
                    f"M1 sniper trigger incomplete for {zone.low:.2f}-{zone.high:.2f}; "
                    "waiting for liquidity sweep, rejection, CHOCH/BOS, and displacement."
                )
                continue

            external_analysis = self.external_analyzer.analyze()
            validation = self.validator.validate(self.state.bias, zone, confirmation, trigger)
            signal = Signal(
                symbol=self.config.symbol,
                bias=self.state.bias,
                zone=zone,
                confirmation=confirmation,
                trigger=trigger,
                validation=validation,
                external_analysis=external_analysis,
            )
            external_aligned = self.external_analyzer.aligns_with(
                external_analysis,
                trigger.direction,
            )
            if self.validator.should_emit(signal) and external_aligned:
                assert self.output is not None
                execution = self.trade_executor.execute(signal)
                signal = replace(signal, execution=execution)
                self.output.write_signal(signal)
                self.status.running(
                    "Signal emitted",
                    direction=trigger.direction.value,
                    execution_status=execution.status,
                )
                self._notify_signal(signal)
            else:
                external_note = ""
                if external_analysis is not None:
                    external_note = (
                        f" external={external_analysis.direction} "
                        f"bull={external_analysis.bull_score} "
                        f"bear={external_analysis.bear_score}"
                    )
                print(
                    f"Signal rejected: {validation.decision} "
                    f"confidence={validation.confidence:.2f}{external_note} "
                    f"notes={validation.risk_notes}"
                )
                self._write_no_trade(
                    "Candidate setup was rejected by validation or second-analyzer alignment.",
                    current_price=current_price,
                    zones=matching_zones,
                    external_analysis=external_analysis,
                )
                self.status.running("Candidate setup rejected")
            return

        reason = wait_reasons[0] if wait_reasons else "No complete entry trigger yet."
        self._write_no_trade(
            reason,
            current_price=current_price,
            zones=matching_zones,
        )
        self.status.running("Waiting for complete entry trigger", reason=reason)

    def _refresh_h1_if_due(self, now: datetime) -> None:
        if not _due(self.state.h1_updated_at, now, self.config.h1_check_minutes):
            return
        h1 = self.mt5.rates("H1", self.config.h1_bars)
        self.state.h1 = h1
        self.state.bias = self.bias_engine.analyze(h1)
        self.state.h1_updated_at = now
        print(
            f"H1 bias: {self.state.bias.bias.value} "
            f"close={self.state.bias.last_close:.2f} reason={'; '.join(self.state.bias.reason)}"
        )

    def _refresh_m15_if_due(self, now: datetime) -> None:
        if self.state.bias is None:
            return
        if not _due(self.state.m15_updated_at, now, self.config.m15_check_minutes):
            return
        m15 = self.mt5.rates("M15", self.config.m15_bars)
        self.state.m15 = m15
        self.state.zones = self.zone_engine.find_all_zones(m15)
        self.state.m15_updated_at = now
        if self.state.zones:
            zones = ", ".join(
                f"{zone.direction.value} {zone.low:.2f}-{zone.high:.2f}"
                for zone in self.state.zones
            )
            print(f"M15 zones: {zones}")
        else:
            print("M15 zones: none")

    def _refresh_m5_if_due(self, now: datetime) -> None:
        if not self.state.zones:
            return
        if not _due(self.state.m5_updated_at, now, self.config.m5_check_minutes):
            return
        self.state.m5 = self.mt5.rates("M5", self.config.m5_bars)
        self.state.m5_updated_at = now
        print("M5 confirmation data refreshed")

    def _write_no_trade(
        self,
        reason: str,
        current_price: float | None,
        zones: list[Zone],
        external_analysis: ExternalAnalysis | None = None,
    ) -> None:
        if self.output is None:
            return
        if external_analysis is None and self.config.external_analyzer_enabled:
            external_analysis = self.external_analyzer.analyze()
        self.output.write_no_trade(
            symbol=self.config.symbol,
            reason=reason,
            current_price=current_price,
            bias=self.state.bias,
            zones=zones,
            external_analysis=external_analysis,
        )
        self._notify_no_trade(reason)

    def _notify_signal(self, signal: Signal) -> None:
        result = self.notifier.notify_signal(signal)
        if self.notifier.enabled:
            print(f"Pushover signal alert: {result.message}")

    def _notify_status(self, title: str, message: str, priority: int | None = None) -> None:
        result = self.notifier.notify_status(title, message, priority=priority)
        if self.notifier.enabled:
            print(f"Pushover status alert: {result.message}")

    def _notify_no_trade(self, reason: str) -> None:
        result = self.notifier.notify_no_trade(
            f"{self.config.symbol} no trade",
            reason,
        )
        if self.notifier.enabled and self.config.pushover_alert_no_trade:
            print(f"Pushover no-trade alert: {result.message}")


def _due(last_run: datetime | None, now: datetime, minutes: int) -> bool:
    if last_run is None:
        return True
    return now - last_run >= timedelta(minutes=minutes)


def _direction_for_bias(bias: Bias) -> Direction | None:
    if bias == Bias.BULLISH:
        return Direction.BUY
    if bias == Bias.BEARISH:
        return Direction.SELL
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the XAUUSD multi-timeframe sniper bot.")
    parser.add_argument("--config", default=None, help="Path to config JSON.")
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit.")
    parser.add_argument("--no-openai", action="store_true", help="Disable OpenAI validation.")
    parser.add_argument("--live", action="store_true", help="Mark output as live mode in logs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.no_openai or args.live:
        config = BotConfig(
            **{
                **config.__dict__,
                "openai_enabled": False if args.no_openai else config.openai_enabled,
                "dry_run": False if args.live else config.dry_run,
            }
        )

    bot = XauSniperBot(config)
    with tee_console_to_log(config):
        try:
            if args.once:
                bot.start()
                try:
                    bot.run_once()
                finally:
                    bot.stop()
            else:
                bot.run_forever()
        except Exception as exc:
            bot.status.error(f"Bot crashed: {exc}")
            bot._notify_status("XAU bot crashed", str(exc), priority=1)
            raise


if __name__ == "__main__":
    main()

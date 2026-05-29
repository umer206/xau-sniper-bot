from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import BotConfig, load_config
from .confirmation import M5ConfirmationEngine
from .models import Bias, BiasSnapshot, Direction, Signal, Zone
from .mt5_client import MT5Client
from .openai_validator import OpenAIValidator
from .output import OutputWriter
from .sniper import M1SniperScanner
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
        self.scanner = M1SniperScanner(config)
        self.validator = OpenAIValidator(config)
        self.state = MarketState()
        self.output: OutputWriter | None = None

    def start(self) -> None:
        self.mt5.connect()
        chart_path = self.mt5.default_chart_bridge_path()
        self.output = OutputWriter(self.config, chart_path)
        print(f"Connected to MT5. Watching {self.config.symbol}. Dry run: {self.config.dry_run}")

    def stop(self) -> None:
        self.mt5.shutdown()

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
        self._refresh_h1_if_due(now)
        self._refresh_m15_if_due(now)
        self._refresh_m5_if_due(now)

        if self.state.bias is None or self.state.bias.bias == Bias.NEUTRAL:
            print("No directional H1 bias yet; standing aside.")
            return
        if not self.state.zones:
            print(f"{self.config.symbol} {self.state.bias.bias.value} bias, but no M15 zone.")
            return

        m1 = self.mt5.rates("M1", self.config.m1_bars)
        direction_for_bias = _direction_for_bias(self.state.bias.bias)
        for zone in self.state.zones:
            if zone.direction != direction_for_bias:
                continue
            if self.state.m5 is None:
                continue
            confirmation = self.confirmation_engine.confirm(self.state.m5, zone)
            if not confirmation.confirmed:
                continue
            targets = self.zone_engine.target_levels(
                self.state.m15,
                self.state.h1,
                zone.direction,
                float(m1.iloc[-1]["close"]),
            )
            trigger = self.scanner.scan(m1, zone, targets)
            if trigger is None:
                continue

            validation = self.validator.validate(self.state.bias, zone, confirmation, trigger)
            signal = Signal(
                symbol=self.config.symbol,
                bias=self.state.bias,
                zone=zone,
                confirmation=confirmation,
                trigger=trigger,
                validation=validation,
            )
            if self.validator.should_emit(signal):
                assert self.output is not None
                self.output.write_signal(signal)
            else:
                print(
                    f"Signal rejected: {validation.decision} "
                    f"confidence={validation.confidence:.2f} notes={validation.risk_notes}"
                )
            break

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
        self.state.zones = self.zone_engine.find_zones(m15, self.state.bias)
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
    if args.once:
        bot.start()
        try:
            bot.run_once()
        finally:
            bot.stop()
    else:
        bot.run_forever()


if __name__ == "__main__":
    main()

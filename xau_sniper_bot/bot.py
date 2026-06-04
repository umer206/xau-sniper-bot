from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pandas as pd

from .analysis_framework import AnalysisFrameworkEngine, FrameworkAnalysis
from .config import BotConfig, load_config
from .confirmation import M5ConfirmationEngine
from .external_analyzer import ExternalAnalyzer
from .execution import MT5TradeExecutor
from .liquidity import LiquidityAnalyzer
from .logging_setup import tee_console_to_log
from .models import (
    Bias,
    BiasSnapshot,
    ConfirmationSnapshot,
    Direction,
    ExternalAnalysis,
    MarketContext,
    Signal,
    Zone,
)
from .mt5_client import MT5Client
from .notifier import PushoverNotifier
from .openai_validator import OpenAIValidator
from .output import OutputWriter
from .sniper import M1SniperScanner
from .status import StatusWriter
from .structure import H1BiasEngine, M15ZoneEngine


@dataclass
class MarketState:
    w1: pd.DataFrame | None = None
    d1: pd.DataFrame | None = None
    h4: pd.DataFrame | None = None
    h1: pd.DataFrame | None = None
    m15: pd.DataFrame | None = None
    m5: pd.DataFrame | None = None
    bias: BiasSnapshot | None = None
    zones: list[Zone] | None = None
    framework_analysis: FrameworkAnalysis | None = None
    framework_updated_at: datetime | None = None
    framework_feed_updated_at: datetime | None = None
    dxy_frames: dict[str, pd.DataFrame] | None = None
    dxy_error: str | None = None
    h1_updated_at: datetime | None = None
    m15_updated_at: datetime | None = None
    m5_updated_at: datetime | None = None


class XauSniperBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.mt5 = MT5Client(config.symbol)
        self.framework_analyzer = AnalysisFrameworkEngine(config)
        self.bias_engine = H1BiasEngine(config)
        self.zone_engine = M15ZoneEngine(config)
        self.confirmation_engine = M5ConfirmationEngine(config)
        self.external_analyzer = ExternalAnalyzer(config)
        self.trade_executor = MT5TradeExecutor(config, self.mt5)
        self.liquidity_analyzer = LiquidityAnalyzer(config)
        self.scanner = M1SniperScanner(config)
        self.validator = OpenAIValidator(config)
        self.status = StatusWriter(config)
        self.notifier = PushoverNotifier(config)
        self.state = MarketState()
        self.output: OutputWriter | None = None
        self._last_scan_summary_at: datetime | None = None
        self._last_scan_summary_key: str | None = None

    def start(self) -> None:
        self.status.running("Starting bot and connecting to MT5")
        self.mt5.connect()
        chart_path = self.mt5.default_chart_bridge_path()
        self.output = OutputWriter(self.config, chart_path)
        self.status.running("Connected to MT5")
        self._notify_status(
            "XAU bot started",
            (
                f"Connected to MT5 and watching {self.config.symbol}.\n"
                f"Mode: {'DRY-RUN' if self.config.dry_run else 'LIVE'}\n"
                "Full scan/setup summaries will follow after analysis."
            ),
        )
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
        self._refresh_framework_if_due(now)
        self._refresh_m5_if_due(now)

        if self.state.bias is None or self.state.bias.bias == Bias.NEUTRAL:
            self._write_no_trade(
                "No directional top-down bias yet; standing aside.",
                current_price=self.state.bias.last_close if self.state.bias else None,
                zones=[],
            )
            self.status.running("No directional top-down bias yet")
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
        current_spread = self.mt5.spread()
        market_context = self._market_context(
            m1,
            direction_for_bias,
            now,
            current_spread,
        )
        active_zones = self._active_zones(self.state.zones, now)
        continuation_confirmations: dict[str, ConfirmationSnapshot] = {}
        continuation = self._continuation_candidate(
            direction_for_bias,
            current_price,
        )
        if continuation is not None:
            continuation_zone, continuation_confirmation = continuation
            active_zones = active_zones + [continuation_zone]
            continuation_confirmations[_zone_key(continuation_zone)] = (
                continuation_confirmation
            )
        m1_continuation = self._m1_continuation_candidate(
            m1,
            direction_for_bias,
            current_price,
        )
        if m1_continuation is not None:
            zone, confirmation = m1_continuation
            active_zones = active_zones + [zone]
            continuation_confirmations[_zone_key(zone)] = confirmation

        if not active_zones:
            self._write_no_trade(
                (
                    "No fresh M15 setup zones or M5 continuation zones remain; "
                    "old zones are ignored after "
                    f"{self.config.zone_expire_after_hours:.0f}h."
                ),
                current_price=current_price,
                zones=[],
                market_context=market_context,
            )
            self.status.running("No fresh M15 setup zones remain")
            return
        matching_zones = [
            zone for zone in active_zones if zone.direction == direction_for_bias
        ]
        matching_zones = self._sort_zones_by_distance(matching_zones, current_price)
        if not matching_zones:
            self._write_no_trade(
                "No M15 setup zone aligns with the H1 bias.",
                current_price=current_price,
                zones=active_zones,
                market_context=market_context,
            )
            self.status.running("No M15 setup zone aligns with H1 bias")
            return

        wait_reasons: list[str] = []
        for zone in matching_zones:
            if self.state.m5 is None:
                wait_reasons.append("M5 confirmation data is not available yet.")
                continue
            confirmation = continuation_confirmations.get(_zone_key(zone))
            if confirmation is None:
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
                setup_name = (
                    "M1 continuation trigger"
                    if zone.setup_type == "continuation"
                    else "M1 sniper trigger"
                )
                wait_reasons.append(
                    f"{setup_name} incomplete for {zone.low:.2f}-{zone.high:.2f}; "
                    "waiting for liquidity sweep, rejection, CHOCH/BOS, and displacement."
                )
                continue

            framework_block = self._framework_signal_block(trigger.direction)
            if framework_block:
                wait_reasons.append(framework_block)
                continue

            liquidity = self.liquidity_analyzer.analyze(
                m1=m1,
                m5=self.state.m5,
                m15=self.state.m15,
                direction=zone.direction,
                trigger=trigger,
                spread=current_spread,
                now=now,
            )
            if not liquidity.passed:
                wait_reasons.append(
                    "Liquidity filter failed: " + "; ".join(liquidity.reason)
                )
                continue

            external_analysis = self.external_analyzer.analyze(use_groq=True)
            validation = self.validator.validate(
                self.state.bias,
                zone,
                confirmation,
                trigger,
                liquidity,
            )
            signal = Signal(
                symbol=self.config.symbol,
                bias=self.state.bias,
                zone=zone,
                confirmation=confirmation,
                trigger=trigger,
                validation=validation,
                external_analysis=external_analysis,
                liquidity=liquidity,
                framework_analysis=_framework_payload(self.state.framework_analysis),
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
                    market_context=market_context,
                )
                self.status.running("Candidate setup rejected")
            return

        reason = wait_reasons[0] if wait_reasons else "No complete entry trigger yet."
        self._write_no_trade(
            reason,
            current_price=current_price,
            zones=matching_zones,
            market_context=market_context,
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

    def _refresh_framework_if_due(self, now: datetime) -> None:
        if not self.config.analysis_framework_enabled:
            return
        if self.state.h1 is None or self.state.m15 is None:
            return
        refresh_feeds = _due(
            self.state.framework_feed_updated_at,
            now,
            self.config.h1_check_minutes,
        )
        previous_analysis = self.state.framework_analysis

        gold_frames: dict[str, pd.DataFrame] = {
            "H1": self.state.h1,
            "M15": self.state.m15,
        }
        macro_specs = (
            ("W1", "w1", self.config.w1_bars),
            ("D1", "d1", self.config.d1_bars),
            ("H4", "h4", self.config.h4_bars),
        )
        for timeframe, state_attr, bars in macro_specs:
            frame = getattr(self.state, state_attr)
            if refresh_feeds or frame is None:
                frame = self._safe_rates(self.config.symbol, timeframe, bars)
            if frame is not None:
                setattr(self.state, state_attr, frame)
                gold_frames[timeframe] = frame
        dxy_frames, dxy_error = self._dxy_frames(refresh_feeds)

        try:
            analysis = self.framework_analyzer.analyze(
                gold_frames,
                dxy_frames=dxy_frames,
                dxy_error=dxy_error,
                now=now,
            )
        except Exception as exc:
            print(f"Framework analysis failed: {exc}")
            return

        self.state.framework_analysis = analysis
        self.state.framework_updated_at = now
        if refresh_feeds:
            self.state.framework_feed_updated_at = now
        self.state.bias = analysis.to_bias_snapshot()
        if refresh_feeds or _framework_blocks_changed(previous_analysis, analysis):
            print(
                f"Framework bias: {analysis.bias} "
                f"score={analysis.bias_score:.1f} "
                f"confidence={analysis.confidence:.0f}% "
                f"tradeable={analysis.tradeable} "
                f"blocks={'; '.join(analysis.hard_blocks) or 'none'}"
            )

    def _refresh_m5_if_due(self, now: datetime) -> None:
        if not self.state.zones:
            return
        if not _due(self.state.m5_updated_at, now, self.config.m5_check_minutes):
            return
        self.state.m5 = self.mt5.rates("M5", self.config.m5_bars)
        self.state.m5_updated_at = now
        print("M5 confirmation data refreshed")

    def _safe_rates(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
    ) -> pd.DataFrame | None:
        try:
            if symbol == self.config.symbol:
                return self.mt5.rates(timeframe, bars)
            return self.mt5.rates_for_symbol(symbol, timeframe, bars)
        except Exception as exc:
            print(f"{symbol} {timeframe} unavailable for framework analysis: {exc}")
            return None

    def _dxy_frames(self, refresh_feeds: bool) -> tuple[dict[str, pd.DataFrame], str | None]:
        if not self.config.dxy_enabled:
            return {}, None
        if not refresh_feeds and self.state.dxy_frames is not None:
            return self.state.dxy_frames, self.state.dxy_error
        frames: dict[str, pd.DataFrame] = {}
        errors: list[str] = []
        for timeframe, bars in (
            ("W1", self.config.w1_bars),
            ("D1", self.config.d1_bars),
            ("H4", self.config.h4_bars),
            ("H1", self.config.h1_bars),
            ("M15", self.config.m15_bars),
        ):
            frame = self._safe_rates(self.config.dxy_symbol, timeframe, bars)
            if frame is None:
                errors.append(f"{self.config.dxy_symbol} {timeframe} unavailable")
            else:
                frames[timeframe] = frame
        self.state.dxy_frames = frames
        self.state.dxy_error = "; ".join(errors) if errors and not frames else None
        return frames, self.state.dxy_error

    def _write_no_trade(
        self,
        reason: str,
        current_price: float | None,
        zones: list[Zone],
        external_analysis: ExternalAnalysis | None = None,
        market_context: MarketContext | None = None,
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
            market_context=market_context,
            framework_analysis=_framework_payload(self.state.framework_analysis),
        )
        self._notify_scan_summary(
            reason,
            current_price,
            zones,
            external_analysis,
            market_context,
        )

    def _market_context(
        self,
        m1: pd.DataFrame,
        direction: Direction | None,
        now: datetime,
        spread: float,
    ) -> MarketContext | None:
        if direction is None or self.state.m15 is None:
            return None
        return self.liquidity_analyzer.market_context(
            m1=m1,
            m15=self.state.m15,
            direction=direction,
            spread=spread,
            now=now,
        )

    def _framework_signal_block(self, direction: Direction) -> str | None:
        if not self.config.analysis_framework_enabled:
            return None
        analysis = self.state.framework_analysis
        if analysis is None:
            return "Top-down framework analysis is not available yet."
        if analysis.allows_direction(direction):
            return None

        expected = "LONG" if direction == Direction.BUY else "SHORT"
        if analysis.hard_blocks:
            return "Framework hard block: " + "; ".join(analysis.hard_blocks[:3])
        if analysis.direction != expected:
            return (
                f"Framework direction is {analysis.direction or 'NO TRADE'}, "
                f"not {expected}."
            )
        if not analysis.tradeable:
            return (
                f"Framework bias is {analysis.bias}; waiting for moderate/strong "
                "top-down confluence before execution."
            )
        return "Framework gate did not approve this setup."

    def _continuation_candidate(
        self,
        direction: Direction | None,
        current_price: float,
    ) -> tuple[Zone, ConfirmationSnapshot] | None:
        if direction is None or self.state.m5 is None:
            return None
        return self.confirmation_engine.continuation_candidate(
            self.state.m5,
            direction,
            current_price,
        )

    def _m1_continuation_candidate(
        self,
        m1: pd.DataFrame,
        direction: Direction | None,
        current_price: float,
    ) -> tuple[Zone, ConfirmationSnapshot] | None:
        if direction is None:
            return None
        zone = self.scanner.continuation_zone(m1, direction, current_price)
        if zone is None:
            return None
        confirmation = ConfirmationSnapshot(
            symbol=self.config.symbol,
            timeframe="M1",
            direction=direction,
            confirmed=True,
            updated_at=datetime.now(timezone.utc),
            reason=[
                f"{zone.timeframe} continuation zone is active",
                "Using local continuation pullback because M15 retest is far",
            ],
        )
        return zone, confirmation

    def _active_zones(self, zones: list[Zone], now: datetime) -> list[Zone]:
        expire_after = self.config.zone_expire_after_hours
        if expire_after <= 0:
            return zones
        return [zone for zone in zones if _zone_age_hours(zone, now) < expire_after]

    def _sort_zones_by_distance(
        self,
        zones: list[Zone],
        current_price: float,
    ) -> list[Zone]:
        return sorted(
            zones,
            key=lambda zone: (_zone_distance(zone, current_price), -zone.strength),
        )

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

    def _notify_scan_summary(
        self,
        reason: str,
        current_price: float | None,
        zones: list[Zone],
        external_analysis: ExternalAnalysis | None,
        market_context: MarketContext | None,
    ) -> None:
        if not self._should_send_scan_summary(
            reason,
            current_price,
            zones,
            external_analysis,
        ):
            return
        result = self.notifier.notify_scan_summary(
            symbol=self.config.symbol,
            reason=reason,
            current_price=current_price,
            bias=self.state.bias,
            zones=zones,
            external_analysis=external_analysis,
            market_context=market_context,
            framework_analysis=_framework_payload(self.state.framework_analysis),
        )
        if self.notifier.enabled and self.config.pushover_alert_scan_summary:
            print(f"Pushover scan summary alert: {result.message}")

    def _should_send_scan_summary(
        self,
        reason: str,
        current_price: float | None,
        zones: list[Zone],
        external_analysis: ExternalAnalysis | None,
    ) -> bool:
        interval = self.config.pushover_scan_summary_min_interval_minutes
        if interval <= 0:
            return True
        now = datetime.now(timezone.utc)
        summary_key = _scan_summary_key(
            self.state.bias,
            reason,
            current_price,
            zones,
            external_analysis,
        )
        if summary_key != self._last_scan_summary_key:
            self._last_scan_summary_key = summary_key
            self._last_scan_summary_at = now
            return True
        if self._last_scan_summary_at is None:
            self._last_scan_summary_at = now
            return True
        if now - self._last_scan_summary_at >= timedelta(minutes=interval):
            self._last_scan_summary_at = now
            return True
        return False


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


def _zone_age_hours(zone: Zone, now: datetime) -> float:
    anchor = zone.anchor_time
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return max((now - anchor.astimezone(timezone.utc)).total_seconds() / 3600.0, 0.0)


def _zone_distance(zone: Zone, current_price: float) -> float:
    if zone.low <= current_price <= zone.high:
        return 0.0
    if current_price > zone.high:
        return current_price - zone.high
    return zone.low - current_price


def _zone_key(zone: Zone) -> str:
    return (
        f"{zone.setup_type}:{zone.direction.value}:"
        f"{zone.timeframe}:{zone.low:.2f}:{zone.high:.2f}"
    )


def _framework_payload(analysis: FrameworkAnalysis | None) -> dict | None:
    return analysis.to_dict() if analysis is not None else None


def _framework_blocks_changed(
    previous: FrameworkAnalysis | None,
    current: FrameworkAnalysis,
) -> bool:
    if previous is None:
        return True
    return previous.hard_blocks != current.hard_blocks or previous.tradeable != current.tradeable


def _scan_summary_key(
    bias: BiasSnapshot | None,
    reason: str,
    current_price: float | None,
    zones: list[Zone],
    external_analysis: ExternalAnalysis | None,
) -> str:
    bias_value = bias.bias.value if bias else "none"
    zone_key = "|".join(
        f"{zone.direction.value}:{zone.low:.2f}:{zone.high:.2f}" for zone in zones[:3]
    )
    external_key = external_analysis.direction if external_analysis else "none"
    price_bucket = "none" if current_price is None else f"{current_price // 5:.0f}"
    return "|".join([bias_value, reason, price_bucket, zone_key, external_key])


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

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .config import BotConfig
from .models import BiasSnapshot, Direction, ExternalAnalysis, MarketContext, Signal, Zone
from .output import format_no_trade_setup, format_trade_setup


PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_MESSAGE_LIMIT = 1024


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    message: str
    status_code: int | None = None


class PushoverNotifier:
    def __init__(self, config: BotConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.pushover_enabled

    def notify_signal(self, signal: Signal) -> NotificationResult:
        if not self.config.pushover_alert_signals:
            return NotificationResult(False, "Signal alerts disabled")

        direction = "LONG" if signal.trigger.direction == Direction.BUY else "SHORT"
        execution = signal.execution.status if signal.execution else "not_attempted"
        title = f"{signal.symbol} {direction} setup"
        message = _truncate(
            "\n".join(
                [
                    f"{signal.symbol} {direction}",
                    f"Entry: {signal.trigger.entry_price:.2f}",
                    f"SL: {signal.trigger.stop_loss:.2f}",
                    f"TP1: {signal.trigger.target_1.price:.2f}",
                    f"TP2: {signal.trigger.target_2.price:.2f}",
                    f"R:R: 1:{signal.trigger.risk_reward:.1f}",
                    f"Second AI: {_external_summary(signal)}",
                    f"Execution: {execution}",
                    "",
                    format_trade_setup(signal),
                ]
            )
        )
        return self.send(title, message, priority=self.config.pushover_priority)

    def notify_no_trade(self, title: str, message: str) -> NotificationResult:
        if not self.config.pushover_alert_no_trade:
            return NotificationResult(False, "No-trade alerts disabled")
        return self.send(title, _truncate(message), priority=-1)

    def notify_scan_summary(
        self,
        *,
        symbol: str,
        reason: str,
        current_price: float | None,
        bias: BiasSnapshot | None,
        zones: list[Zone],
        external_analysis: ExternalAnalysis | None,
        market_context: MarketContext | None = None,
        framework_analysis: dict | None = None,
    ) -> NotificationResult:
        if not self.config.pushover_alert_scan_summary:
            return NotificationResult(False, "Scan summary alerts disabled")
        message = format_no_trade_setup(
            symbol=symbol,
            reason=reason,
            current_price=current_price,
            bias=bias,
            zones=zones,
            external_analysis=external_analysis,
            market_context=market_context,
            framework_analysis=framework_analysis,
            zone_stale_after_hours=self.config.zone_stale_after_hours,
            zone_expire_after_hours=self.config.zone_expire_after_hours,
            zone_near_threshold_points=self.config.zone_near_threshold_points,
        )
        return self.send(f"{symbol} scan summary", _truncate(message), priority=-1)

    def notify_status(
        self,
        title: str,
        message: str,
        priority: int | None = None,
    ) -> NotificationResult:
        if not self.config.pushover_alert_status:
            return NotificationResult(False, "Status alerts disabled")
        chosen_priority = self.config.pushover_priority if priority is None else priority
        return self.send(title, _truncate(message), priority=chosen_priority)

    def send(
        self,
        title: str,
        message: str,
        priority: int | None = None,
    ) -> NotificationResult:
        if not self.enabled:
            return NotificationResult(False, "Pushover disabled")

        token = self.config.pushover_app_token or os.getenv("PUSHOVER_APP_TOKEN", "")
        user = self.config.pushover_user_key or os.getenv("PUSHOVER_USER_KEY", "")
        if not token or not user:
            return NotificationResult(False, "Missing Pushover token or user key")

        payload = {
            "token": token,
            "user": user,
            "title": title,
            "message": message,
            "priority": str(self.config.pushover_priority if priority is None else priority),
        }
        if self.config.pushover_device:
            payload["device"] = self.config.pushover_device
        if self.config.pushover_sound:
            payload["sound"] = self.config.pushover_sound

        data = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            PUSHOVER_API_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                status = int(parsed.get("status", 0))
                if status == 1:
                    return NotificationResult(True, "Pushover notification sent", response.status)
                errors = parsed.get("errors", ["Unknown Pushover error"])
                return NotificationResult(False, "; ".join(errors), response.status)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return NotificationResult(False, f"Pushover HTTP {exc.code}: {body}", exc.code)
        except Exception as exc:
            return NotificationResult(False, f"Pushover failed: {exc}")


def _external_summary(signal: Signal) -> str:
    if signal.external_analysis is None:
        return "disabled"
    return (
        f"{signal.external_analysis.direction} "
        f"bull={signal.external_analysis.bull_score} "
        f"bear={signal.external_analysis.bear_score}"
    )


def _truncate(message: str) -> str:
    if len(message) <= PUSHOVER_MESSAGE_LIMIT:
        return message
    suffix = "\n...truncated"
    return message[: PUSHOVER_MESSAGE_LIMIT - len(suffix)] + suffix

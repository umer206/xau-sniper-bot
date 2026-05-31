from __future__ import annotations

from typing import Any

from .config import BotConfig
from .models import Direction, ExecutionResult, Signal
from .mt5_client import MT5Client
from .trade_lock import TradeLock


class MT5TradeExecutor:
    def __init__(self, config: BotConfig, mt5_client: MT5Client) -> None:
        self.config = config
        self.mt5_client = mt5_client
        self.trade_lock = TradeLock(config)

    def execute(self, signal: Signal) -> ExecutionResult:
        if self.config.dry_run:
            return ExecutionResult(
                status="dry_run",
                message="Dry run enabled; MT5 order was not sent.",
                volume=self.config.trade_volume,
                target_used=self._target_used(),
            )
        if not self.config.trade_execution_enabled:
            return ExecutionResult(
                status="disabled",
                message="trade_execution_enabled is false; MT5 order was not sent.",
            )

        setup_id = self.trade_lock.setup_id(signal)
        locked, lock = self.trade_lock.is_locked(setup_id)
        if locked:
            created_at = lock.get("created_at", "unknown") if lock else "unknown"
            return ExecutionResult(
                status="locked",
                message=f"Duplicate setup blocked by trade lock {setup_id} from {created_at}.",
                target_used=self._target_used(),
            )

        mt5 = self.mt5_client.mt5
        symbol = signal.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return self._failed(f"No tick available for {symbol}: {mt5.last_error()}")

        spread = float(tick.ask) - float(tick.bid)
        if spread > self.config.trade_max_spread:
            return self._failed(
                f"Spread {spread:.2f} is above max {self.config.trade_max_spread:.2f}."
            )

        if not self.config.trade_allow_existing_position:
            positions = mt5.positions_get(symbol=symbol)
            if positions:
                return self._failed(f"Existing {symbol} position found; duplicate blocked.")

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return self._failed(f"No symbol info for {symbol}: {mt5.last_error()}")

        volume = _normalize_volume(
            self.config.trade_volume,
            float(getattr(symbol_info, "volume_min", self.config.trade_volume)),
            float(getattr(symbol_info, "volume_max", self.config.trade_volume)),
            float(getattr(symbol_info, "volume_step", self.config.trade_volume)),
        )
        order_type = (
            mt5.ORDER_TYPE_BUY
            if signal.trigger.direction == Direction.BUY
            else mt5.ORDER_TYPE_SELL
        )
        price = float(tick.ask if signal.trigger.direction == Direction.BUY else tick.bid)
        target = (
            signal.trigger.target_2
            if self.config.trade_take_profit_target == 2
            else signal.trigger.target_1
        )
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": round(signal.trigger.stop_loss, 2),
            "tp": round(target.price, 2),
            "deviation": self.config.trade_deviation_points,
            "magic": self.config.trade_magic,
            "comment": self.config.trade_comment,
            "type_time": mt5.ORDER_TIME_GTC,
        }

        check = mt5.order_check(dict(request))
        if check is None:
            return self._failed(f"MT5 order_check failed: {mt5.last_error()}")

        check_retcode = int(getattr(check, "retcode", -1))
        accepted_check_codes = {
            0,
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)),
        }
        if check_retcode not in accepted_check_codes:
            comment = getattr(check, "comment", "")
            return self._failed(f"MT5 order_check rejected: {check_retcode} {comment}")

        result = self._send_with_filling_fallback(mt5, request)
        if result is None:
            return self._failed(f"MT5 order_send failed: {mt5.last_error()}")

        retcode = int(getattr(result, "retcode", -1))
        success_codes = {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)),
        }
        if retcode not in success_codes:
            return ExecutionResult(
                status="rejected",
                message=f"MT5 rejected order: {retcode} {getattr(result, 'comment', '')}",
                retcode=retcode,
                price=price,
                volume=volume,
                target_used=self._target_used(),
            )

        execution = ExecutionResult(
            status="placed",
            message="MT5 order placed successfully.",
            order_id=int(getattr(result, "order", 0) or 0),
            retcode=retcode,
            price=price,
            volume=volume,
            target_used=self._target_used(),
        )
        self.trade_lock.record(setup_id, signal, execution.status)
        return execution

    def _send_with_filling_fallback(self, mt5: Any, request: dict[str, Any]) -> Any:
        modes = self._filling_modes(mt5)
        for mode in modes:
            result = mt5.order_send({**request, "type_filling": mode})
            if result is None:
                continue
            retcode = int(getattr(result, "retcode", -1))
            invalid_fill = int(getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030))
            if retcode != invalid_fill:
                return result
        return None

    def _filling_modes(self, mt5: Any) -> list[int]:
        requested = self.config.trade_filling_mode.lower()
        known = {
            "fok": getattr(mt5, "ORDER_FILLING_FOK", None),
            "ioc": getattr(mt5, "ORDER_FILLING_IOC", None),
            "return": getattr(mt5, "ORDER_FILLING_RETURN", None),
        }
        if requested != "auto":
            mode = known.get(requested)
            return [mode] if mode is not None else []
        return [mode for mode in known.values() if mode is not None]

    def _target_used(self) -> str:
        return "target_2" if self.config.trade_take_profit_target == 2 else "target_1"

    def _failed(self, message: str) -> ExecutionResult:
        return ExecutionResult(status="failed", message=message)


def _normalize_volume(volume: float, minimum: float, maximum: float, step: float) -> float:
    if step <= 0:
        step = minimum
    volume = max(minimum, min(volume, maximum))
    steps = round((volume - minimum) / step)
    normalized = minimum + (steps * step)
    return round(max(minimum, min(normalized, maximum)), 2)

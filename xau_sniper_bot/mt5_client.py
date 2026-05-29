from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


TIMEFRAMES = {
    "H1": "TIMEFRAME_H1",
    "M15": "TIMEFRAME_M15",
    "M5": "TIMEFRAME_M5",
    "M1": "TIMEFRAME_M1",
}


@dataclass
class MT5Client:
    symbol: str

    def __post_init__(self) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError(
                "MetaTrader5 package is not installed. Run `pip install -r requirements.txt`."
            ) from exc
        self.mt5 = mt5

    def connect(self) -> None:
        if not self.mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {self.mt5.last_error()}")
        selected = self.mt5.symbol_select(self.symbol, True)
        if not selected:
            raise RuntimeError(f"Could not select symbol {self.symbol}: {self.mt5.last_error()}")

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def rates(self, timeframe: str, bars: int) -> pd.DataFrame:
        mt5_timeframe = getattr(self.mt5, TIMEFRAMES[timeframe])
        rates = self.mt5.copy_rates_from_pos(self.symbol, mt5_timeframe, 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No {timeframe} rates for {self.symbol}: {self.mt5.last_error()}")

        frame = pd.DataFrame(rates)
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        return frame.reset_index(drop=True)

    def last_price(self) -> float:
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {self.symbol}: {self.mt5.last_error()}")
        bid = float(tick.bid)
        ask = float(tick.ask)
        return (bid + ask) / 2.0

    def default_chart_bridge_path(self, filename: str = "xau_sniper_signal.json") -> Path | None:
        info: Any = self.mt5.terminal_info()
        if info is None:
            return None
        data_path = getattr(info, "data_path", None)
        if not data_path:
            return None
        return Path(data_path) / "MQL5" / "Files" / filename


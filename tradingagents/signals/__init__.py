"""信号模块。"""

from .generator import SignalGenerator, load_watchlist
from .recorder import SignalRecorder
from .types import TradingSignal, SignalRecord

__all__ = [
    "TradingSignal",
    "SignalRecord",
    "SignalGenerator",
    "SignalRecorder",
    "load_watchlist",
]
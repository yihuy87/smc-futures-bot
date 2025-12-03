# binance/ohlc_buffer.py
# Menyimpan buffer OHLC 5m per symbol dari WebSocket Binance.

from collections import deque
from typing import Deque, Dict, List, TypedDict


class Candle(TypedDict):
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool


class OHLCBufferManager:
    """
    Manager buffer OHLC per symbol (5m).
    Disuplai dari stream WebSocket kline_5m (Binance Futures).
    """

    def __init__(self, max_candles: int = 300) -> None:
        self.max_candles = max_candles
        self._buffers: Dict[str, Deque[Candle]] = {}

    def _get_buffer(self, symbol: str) -> Deque[Candle]:
        if symbol not in self._buffers:
            self._buffers[symbol] = deque(maxlen=self.max_candles)
        return self._buffers[symbol]

    def update_from_kline(self, symbol: str, kline: dict) -> None:
        """
        Update buffer dari objek kline WS Binance.
        Kline contoh field:
        {
          "t": 123400000,     # Kline start time
          "T": 123460000,     # Kline close time
          "o": "0.0010",
          "h": "0.0025",
          "l": "0.0015",
          "c": "0.0020",
          "v": "1000",
          "x": true,          # Is this kline closed?
          ...
        }
        """
        buf = self._get_buffer(symbol)

        open_time = int(kline.get("t", 0))
        close_time = int(kline.get("T", 0))
        try:
            o = float(kline.get("o", "0"))
            h = float(kline.get("h", "0"))
            l = float(kline.get("l", "0"))
            c = float(kline.get("c", "0"))
            v = float(kline.get("v", "0"))
        except ValueError:
            return

        closed = bool(kline.get("x", False))

        candle: Candle = {
            "open_time": open_time,
            "close_time": close_time,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "closed": closed,
        }

        if not buf:
            buf.append(candle)
            return

        # jika open_time sama dengan candle terakhir → update/replace
        last = buf[-1]
        if last["open_time"] == open_time:
            buf[-1] = candle
        else:
            buf.append(candle)

    def get_candles(self, symbol: str) -> List[Candle]:
        """
        Return list candle (copy) untuk symbol. Bisa kosong.
        """
        buf = self._get_buffer(symbol)
        return list(buf)

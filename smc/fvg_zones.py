# smc/fvg_zones.py
# Deteksi FVG (Fair Value Gap) di sekitar displacement.

from typing import List, Optional, Dict
from binance.ohlc_buffer import Candle


def detect_fvg_around(
    candles: List[Candle],
    center_index: int,
    window: int = 3,
) -> Dict[str, Optional[float]]:
    """
    Deteksi FVG di sekitar candle 'center_index'.

    Menggunakan pola 3-candle klasik:
    - Bullish FVG: low[2] > high[0]
    - Bearish FVG: high[2] < low[0]

    Return:
    {
        "has_fvg": bool,
        "low": float | None,
        "high": float | None,
        "direction": "bullish" | "bearish" | None
    }
    """
    n = len(candles)
    if n < 3 or center_index is None:
        return {"has_fvg": False, "low": None, "high": None, "direction": None}

    start = max(0, center_index - window)
    end = min(n - 2, center_index + window)

    best_bull_mid_dist = None
    best_bear_mid_dist = None

    best_bull = (None, None)  # (fvg_low, fvg_high)
    best_bear = (None, None)

    last_close = candles[-1]["close"]

    for i in range(start, end):
        # i, i+1, i+2
        if i + 2 >= n:
            break
        c0 = candles[i]
        c2 = candles[i + 2]

        # Bullish FVG: c2.low > c0.high
        if c2["low"] > c0["high"]:
            fvg_low = c0["high"]
            fvg_high = c2["low"]
            mid = 0.5 * (fvg_low + fvg_high)
            dist = abs(last_close - mid)
            if best_bull_mid_dist is None or dist < best_bull_mid_dist:
                best_bull_mid_dist = dist
                best_bull = (fvg_low, fvg_high)

        # Bearish FVG: c2.high < c0.low
        if c2["high"] < c0["low"]:
            fvg_high = c0["low"]
            fvg_low = c2["high"]
            mid = 0.5 * (fvg_low + fvg_high)
            dist = abs(last_close - mid)
            if best_bear_mid_dist is None or dist < best_bear_mid_dist:
                best_bear_mid_dist = dist
                best_bear = (fvg_low, fvg_high)

    # pilih yang paling dekat dengan harga terakhir
    chosen_dir: Optional[str] = None
    fvg_low: Optional[float] = None
    fvg_high: Optional[float] = None

    if best_bull_mid_dist is not None or best_bear_mid_dist is not None:
        if best_bear_mid_dist is None or (
            best_bull_mid_dist is not None and best_bull_mid_dist <= best_bear_mid_dist
        ):
            chosen_dir = "bullish"
            fvg_low, fvg_high = best_bull
        else:
            chosen_dir = "bearish"
            fvg_low, fvg_high = best_bear

    if chosen_dir is None or fvg_low is None or fvg_high is None or fvg_high <= fvg_low:
        return {"has_fvg": False, "low": None, "high": None, "direction": None}

    return {
        "has_fvg": True,
        "low": float(fvg_low),
        "high": float(fvg_high),
        "direction": chosen_dir,
  }

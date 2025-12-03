# smc/fvg_zones.py
# Deteksi FVG (Fair Value Gap) di sekitar displacement + penilaian kualitas.

from typing import List, Optional, Dict
from binance.ohlc_buffer import Candle


def detect_fvg_around(
    candles: List[Candle],
    center_index: int,
    window: int = 3,
    max_width_pct: float = 0.008,
    max_dist_pct: float = 0.006,
) -> Dict[str, Optional[object]]:
    """
    Deteksi FVG di sekitar candle 'center_index'.

    Pola 3-candle klasik:
    - Bullish FVG: low[2] > high[0]
    - Bearish FVG: high[2] < low[0]

    Selain deteksi, juga menilai kualitas:
    - lebar FVG tidak terlalu besar
    - jarak mid FVG ke harga terakhir tidak terlalu jauh

    Return:
    {
        "has_fvg": bool,
        "low": float | None,
        "high": float | None,
        "direction": "bullish" | "bearish" | None,
        "quality_ok": bool
    }
    """
    n = len(candles)
    if n < 3 or center_index is None:
        return {
            "has_fvg": False,
            "low": None,
            "high": None,
            "direction": None,
            "quality_ok": False,
        }

    start = max(0, center_index - window)
    end = min(n - 2, center_index + window)

    best_bull_mid_dist = None
    best_bear_mid_dist = None

    best_bull = (None, None)  # (fvg_low, fvg_high)
    best_bear = (None, None)

    last_close = candles[-1]["close"]

    for i in range(start, end):
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

    chosen_dir: Optional[str] = None
    fvg_low: Optional[float] = None
    fvg_high: Optional[float] = None
    mid = None

    if best_bull_mid_dist is not None or best_bear_mid_dist is not None:
        if best_bear_mid_dist is None or (
            best_bull_mid_dist is not None and best_bull_mid_dist <= best_bear_mid_dist
        ):
            chosen_dir = "bullish"
            fvg_low, fvg_high = best_bull
            mid = 0.5 * (fvg_low + fvg_high)
        else:
            chosen_dir = "bearish"
            fvg_low, fvg_high = best_bear
            mid = 0.5 * (fvg_low + fvg_high)

    if chosen_dir is None or fvg_low is None or fvg_high is None or fvg_high <= fvg_low:
        return {
            "has_fvg": False,
            "low": None,
            "high": None,
            "direction": None,
            "quality_ok": False,
        }

    # penilaian kualitas sederhana
    width = fvg_high - fvg_low
    if mid is None or mid <= 0:
        width_pct = 0.0
        dist_pct = 0.0
    else:
        width_pct = width / mid
        dist_pct = abs(last_close - mid) / mid

    quality_ok = True

    # batas lebar FVG (supaya tidak terlalu lebar)
    if width_pct > max_width_pct:
        quality_ok = False

    # batas jarak ke harga sekarang (tidak terlalu jauh)
    if dist_pct > max_dist_pct:
        quality_ok = False

    return {
        "has_fvg": True,
        "low": float(fvg_low),
        "high": float(fvg_high),
        "direction": chosen_dir,
        "quality_ok": quality_ok,
                }

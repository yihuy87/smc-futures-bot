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
    min_width_pct: float = 0.0008,  # ~0.08% minimum
) -> Dict[str, Optional[object]]:
    """
    Deteksi FVG di sekitar candle 'center_index'.

    Pola 3-candle klasik:
    - Bullish FVG: low[2] > high[0]
    - Bearish FVG: high[2] < low[0]

    Selain deteksi, juga menilai kualitas:
    - lebar FVG tidak terlalu besar (max_width_pct)
    - lebar FVG tidak terlalu kecil (min_width_pct)
    - jarak mid FVG ke harga terakhir tidak terlalu jauh (max_dist_pct)

    CATATAN UNIT:
    - *_pct parameters di sini adalah *fraction* dari price (mis. 0.008 = 0.8%),
      bukan literal persen (0.8). Ini konsisten dengan penggunaan di SMC module.
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

    # validate center_index
    if not (0 <= center_index < n):
        return {
            "has_fvg": False,
            "low": None,
            "high": None,
            "direction": None,
            "quality_ok": False,
        }

    # iterate i such that i+2 < n; make loop inclusive of upper window bound
    start = max(0, center_index - window)
    last_start = min(n - 3, center_index + window)  # ensure i+2 < n
    if start > last_start:
        return {
            "has_fvg": False,
            "low": None,
            "high": None,
            "direction": None,
            "quality_ok": False,
        }

    best_bull_mid_dist: Optional[float] = None
    best_bear_mid_dist: Optional[float] = None

    best_bull = (None, None)  # (fvg_low, fvg_high)
    best_bear = (None, None)

    last_close = float(candles[-1]["close"])

    for i in range(start, last_start + 1):
        c0 = candles[i]
        c2 = candles[i + 2]

        # cast numeric fields to float for safety
        c0_high = float(c0["high"])
        c0_low = float(c0["low"])
        c2_high = float(c2["high"])
        c2_low = float(c2["low"])

        # Bullish FVG: c2.low > c0.high
        if c2_low > c0_high:
            fvg_low = c0_high
            fvg_high = c2_low
            mid = 0.5 * (float(fvg_low) + float(fvg_high))
            # avoid weird mid <= 0
            if mid > 0:
                dist = abs(last_close - mid)
                if best_bull_mid_dist is None or dist < best_bull_mid_dist:
                    best_bull_mid_dist = dist
                    best_bull = (float(fvg_low), float(fvg_high))

        # Bearish FVG: c2.high < c0.low
        if c2_high < c0_low:
            fvg_high = c0_low
            fvg_low = c2_high
            mid = 0.5 * (float(fvg_low) + float(fvg_high))
            if mid > 0:
                dist = abs(last_close - mid)
                if best_bear_mid_dist is None or dist < best_bear_mid_dist:
                    best_bear_mid_dist = dist
                    best_bear = (float(fvg_low), float(fvg_high))

    chosen_dir: Optional[str] = None
    fvg_low: Optional[float] = None
    fvg_high: Optional[float] = None
    mid_val: Optional[float] = None

    if best_bull_mid_dist is not None or best_bear_mid_dist is not None:
        if best_bear_mid_dist is None or (
            best_bull_mid_dist is not None and best_bull_mid_dist <= best_bear_mid_dist
        ):
            chosen_dir = "bullish"
            fvg_low, fvg_high = best_bull
        else:
            chosen_dir = "bearish"
            fvg_low, fvg_high = best_bear

        if fvg_low is not None and fvg_high is not None:
            mid_val = 0.5 * (float(fvg_low) + float(fvg_high))

    if chosen_dir is None or fvg_low is None or fvg_high is None or fvg_high <= fvg_low:
        return {
            "has_fvg": False,
            "low": None,
            "high": None,
            "direction": None,
            "quality_ok": False,
        }

    width = float(fvg_high) - float(fvg_low)
    if mid_val is None or mid_val <= 0:
        width_pct = 0.0
        dist_pct = 0.0
    else:
        width_pct = width / mid_val
        dist_pct = abs(last_close - mid_val) / mid_val

    quality_ok = True

    # batas lebar FVG (supaya tidak terlalu lebar)
    if width_pct > float(max_width_pct):
        quality_ok = False

    # batas minimum lebar FVG (hindari noise mikro)
    if width_pct < float(min_width_pct):
        quality_ok = False

    # batas jarak ke harga sekarang (tidak terlalu jauh)
    if dist_pct > float(max_dist_pct):
        quality_ok = False

    return {
        "has_fvg": True,
        "low": float(fvg_low),
        "high": float(fvg_high),
        "direction": chosen_dir,
        "quality_ok": quality_ok,
        }

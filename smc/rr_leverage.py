# smc/rr_leverage.py
# Bangun level Entry/SL/TP dan rekomendasi leverage berdasarkan jarak SL (SL%).
#
# Perbaikan besar:
# - SL tidak lagi ultra kecil (0.1–0.2%), tapi lebih sehat (≈0.35–1.5%)
# - SL diposisikan di balik sweep + buffer berbasis FVG range + ATR + % harga
# - Entry tetap gunakan FVG, tetapi dengan pendekatan yang lebih aman
# - Rekomendasi leverage jauh lebih konservatif
# - LOGIKA Risk Calc di sweep_fvg_analyzer diperbaiki (1/sl_pct, bukan 100/sl_pct)
#
# Revisi ini menambahkan sanity guards (range checks, numeric safety) dan
# memastikan sl_pct dihitung konsisten dalam *persen* (mis. 0.45 berarti 0.45%).

from typing import Dict, Tuple, List
import math

from binance.ohlc_buffer import Candle


def _calc_atr(candles: List[Candle], period: int = 14) -> float:
    """
    Hitung ATR sederhana dari list candle 5m.
    Jika data kurang, return 0.0 (fallback).
    """
    n = len(candles)
    if n <= period + 1:
        return 0.0

    trs: List[float] = []
    for i in range(1, n):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        prev_close = float(candles[i - 1]["close"])
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        trs.append(tr)

    if not trs:
        return 0.0

    period = min(period, len(trs))
    recent_trs = trs[-period:]
    return sum(recent_trs) / len(recent_trs)


def build_levels_and_leverage(
    side: str,
    candles_5m: list[Candle],
    sweep_index: int,
    fvg_low: float,
    fvg_high: float,
    rr_tp1: float = 1.2,
    rr_tp2: float = 2.0,
    rr_tp3: float = 3.0,
) -> Dict:
    """
    Bangun entry/sl/tp dan rekomendasi leverage untuk SMC sweep+FVG retest.

    Return keys:
      entry, sl, tp1, tp2, tp3, sl_pct (persen), lev_min, lev_max

    Catatan unit:
      - sl_pct dikembalikan dalam *persen* (mis. 0.45 => 0.45%).
    """
    # --- basic guards ---
    n = len(candles_5m)
    if n == 0:
        raise ValueError("candles_5m kosong")
    if sweep_index is None or not (0 <= sweep_index < n):
        raise IndexError(f"sweep_index out of range: {sweep_index}")

    last_close = float(candles_5m[-1]["close"])

    # Pastikan urutan low < high untuk FVG
    f_low = float(min(fvg_low, fvg_high))
    f_high = float(max(fvg_low, fvg_high))
    f_range = max(f_high - f_low, 1e-9)

    # Entry: sedikit ke dalam FVG dari sisi yang sesuai dengan arah,
    # tetapi tidak di luar harga sekarang (anti-FOMO).
    edge_frac = 0.3  # 30% dari sisi FVG

    if side == "long":
        raw_entry = f_high - edge_frac * f_range
        entry = float(min(raw_entry, last_close))
    else:
        raw_entry = f_low + edge_frac * f_range
        entry = float(max(raw_entry, last_close))

    # Ensure entry not zero to avoid division issues
    if entry == 0.0:
        entry = last_close if last_close != 0.0 else 1e-9

    # ATR for scale
    atr = float(_calc_atr(candles_5m, period=14))

    # ===================== SL & RISK =====================
    # buffer logic: base from FVG + min price buffer based on percent & ATR
    base_buffer = 0.30 * f_range
    min_price_buffer_pct = 0.0035  # ≈0.35%
    min_price_buffer = abs(entry) * min_price_buffer_pct
    if atr > 0:
        min_price_buffer = max(min_price_buffer, 0.5 * atr)

    buffer = max(base_buffer, min_price_buffer)

    if side == "long":
        sweep_low = float(candles_5m[sweep_index]["low"])
        sl = float(sweep_low - buffer)
        risk = entry - sl
    else:
        sweep_high = float(candles_5m[sweep_index]["high"])
        sl = float(sweep_high + buffer)
        risk = sl - entry

    # Fallback if risk not positive (extreme / degenerate cases)
    if not (risk > 0 and math.isfinite(risk)):
        min_r = abs(entry) * min_price_buffer_pct
        if side == "long":
            sl = entry - min_r
            risk = entry - sl
        else:
            sl = entry + min_r
            risk = sl - entry

    # final numeric safety
    if risk <= 0:
        # last-resort fallback
        raise RuntimeError("Unable to compute positive risk for levels")

    # ===================== enforce minimal SL% floor (target healthy range) ====
    sl_pct = abs(risk / entry) * 100.0  # percent

    MIN_SL_PCT = 0.35  # minimum acceptable percent
    if sl_pct < MIN_SL_PCT:
        # widen risk to meet min SL%
        target_risk = abs(entry) * (MIN_SL_PCT / 100.0)
        if side == "long":
            sl = entry - target_risk
            risk = entry - sl
        else:
            sl = entry + target_risk
            risk = sl - entry
        sl_pct = abs(risk / entry) * 100.0

    # OPTIONAL: Cap SL% upper bound to avoid crazy wide SL (safety)
    MAX_SL_PCT = 20.0  # unrealistic very large SLs are capped (project-specific)
    if sl_pct > MAX_SL_PCT:
        # bring sl closer proportionally
        target_risk = abs(entry) * (MAX_SL_PCT / 100.0)
        if side == "long":
            sl = entry - target_risk
            risk = entry - sl
        else:
            sl = entry + target_risk
            risk = sl - entry
        sl_pct = abs(risk / entry) * 100.0

    # ===================== TP (RR) =====================
    if side == "long":
        tp1 = entry + float(rr_tp1) * risk
        tp2 = entry + float(rr_tp2) * risk
        tp3 = entry + float(rr_tp3) * risk
    else:
        tp1 = entry - float(rr_tp1) * risk
        tp2 = entry - float(rr_tp2) * risk
        tp3 = entry - float(rr_tp3) * risk

    # ===================== LEVERAGE recommendation =====================
    # use sl_pct (percent) to recommend leverage
    lev_min, lev_max = recommend_leverage_range(sl_pct)

    # ensure lev_min <= lev_max and are finite
    lev_min = float(lev_min)
    lev_max = float(lev_max)
    if not (math.isfinite(lev_min) and math.isfinite(lev_max)):
        lev_min, lev_max = 1.0, 1.0
    if lev_min > lev_max:
        lev_min, lev_max = lev_max, lev_min

    return {
        "entry": float(entry),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "tp3": float(tp3),
        "sl_pct": float(sl_pct),
        "lev_min": float(lev_min),
        "lev_max": float(lev_max),
    }


def recommend_leverage_range(sl_pct: float) -> Tuple[float, float]:
    """
    Rekomendasi leverage rentang berdasarkan SL% (dalam % harga).
    Versi konservatif:
    - SL kecil → leverage boleh agak besar, tapi tidak ekstrem
    - SL besar → leverage diturunkan
    """
    try:
        sp = float(sl_pct)
    except Exception:
        sp = 0.0

    if sp <= 0:
        return 1.0, 2.0

    if sp <= 0.50:
        return 4.0, 7.0
    elif sp <= 0.80:
        return 3.0, 5.0
    elif sp <= 1.50:
        return 2.0, 3.0
    else:
        return 1.0, 2.0

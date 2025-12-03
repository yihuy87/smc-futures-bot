# smc/rr_leverage.py
# Bangun level Entry/SL/TP dan rekomendasi leverage berdasarkan jarak SL (SL%).

from typing import Dict

from binance.ohlc_buffer import Candle


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
    side: "long" atau "short"
    fvg_low, fvg_high: level FVG dari deteksi sebelumnya.

    Return dict:
    {
        "entry": float,
        "sl": float,
        "tp1": float,
        "tp2": float,
        "tp3": float,
        "sl_pct": float,
        "lev_min": float,
        "lev_max": float,
    }
    """
    last_close = candles_5m[-1]["close"]

    if side == "long":
        # Entry di mid FVG, tetapi jangan di atas harga terakhir (anti FOMO)
        raw_entry = 0.5 * (fvg_low + fvg_high)
        entry = min(raw_entry, last_close)

        # SL di bawah low sweep, sedikit buffer
        sweep_low = candles_5m[sweep_index]["low"]
        # buffer kecil ~ 0.15% dari harga sweep (adaptif)
        buffer = sweep_low * 0.0015
        sl = sweep_low - buffer

        risk = entry - sl
    else:
        # SHORT
        raw_entry = 0.5 * (fvg_low + fvg_high)
        entry = max(raw_entry, last_close)

        sweep_high = candles_5m[sweep_index]["high"]
        buffer = sweep_high * 0.0015
        sl = sweep_high + buffer

        risk = sl - entry

    if risk <= 0:
        # fallback kecil
        risk = abs(entry) * 0.003

    # TP berdasarkan RR
    if side == "long":
        tp1 = entry + rr_tp1 * risk
        tp2 = entry + rr_tp2 * risk
        tp3 = entry + rr_tp3 * risk
    else:
        tp1 = entry - rr_tp1 * risk
        tp2 = entry - rr_tp2 * risk
        tp3 = entry - rr_tp3 * risk

    sl_pct = abs(risk / entry) * 100.0 if entry != 0 else 0.0
    lev_min, lev_max = recommend_leverage_range(sl_pct)

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


def recommend_leverage_range(sl_pct: float) -> tuple[float, float]:
    """
    Rekomendasi leverage rentang berdasarkan SL% (risk per posisi jika 1x).
    Ini bukan perintah, hanya saran aman.
    """
    if sl_pct <= 0:
        return 5.0, 10.0

    # Semakin kecil SL%, semakin besar leverage yang masih masuk akal.
    if sl_pct <= 0.25:
        return 25.0, 40.0
    elif sl_pct <= 0.50:
        return 15.0, 25.0
    elif sl_pct <= 0.80:
        return 8.0, 15.0
    elif sl_pct <= 1.20:
        return 5.0, 8.0
    else:
        return 3.0, 5.0

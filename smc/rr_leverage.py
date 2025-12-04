# smc/rr_leverage.py
# Bangun level Entry/SL/TP dan rekomendasi leverage berdasarkan jarak SL (SL%).

from typing import Dict, Tuple

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

    Versi optimasi:
    - Entry pakai "FVG EDGE" (shallow retest), bukan mid FVG.
      LONG  → dekat batas atas FVG
      SHORT → dekat batas bawah FVG
    - SL di balik sweep + buffer adaptif.
    """

    last_close = candles_5m[-1]["close"]

    # Pastikan urutan low < high
    f_low = min(fvg_low, fvg_high)
    f_high = max(fvg_low, fvg_high)
    f_range = max(f_high - f_low, 1e-9)
    edge_frac = 0.15  # 15% ke dalam dari sisi yang dekat harga

    # ===================== ENTRY =====================
    if side == "long":
        # Harga setelah displacement di atas FVG.
        # Retest tipis: dari sisi ATAS FVG turun sedikit ke dalam.
        raw_entry = f_high - edge_frac * f_range
        # Jangan sampai entry di atas harga sekarang (anti FOMO).
        entry = min(raw_entry, last_close)
    else:
        # SHORT:
        # Harga setelah displacement di bawah FVG.
        # Retest tipis: dari sisi BAWAH FVG naik sedikit ke dalam.
        raw_entry = f_low + edge_frac * f_range
        # Jangan sampai entry di bawah harga sekarang.
        entry = max(raw_entry, last_close)

    # ===================== SL & RISK =====================
    if side == "long":
        sweep_low = candles_5m[sweep_index]["low"]
        buffer = max(0.30 * f_range, abs(entry) * 0.0005)
        sl = sweep_low - buffer
        risk = entry - sl
    else:
        sweep_high = candles_5m[sweep_index]["high"]
        buffer = max(0.30 * f_range, abs(entry) * 0.0005)
        sl = sweep_high + buffer
        risk = sl - entry

    if risk <= 0:
        # fallback kecil supaya tidak nol/negatif
        risk = max(abs(entry) * 0.003, 1e-8)

    # ===================== TP (RR) =====================
    if side == "long":
        tp1 = entry + rr_tp1 * risk
        tp2 = entry + rr_tp2 * risk
        tp3 = entry + rr_tp3 * risk
    else:
        tp1 = entry - rr_tp1 * risk
        tp2 = entry - rr_tp2 * risk
        tp3 = entry - rr_tp3 * risk

    # ===================== SL% & LEVERAGE =====================
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


def recommend_leverage_range(sl_pct: float) -> Tuple[float, float]:
    """
    Rekomendasi leverage rentang berdasarkan SL% (risk per posisi jika 1x).
    Disesuaikan dengan gaya pesan sinyal:
    - SL kecil → leverage boleh lebih besar
    - SL besar → leverage diturunkan
    """
    if sl_pct <= 0:
        return 5.0, 10.0

    if sl_pct <= 0.40:
        # contoh: ~0.35% → 15x–25x
        return 15.0, 25.0
    elif sl_pct <= 0.70:
        # contoh: ~0.55–0.68% → 8x–15x
        return 8.0, 15.0
    elif sl_pct <= 1.20:
        return 5.0, 8.0
    else:
        return 3.0, 5.0

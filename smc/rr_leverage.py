# smc/rr_leverage.py
# Bangun level Entry/SL/TP dan rekomendasi leverage berdasarkan jarak SL (SL%).
#
# Perbaikan besar:
# - SL tidak lagi ultra kecil (0.1–0.2%), tapi lebih sehat (≈0.35–1.5%)
# - SL diposisikan di balik sweep + buffer berbasis FVG range + ATR + % harga
# - Entry tetap gunakan FVG, tetapi dengan pendekatan yang lebih aman
# - Rekomendasi leverage jauh lebih konservatif
# - LOGIKA Risk Calc di sweep_fvg_analyzer diperbaiki (1/sl_pct, bukan 100/sl_pct)

from typing import Dict, Tuple, List

from binance.ohlc_buffer import Candle


def _calc_atr(candles: List[Candle], period: int = 14) -> float:
    """
    Hitung ATR sederhana dari list candle 5m.
    Jika data kurang, return 0.0 (fallback).
    """
    n = len(candles)
    if n <= period + 1:
        return 0.0

    trs = []
    for i in range(1, n):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
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
    side: "long" atau "short"
    fvg_low, fvg_high: level FVG dari deteksi sebelumnya.

    Versi perbaikan:
    - Entry masih menggunakan FVG, tapi tidak terlalu agresif (tidak terlalu dekat noise).
    - SL diletakkan di balik sweep + buffer adaptif:
      * 30% lebar FVG
      * minimal 0.35% dari harga
      * minimal 0.5×ATR (jika ATR tersedia)
    - SL% dijaga di kisaran sehat (≈0.35%–1.5%) sehingga:
      * tidak terlalu mudah tersentuh noise
      * tetap memberi RR yang masuk akal
    """

    last_close = candles_5m[-1]["close"]

    # Pastikan urutan low < high
    f_low = min(fvg_low, fvg_high)
    f_high = max(fvg_low, fvg_high)
    f_range = max(f_high - f_low, 1e-9)

    # Entry: sedikit ke dalam FVG dari sisi yang sesuai dengan arah,
    # tapi tidak memaksa di luar harga saat ini (anti FOMO).
    edge_frac = 0.3  # 30% dari sisi FVG

    if side == "long":
        # Retest dari sisi atas FVG, turun sedikit ke dalam
        raw_entry = f_high - edge_frac * f_range
        entry = min(raw_entry, last_close)
    else:
        # SHORT: retest dari sisi bawah FVG, naik sedikit ke dalam
        raw_entry = f_low + edge_frac * f_range
        entry = max(raw_entry, last_close)

    # ATR untuk skala buffer
    atr = _calc_atr(candles_5m, period=14)

    # ===================== SL & RISK =====================
    if side == "long":
        sweep_low = candles_5m[sweep_index]["low"]
        # buffer awal: 30% FVG range
        base_buffer = 0.30 * f_range
        # tambahkan constraint minimal berdasarkan ATR & persentase harga
        min_price_buffer = abs(entry) * 0.0035  # ≈0.35% dari harga
        if atr > 0:
            min_price_buffer = max(min_price_buffer, 0.5 * atr)

        buffer = max(base_buffer, min_price_buffer)
        sl = sweep_low - buffer
        risk = entry - sl
    else:
        sweep_high = candles_5m[sweep_index]["high"]
        base_buffer = 0.30 * f_range
        min_price_buffer = abs(entry) * 0.0035  # ≈0.35% dari harga
        if atr > 0:
            min_price_buffer = max(min_price_buffer, 0.5 * atr)

        buffer = max(base_buffer, min_price_buffer)
        sl = sweep_high + buffer
        risk = sl - entry

    # Fallback jika entah bagaimana risk <= 0
    if risk <= 0:
        # Minimum 0.35% dari harga sebagai backup
        min_r = abs(entry) * 0.0035
        if side == "long":
            sl = entry - min_r
            risk = entry - sl
        else:
            sl = entry + min_r
            risk = sl - entry

    # Hitung SL% dan jaga di kisaran sehat (target 0.35–1.5%)
    sl_pct = abs(risk / entry) * 100.0 if entry != 0 else 0.0

    # Kalau masih terlalu kecil (<0.35%), lebarkan lagi SL sedikit
    MIN_SL_PCT = 0.35
    if sl_pct > 0 and sl_pct < MIN_SL_PCT:
        target_risk = abs(entry) * (MIN_SL_PCT / 100.0)
        if side == "long":
            sl = entry - target_risk
            risk = entry - sl
        else:
            sl = entry + target_risk
            risk = sl - entry
        sl_pct = abs(risk / entry) * 100.0 if entry != 0 else sl_pct

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
    Rekomendasi leverage rentang berdasarkan SL% (dalam % harga).
    Versi konservatif:
    - SL kecil → leverage boleh agak besar, tapi tidak ekstrem
    - SL besar → leverage diturunkan
    """
    if sl_pct <= 0:
        return 3.0, 5.0

    # Kira-kira:
    # - <0.5% : 4–7x
    # - 0.5–0.8% : 3–5x
    # - 0.8–1.5% : 2–3x
    # - >1.5% : 1–2x
    if sl_pct <= 0.50:
        return 4.0, 7.0
    elif sl_pct <= 0.80:
        return 3.0, 5.0
    elif sl_pct <= 1.50:
        return 2.0, 3.0
    else:
        return 1.0, 2.0

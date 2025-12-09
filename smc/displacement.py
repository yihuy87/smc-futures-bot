# smc/displacement.py
# Deteksi displacement (candle impuls kuat) setelah sweep + minor Break of Structure.

from typing import List, Optional, Dict
from binance.ohlc_buffer import Candle


def detect_displacement(
    candles: List[Candle],
    sweep_index: int,
    side: str,
    look_ahead: int = 2,
    body_factor: float = 2.0,
) -> Dict[str, Optional[object]]:
    """
    Deteksi candle impuls (displacement) setelah sweep_index.

    Syarat:
    - body besar dibanding rata-rata body beberapa candle sebelumnya
    - body dominan terhadap range candle (wick tidak mendominasi)
    - arah body sesuai side (long: bullish, short: bearish)
    - candle mematahkan struktur kecil sebelum sweep (minor BOS)

    Return:
    {
        "index": int | None,
        "bos_ok": bool
    }
    """

    n = len(candles)
    if n < 10 or sweep_index is None:
        return {"index": None, "bos_ok": False}

    # --- Validasi sweep_index ---
    if sweep_index < 2 or sweep_index >= n - 1:
        return {"index": None, "bos_ok": False}

    # --- Hitung rata-rata body sebelum sweep ---
    prev_start = max(0, sweep_index - 5)
    prev_segment = candles[prev_start:sweep_index]

    prev_bodies = [
        abs(c["close"] - c["open"]) for c in prev_segment
    ]

    if not prev_bodies:
        return {"index": None, "bos_ok": False}

    avg_body = sum(prev_bodies) / len(prev_bodies)
    if avg_body <= 0:
        return {"index": None, "bos_ok": False}

    # --- Struktur sebelum sweep ---
    struct_start = max(0, sweep_index - 6)
    struct_segment = candles[struct_start:sweep_index + 1]

    if not struct_segment:
        return {"index": None, "bos_ok": False}

    pre_high = max(c["high"] for c in struct_segment)
    pre_low = min(c["low"] for c in struct_segment)

    best_idx: Optional[int] = None
    best_body = 0.0
    bos_ok = False

    # --- Cari displacement candle di depan sweep (1–2 candle) ---
    start = sweep_index + 1
    end = min(n, sweep_index + 1 + max(1, look_ahead))

    for i in range(start, end):
        c = candles[i]
        open_ = float(c["open"])
        close = float(c["close"])
        high = float(c["high"])
        low = float(c["low"])

        body = abs(close - open_)
        total_range = high - low
        if total_range <= 0:
            continue

        # Arah body harus selaras
        if side == "long" and not (close > open_):
            continue
        if side == "short" and not (close < open_):
            continue

        body_ratio = body / total_range

        # body harus dominan dan lebih besar dari histori
        if body < body_factor * avg_body or body_ratio < 0.60:
            continue

        # --- Minor BOS lebih ketat: gunakan close, bukan wick ---
        if side == "long":
            bos_cond = close > pre_high
        else:
            bos_cond = close < pre_low

        if body > best_body:
            best_body = body
            best_idx = i
            bos_ok = bool(bos_cond)

    return {"index": best_idx, "bos_ok": bos_ok}

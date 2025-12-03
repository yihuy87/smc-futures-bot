# smc/displacement.py
# Deteksi displacement (candle impuls kuat) setelah sweep.

from typing import List, Optional, Dict
from binance.ohlc_buffer import Candle


def detect_displacement(
    candles: List[Candle],
    sweep_index: int,
    look_ahead: int = 2,
    body_factor: float = 1.8,
) -> Dict[str, Optional[int]]:
    """
    Deteksi candle impuls (displacement) setelah sweep_index.

    - Bandingkan body candle kandidat dengan rata-rata body beberapa candle sebelumnya.
    - arah harus searah dengan bias (naik untuk long, turun untuk short)
    (arah final akan diputuskan di analyzer, di sini hanya cek 'besar' dan 'tegas').

    Return:
    {
        "index": int | None,   # index candle displacement
    }
    """
    n = len(candles)
    if n < 10 or sweep_index is None or sweep_index < 3:
        return {"index": None}

    # hitung rata-rata body 5 candle sebelum sweep
    prev_range = range(max(0, sweep_index - 5), sweep_index)
    prev_bodies = [
        abs(candles[i]["close"] - candles[i]["open"]) for i in prev_range
    ]
    if not prev_bodies:
        return {"index": None}

    avg_body = sum(prev_bodies) / len(prev_bodies)
    if avg_body <= 0:
        return {"index": None}

    # cari candle impuls di 1-2 candle setelah sweep
    start = sweep_index + 1
    end = min(n, sweep_index + 1 + look_ahead)

    best_idx: Optional[int] = None
    best_body = 0.0

    for i in range(start, end):
        c = candles[i]
        body = abs(c["close"] - c["open"])
        total_range = c["high"] - c["low"]
        if total_range <= 0:
            continue

        # body harus dominan di candle tsb
        body_ratio = body / total_range

        # syarat: body cukup besar vs histori, dan dominan di range candle
        if body >= body_factor * avg_body and body_ratio >= 0.55:
            if body > best_body:
                best_body = body
                best_idx = i

    return {"index": best_idx}

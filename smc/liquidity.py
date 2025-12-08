# smc/liquidity.py
# Deteksi swing high/low dan zona liquidity (equal highs / equal lows) + sweep berkualitas.

from typing import List, Dict, Tuple, Optional
from binance.ohlc_buffer import Candle


def _pivot_high(candles: List[Candle], i: int, left: int = 2, right: int = 2) -> bool:
    """
    Simple pivot high: high[i] > high i-left...i-1 dan > high i+1...i+right.
    """
    if i < left or i + right >= len(candles):
        return False
    h = candles[i]["high"]
    for j in range(i - left, i + right + 1):
        if j == i:
            continue
        if candles[j]["high"] >= h:
            return False
    return True


def _pivot_low(candles: List[Candle], i: int, left: int = 2, right: int = 2) -> bool:
    """
    Simple pivot low: low[i] < low i-left...i-1 dan < low i+1...i+right.
    """
    if i < left or i + right >= len(candles):
        return False
    l = candles[i]["low"]
    for j in range(i - left, i + right + 1):
        if j == i:
            continue
        if candles[j]["low"] <= l:
            return False
    return True


def find_swings(
    candles: List[Candle],
    left: int = 2,
    right: int = 2,
) -> Tuple[List[int], List[int]]:
    """
    Return indeks swing_highs, swing_lows (pivot) pada list candle.
    """
    highs: List[int] = []
    lows: List[int] = []
    n = len(candles)
    for i in range(n):
        if _pivot_high(candles, i, left, right):
            highs.append(i)
        if _pivot_low(candles, i, left, right):
            lows.append(i)
    return highs, lows


def _cluster_levels(values: List[Tuple[int, float]], tolerance_pct: float) -> List[List[Tuple[int, float]]]:
    """
    Group (index, price) menjadi cluster jika selisih relatif kecil (<= tolerance_pct).
    Simple 1-pass cluster dari kiri ke kanan.
    """
    if not values:
        return []

    clusters: List[List[Tuple[int, float]]] = []
    current_cluster: List[Tuple[int, float]] = [values[0]]

    for idx, price in values[1:]:
        avg = sum(p for _, p in current_cluster) / len(current_cluster)
        rel_diff = abs(price - avg) / avg if avg != 0 else 0.0

        if rel_diff <= tolerance_pct:
            current_cluster.append((idx, price))
        else:
            clusters.append(current_cluster)
            current_cluster = [(idx, price)]

    if current_cluster:
        clusters.append(current_cluster)

    return clusters


def detect_liquidity_zones(
    candles: List[Candle],
    lookback: int = 40,
    tolerance_pct: float = 0.001,
) -> Dict[str, Optional[float]]:
    """
    Deteksi zona liquidity sederhana dalam window lookback terakhir.
    Fokus pada equal highs / equal lows dari swing pivot.

    Return:
    {
        "upper_liquidity": level or None,
        "lower_liquidity": level or None
    }
    """
    n = len(candles)
    if n < 10:
        return {"upper_liquidity": None, "lower_liquidity": None}

    start = max(0, n - lookback)
    segment = candles[start:]

    swings_high, swings_low = find_swings(segment, left=2, right=2)

    highs: List[Tuple[int, float]] = [
        (start + i, segment[i]["high"]) for i in swings_high
    ]
    lows: List[Tuple[int, float]] = [
        (start + i, segment[i]["low"]) for i in swings_low
    ]

    upper_liquidity = None
    lower_liquidity = None

    # cari cluster equal highs
    if len(highs) >= 2:
        highs_sorted = sorted(highs, key=lambda x: x[1])
        high_clusters = _cluster_levels(highs_sorted, tolerance_pct)
        if high_clusters:
            best_cluster = max(
                high_clusters,
                key=lambda cl: sum(p for _, p in cl) / len(cl),
            )
            upper_liquidity = sum(p for _, p in best_cluster) / len(best_cluster)

    # cari cluster equal lows
    if len(lows) >= 2:
        lows_sorted = sorted(lows, key=lambda x: x[1])
        low_clusters = _cluster_levels(lows_sorted, tolerance_pct)
        if low_clusters:
            best_cluster = min(
                low_clusters,
                key=lambda cl: sum(p for _, p in cl) / len(cl),
            )
            lower_liquidity = sum(p for _, p in best_cluster) / len(best_cluster)

    return {
        "upper_liquidity": float(upper_liquidity) if upper_liquidity is not None else None,
        "lower_liquidity": float(lower_liquidity) if lower_liquidity is not None else None,
    }

def detect_sweep(
    candles: List[Candle],
    upper_liquidity: Optional[float],
    lower_liquidity: Optional[float],
    check_last_n: int = 4,
) -> Dict[str, Optional[object]]:
    """
    Deteksi sweep terhadap liquidity atas atau bawah pada beberapa candle terakhir.
    Sekaligus menilai kualitas sweep (bukan wick kecil biasa).

    Return:
    {
        "side": "long" | "short" | None,
        "index": int | None,
        "liquidity_level": float | None,
        "quality": bool
    }
    """
    n = len(candles)
    if n < 8:
        return {"side": None, "index": None, "liquidity_level": None, "quality": False}

    start = max(0, n - check_last_n)

    # helper: rata-rata range & wick kecil sebelum sweep
    def avg_stats(before_index: int) -> Tuple[float, float, float]:
        # hitung dari beberapa candle sebelum before_index
        j_start = max(0, before_index - 5)
        prev = candles[j_start:before_index]
        if not prev:
            return 0.0, 0.0, 0.0
        ranges = [c["high"] - c["low"] for c in prev]
        upper_wicks = [c["high"] - max(c["open"], c["close"]) for c in prev]
        lower_wicks = [min(c["open"], c["close"]) - c["low"] for c in prev]
        avg_range = sum(ranges) / len(ranges)
        avg_up_wick = sum(upper_wicks) / len(upper_wicks)
        avg_lo_wick = sum(lower_wicks) / len(lower_wicks)
        return avg_range, avg_up_wick, avg_lo_wick

    # cek dari candle terbaru ke lebih lama (prefer sweep paling baru)
    # ----- Sweep bawah (LONG) -----
    if lower_liquidity is not None:
        for i in range(n - 1, start - 1, -1):
            c = candles[i]
            low = c["low"]
            high = c["high"]
            open_ = c["open"]
            close = c["close"]

            # low menembus level liquidity, close kembali di atas level
            if not (low < lower_liquidity < close):
                continue

            total_range = high - low
            if total_range <= 0:
                continue

            body = abs(close - open_)
            lower_wick = min(open_, close) - low

            avg_range, _, avg_lo_wick = avg_stats(i)
            if avg_range <= 0:
                continue

            # sweep berkualitas:
            # - range jauh > rata-rata
            # - lower wick dominan dan lebih besar dari wick sebelumnya
            # - body tidak full (bukan candle full body)
            range_ok = total_range > 1.5 * avg_range
            wick_ratio = lower_wick / total_range if total_range > 0 else 0.0
            wick_vs_avg = lower_wick > 1.5 * avg_lo_wick if avg_lo_wick > 0 else True
            body_not_too_big = body <= 0.7 * total_range

            quality = bool(range_ok and wick_ratio >= 0.45 and wick_vs_avg and body_not_too_big)

            return {
                "side": "long",
                "index": i,
                "liquidity_level": lower_liquidity,
                "quality": quality,
            }

    # ----- Sweep atas (SHORT) -----
    if upper_liquidity is not None:
        for i in range(n - 1, start - 1, -1):
            c = candles[i]
            low = c["low"]
            high = c["high"]
            open_ = c["open"]
            close = c["close"]

            if not (high > upper_liquidity > close):
                continue

            total_range = high - low
            if total_range <= 0:
                continue

            body = abs(close - open_)
            upper_wick = high - max(open_, close)

            avg_range, avg_up_wick, _ = avg_stats(i)
            if avg_range <= 0:
                continue

            range_ok = total_range > 1.5 * avg_range
            wick_ratio = upper_wick / total_range if total_range > 0 else 0.0
            wick_vs_avg = upper_wick > 1.5 * avg_up_wick if avg_up_wick > 0 else True
            body_not_too_big = body <= 0.7 * total_range

            quality = bool(range_ok and wick_ratio >= 0.45 and wick_vs_avg and body_not_too_big)

            return {
                "side": "short",
                "index": i,
                "liquidity_level": upper_liquidity,
                "quality": quality,
            }

    return {"side": None, "index": None, "liquidity_level": None, "quality": False}

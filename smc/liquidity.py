# smc/liquidity.py
# Deteksi swing high/low dan zona liquidity (equal highs / equal lows) + sweep berkualitas.
#
# Revisi: tambahkan sanity guards, casting numerik, dan fallback ringan agar robust.

from typing import List, Dict, Tuple, Optional
from binance.ohlc_buffer import Candle
import math


def _pivot_high(candles: List[Candle], i: int, left: int = 2, right: int = 2) -> bool:
    """
    Simple pivot high: high[i] > high i-left...i-1 dan > high i+1...i+right.
    Safe against edges.
    """
    n = len(candles)
    if n == 0:
        return False
    # ensure left/right feasible
    if left < 0 or right < 0:
        return False
    if i - left < 0 or i + right >= n:
        return False
    try:
        h = float(candles[i]["high"])
    except Exception:
        return False
    for j in range(i - left, i + right + 1):
        if j == i:
            continue
        try:
            other_h = float(candles[j]["high"])
        except Exception:
            return False
        if other_h >= h:
            return False
    return True


def _pivot_low(candles: List[Candle], i: int, left: int = 2, right: int = 2) -> bool:
    """
    Simple pivot low: low[i] < low i-left...i-1 dan < low i+1...i+right.
    """
    n = len(candles)
    if n == 0:
        return False
    if left < 0 or right < 0:
        return False
    if i - left < 0 or i + right >= n:
        return False
    try:
        l = float(candles[i]["low"])
    except Exception:
        return False
    for j in range(i - left, i + right + 1):
        if j == i:
            continue
        try:
            other_l = float(candles[j]["low"])
        except Exception:
            return False
        if other_l <= l:
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
    if n == 0:
        return highs, lows

    # clamp left/right so they are sensible relative to n
    left = max(0, min(left, n // 2))
    right = max(0, min(right, n // 2))

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

    for idx_price in values[1:]:
        try:
            idx, price = idx_price
            price = float(price)
        except Exception:
            continue

        # compute average price of current cluster
        avg = sum(float(p) for _, p in current_cluster) / len(current_cluster) if current_cluster else 0.0
        rel_diff = abs(price - avg) / avg if avg != 0 else 0.0

        if rel_diff <= float(tolerance_pct):
            current_cluster.append((int(idx), float(price)))
        else:
            clusters.append(current_cluster)
            current_cluster = [(int(idx), float(price))]

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
    if n < 8:
        return {"upper_liquidity": None, "lower_liquidity": None}

    start = max(0, n - int(lookback))
    segment = candles[start:]

    swings_high, swings_low = find_swings(segment, left=2, right=2)

    highs: List[Tuple[int, float]] = []
    lows: List[Tuple[int, float]] = []

    # map swing indices (relative to segment) to global indices and prices
    for i in swings_high:
        try:
            price = float(segment[i]["high"])
            highs.append((start + int(i), price))
        except Exception:
            continue

    for i in swings_low:
        try:
            price = float(segment[i]["low"])
            lows.append((start + int(i), price))
        except Exception:
            continue

    upper_liquidity: Optional[float] = None
    lower_liquidity: Optional[float] = None

    # cari cluster equal highs
    if len(highs) >= 2:
        highs_sorted = sorted(highs, key=lambda x: x[1])
        high_clusters = _cluster_levels(highs_sorted, tolerance_pct)
        if high_clusters:
            # choose cluster with most members, tie-breaker: avg price closest to last price
            last_price = float(candles[-1]["close"])
            best_cluster = max(
                high_clusters,
                key=lambda cl: (len(cl), -abs(sum(p for _, p in cl) / len(cl) - last_price)),
            )
            if best_cluster:
                upper_liquidity = sum(p for _, p in best_cluster) / len(best_cluster)

    # cari cluster equal lows
    if len(lows) >= 2:
        lows_sorted = sorted(lows, key=lambda x: x[1])
        low_clusters = _cluster_levels(lows_sorted, tolerance_pct)
        if low_clusters:
            last_price = float(candles[-1]["close"])
            best_cluster = max(
                low_clusters,
                key=lambda cl: (len(cl), -abs(sum(p for _, p in cl) / len(cl) - last_price)),
            )
            if best_cluster:
                lower_liquidity = sum(p for _, p in best_cluster) / len(best_cluster)

    return {
        "upper_liquidity": float(upper_liquidity) if upper_liquidity is not None and math.isfinite(upper_liquidity) else None,
        "lower_liquidity": float(lower_liquidity) if lower_liquidity is not None and math.isfinite(lower_liquidity) else None,
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
    if n < 6:
        return {"side": None, "index": None, "liquidity_level": None, "quality": False}

    start = max(0, n - int(check_last_n))

    def avg_stats(before_index: int) -> Tuple[float, float, float]:
        j_start = max(0, before_index - 5)
        prev = candles[j_start:before_index]
        if not prev:
            return 0.0, 0.0, 0.0
        ranges = []
        upper_wicks = []
        lower_wicks = []
        for c in prev:
            try:
                r = float(c["high"]) - float(c["low"])
                ranges.append(r)
                upper_wicks.append(float(c["high"]) - max(float(c["open"]), float(c["close"])))
                lower_wicks.append(min(float(c["open"]), float(c["close"])) - float(c["low"]))
            except Exception:
                continue
        avg_range = sum(ranges) / len(ranges) if ranges else 0.0
        avg_up_wick = sum(upper_wicks) / len(upper_wicks) if upper_wicks else 0.0
        avg_lo_wick = sum(lower_wicks) / len(lower_wicks) if lower_wicks else 0.0
        return avg_range, avg_up_wick, avg_lo_wick

    # ----- Sweep bawah (LONG) -----
    if lower_liquidity is not None:
        for i in range(n - 1, start - 1, -1):
            c = candles[i]
            try:
                low = float(c["low"])
                high = float(c["high"])
                open_ = float(c["open"])
                close = float(c["close"])
            except Exception:
                continue

            # condition: low pierces liquidity level and close recovers above it
            if not (low < float(lower_liquidity) < close):
                continue

            total_range = high - low
            if total_range <= 0:
                continue

            body = abs(close - open_)
            lower_wick = min(open_, close) - low

            avg_range, _, avg_lo_wick = avg_stats(i)
            if avg_range <= 0:
                # not enough history to evaluate quality; return sweep but quality False
                return {
                    "side": "long",
                    "index": i,
                    "liquidity_level": lower_liquidity,
                    "quality": False,
                }

            # sweep quality heuristics
            range_ok = total_range > 1.5 * avg_range
            wick_ratio = (lower_wick / total_range) if total_range > 0 else 0.0
            wick_vs_avg = lower_wick > 1.5 * avg_lo_wick if avg_lo_wick > 0 else True
            body_not_too_big = body <= 0.7 * total_range

            quality = bool(range_ok and wick_ratio >= 0.45 and wick_vs_avg and body_not_too_big)

            return {
                "side": "long",
                "index": i,
                "liquidity_level": float(lower_liquidity),
                "quality": quality,
            }

    # ----- Sweep atas (SHORT) -----
    if upper_liquidity is not None:
        for i in range(n - 1, start - 1, -1):
            c = candles[i]
            try:
                low = float(c["low"])
                high = float(c["high"])
                open_ = float(c["open"])
                close = float(c["close"])
            except Exception:
                continue

            if not (high > float(upper_liquidity) > close):
                continue

            total_range = high - low
            if total_range <= 0:
                continue

            body = abs(close - open_)
            upper_wick = high - max(open_, close)

            avg_range, avg_up_wick, _ = avg_stats(i)
            if avg_range <= 0:
                return {
                    "side": "short",
                    "index": i,
                    "liquidity_level": upper_liquidity,
                    "quality": False,
                }

            range_ok = total_range > 1.5 * avg_range
            wick_ratio = (upper_wick / total_range) if total_range > 0 else 0.0
            wick_vs_avg = upper_wick > 1.5 * avg_up_wick if avg_up_wick > 0 else True
            body_not_too_big = body <= 0.7 * total_range

            quality = bool(range_ok and wick_ratio >= 0.45 and wick_vs_avg and body_not_too_big)

            return {
                "side": "short",
                "index": i,
                "liquidity_level": float(upper_liquidity),
                "quality": quality,
            }

    return {"side": None, "index": None, "liquidity_level": None, "quality": False}

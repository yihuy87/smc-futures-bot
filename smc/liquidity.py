# smc/liquidity.py
# Deteksi swing high/low dan zona liquidity sederhana (equal highs / equal lows).

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
        # bandingkan dengan harga rata-rata cluster sementara
        avg = sum(p for _, p in current_cluster) / len(current_cluster)
        if avg == 0:
            rel_diff = 0.0
        else:
            rel_diff = abs(price - avg) / avg

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
        # ambil cluster dengan rata-rata harga tertinggi (liquidity atas)
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
        # ambil cluster dengan rata-rata harga terendah (liquidity bawah)
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

    Return:
    {
        "side": "long" | "short" | None,
        "index": int | None,
        "liquidity_level": float | None
    }
    """
    n = len(candles)
    if n < 5:
        return {"side": None, "index": None, "liquidity_level": None}

    start = max(0, n - check_last_n)
    sweep_side: Optional[str] = None
    sweep_idx: Optional[int] = None
    sweep_level: Optional[float] = None

    # cek sweep low (untuk peluang LONG)
    if lower_liquidity is not None:
        for i in range(start, n):
            c = candles[i]
            low = c["low"]
            close = c["close"]
            # low tembus di bawah liquidity, close kembali di atas
            if low < lower_liquidity and close > lower_liquidity:
                sweep_side = "long"
                sweep_idx = i
                sweep_level = lower_liquidity
                break

    # cek sweep high (untuk peluang SHORT)
    if sweep_side is None and upper_liquidity is not None:
        for i in range(start, n):
            c = candles[i]
            high = c["high"]
            close = c["close"]
            # high tembus di atas liquidity, close kembali di bawah
            if high > upper_liquidity and close < upper_liquidity:
                sweep_side = "short"
                sweep_idx = i
                sweep_level = upper_liquidity
                break

    return {
        "side": sweep_side,
        "index": sweep_idx,
        "liquidity_level": sweep_level,
               }

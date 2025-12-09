# smc/htf_context.py
# Ambil konteks HTF (15m & 1h) sederhana tanpa indikator:
# - trend UP / DOWN / RANGE di 1h
# - posisi harga di dalam range (DISCOUNT / PREMIUM / MID) untuk 1h & 15m
#
# Perbaikan:
# - Reuse HTTP session untuk efisiensi
# - Fallback BINANCE_REST_URL dari env jika config tidak tersedia
# - Robust parsing + explicit float casting
# - Logging yang lebih informatif and safer defaults on failure

from typing import Dict, List, Literal, Optional
import os
import logging
from functools import lru_cache

import requests

# try to import config; fallback to env
try:
    from config import BINANCE_REST_URL  # type: ignore
except Exception:
    BINANCE_REST_URL = os.environ.get("BINANCE_REST_URL", "https://fapi.binance.com")

logger = logging.getLogger(__name__)
_session = requests.Session()

# tuning thresholds as constants (easy to tweak)
_MIN_KLINES_FOR_TREND = 20
_TREND_UP_HIGH_PCT = 1.01
_TREND_UP_LOW_PCT = 1.005
_TREND_DOWN_HIGH_PCT = 0.99
_TREND_DOWN_LOW_PCT = 0.995


def _fetch_klines(symbol: str, interval: str, limit: int = 150) -> Optional[List[dict]]:
    """
    Fetch klines from Binance REST. Returns parsed JSON list or None on failure.
    Non-blocking: logs and returns None if any network issue.
    """
    url = f"{BINANCE_REST_URL.rstrip('/')}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    try:
        r = _session.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            logger.warning("[%s] Unexpected klines payload type: %s", symbol, type(data))
            return None
        return data
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        logger.warning("[%s] HTTP error fetching klines %s: %s", symbol, interval, status)
        return None
    except requests.exceptions.RequestException as e:
        logger.warning("[%s] Network error fetching klines %s: %s", symbol, interval, e)
        return None
    except Exception as e:
        logger.exception("[%s] Unexpected error fetching klines %s: %s", symbol, interval, e)
        return None


def _parse_ohlc(data: List[dict]) -> Dict[str, List[float]]:
    """
    Parse Binance kline rows into lists of floats for high/low/close.
    Binance kline format (array): [openTime, open, high, low, close, ...]
    We only read indices 2 (high), 3 (low), 4 (close).
    """
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    for row in data:
        try:
            # be explicit: index 2 = high, 3 = low, 4 = close
            h = float(row[2])
            l = float(row[3])
            c = float(row[4])
        except (ValueError, TypeError, IndexError):
            # skip malformed row but continue
            continue
        highs.append(h)
        lows.append(l)
        closes.append(c)
    return {"high": highs, "low": lows, "close": closes}


def _detect_trend_1h(hlc: Dict[str, List[float]]) -> Literal["UP", "DOWN", "RANGE"]:
    """
    Simple trend detection on 1h HLC arrays.
    Uses coarse swings by sampling highs/lows to ignore micro-noise.
    """
    highs = hlc.get("high", [])
    lows = hlc.get("low", [])
    n = len(highs)
    if n < _MIN_KLINES_FOR_TREND:
        return "RANGE"

    # coarse downsampling
    step = max(n // 10, 2)
    swing_highs = highs[::step]
    swing_lows = lows[::step]
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return "RANGE"

    first_h = float(swing_highs[0])
    last_h = float(swing_highs[-1])
    first_l = float(swing_lows[0])
    last_l = float(swing_lows[-1])

    # small thresholds to avoid noise
    if last_h > first_h * _TREND_UP_HIGH_PCT and last_l > first_l * _TREND_UP_LOW_PCT:
        return "UP"
    if last_h < first_h * _TREND_DOWN_HIGH_PCT and last_l < first_l * _TREND_DOWN_LOW_PCT:
        return "DOWN"
    return "RANGE"


def _discount_premium(
    hlc: Dict[str, List[float]],
    window: int = 60,
) -> Dict[str, object]:
    """
    Return position within recent window:
    - position: "DISCOUNT" | "PREMIUM" | "MID"
    - range_high, range_low, price

    If insufficient data, returns MID and None ranges guarded.
    """
    highs = hlc.get("high", [])
    lows = hlc.get("low", [])
    closes = hlc.get("close", [])
    n = len(highs)
    if n < 5 or not closes:
        return {
            "position": "MID",
            "range_high": None,
            "range_low": None,
            "price": closes[-1] if closes else None,
        }

    start = max(0, n - int(window))
    seg_high = highs[start:]
    seg_low = lows[start:]
    price = float(closes[-1])

    try:
        range_high = max(seg_high)
        range_low = min(seg_low)
    except ValueError:
        return {
            "position": "MID",
            "range_high": None,
            "range_low": None,
            "price": price,
        }

    if range_high <= range_low:
        return {
            "position": "MID",
            "range_high": range_high,
            "range_low": range_low,
            "price": price,
        }

    mid_span = float(range_high - range_low)
    pos = (price - range_low) / mid_span if mid_span > 0 else 0.5

    if pos <= 0.35:
        position = "DISCOUNT"
    elif pos >= 0.65:
        position = "PREMIUM"
    else:
        position = "MID"

    return {
        "position": position,
        "range_high": range_high,
        "range_low": range_low,
        "price": price,
    }


# cache HTF fetch for a short time in-process to avoid hammering REST in tight loops.
# LRU cache with small capacity; caller can restart process to refresh.
@lru_cache(maxsize=128)
def _fetch_and_parse_cached(symbol: str, interval: str, limit: int = 150) -> Optional[Dict[str, List[float]]]:
    data = _fetch_klines(symbol, interval, limit=limit)
    if not data:
        return None
    parsed = _parse_ohlc(data)
    return parsed


def get_htf_context(symbol: str) -> Dict[str, object]:
    """
    Ambil konteks 1h & 15m untuk symbol (tanpa indikator).
    Return dict:
    {
      "trend_1h": "UP"|"DOWN"|"RANGE",
      "pos_1h": "DISCOUNT"|"PREMIUM"|"MID",
      "pos_15m": "DISCOUNT"|"PREMIUM"|"MID",
      "htf_ok_long": bool,
      "htf_ok_short": bool,
    }

    Jika gagal fetch data, semua dianggap NETRAL (htf_ok_long/short = True).
    """
    # default netral
    ctx = {
        "trend_1h": "RANGE",
        "pos_1h": "MID",
        "pos_15m": "MID",
        "htf_ok_long": True,
        "htf_ok_short": True,
    }

    # fetch & parse (cached)
    hlc_1h = _fetch_and_parse_cached(symbol, "1h")
    hlc_15m = _fetch_and_parse_cached(symbol, "15m")

    if not hlc_1h or not hlc_15m:
        # cannot determine HTF reliably — return neutral
        return ctx

    trend_1h = _detect_trend_1h(hlc_1h)
    pos1 = _discount_premium(hlc_1h)
    pos15 = _discount_premium(hlc_15m)

    pos_1h = pos1.get("position", "MID")
    pos_15m = pos15.get("position", "MID")

    # Alignment rules (conservative)
    htf_ok_long = True
    htf_ok_short = True

    # LONG ideal: not 1h DOWN + not premium on both 1h & 15m
    if trend_1h == "DOWN":
        htf_ok_long = False
    if pos_1h == "PREMIUM" and pos_15m == "PREMIUM":
        htf_ok_long = False

    # SHORT ideal: not 1h UP + not discount on both 1h & 15m
    if trend_1h == "UP":
        htf_ok_short = False
    if pos_1h == "DISCOUNT" and pos_15m == "DISCOUNT":
        htf_ok_short = False

    return {
        "trend_1h": trend_1h,
        "pos_1h": pos_1h,
        "pos_15m": pos_15m,
        "htf_ok_long": bool(htf_ok_long),
        "htf_ok_short": bool(htf_ok_short),
    }

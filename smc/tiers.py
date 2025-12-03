# smc/tiers.py
# Evaluasi kualitas sinyal dan tentukan Tier (A+, A, B, NONE).

from typing import Dict

from core.bot_state import state


def score_signal(meta: Dict) -> int:
    """
    Skoring sederhana berdasarkan kualitas:
    - ada liquidity & sweep
    - displacement kuat
    - FVG jelas
    - RR bagus
    - SL% tidak terlalu besar
    """
    score = 0

    if meta.get("has_liquidity"):
        score += 15
    if meta.get("has_sweep"):
        score += 25
    if meta.get("has_displacement"):
        score += 25
    if meta.get("has_fvg"):
        score += 20

    # reward jika RR baik (TP2 ~ >= RR 2)
    if meta.get("good_rr"):
        score += 10

    sl_pct = meta.get("sl_pct", 0.0)
    if 0.1 <= sl_pct <= 0.8:
        score += 15  # SL% sehat (kecil tapi tidak absurd)

    return int(min(score, 150))


def tier_from_score(score: int) -> str:
    """
    Tier:
    - A+ : >= 120
    - A  : 100–119
    - B  : 80–99
    - NONE : < 80
    """
    if score >= 120:
        return "A+"
    elif score >= 100:
        return "A"
    elif score >= 80:
        return "B"
    else:
        return "NONE"


def should_send_tier(tier: str) -> bool:
    """
    Urutan: NONE < B < A < A+
    Bandingkan terhadap state.min_tier (diatur via Telegram /mode).
    """
    order = {"NONE": 0, "B": 1, "A": 2, "A+": 3}
    min_tier = state.min_tier or "A"
    return order.get(tier, 0) >= order.get(min_tier, 2)


def evaluate_signal_quality(meta: Dict) -> Dict:
    """
    Wrapper untuk dipanggil dari analyzer.

    meta minimal berisi:
    {
      "has_liquidity": bool,
      "has_sweep": bool,
      "has_displacement": bool,
      "has_fvg": bool,
      "good_rr": bool,
      "sl_pct": float,
    }
    """
    score = score_signal(meta)
    tier = tier_from_score(score)
    send = should_send_tier(tier)
    return {
        "score": score,
        "tier": tier,
        "should_send": send,
  }

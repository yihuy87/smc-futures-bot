# smc/tiers.py
# Evaluasi kualitas sinyal dan tentukan Tier (A+, A, B, NONE).

from typing import Dict

from core.bot_state import state


def score_signal(meta: Dict) -> int:
    """
    Skoring berdasarkan kualitas:
    - ada liquidity & sweep
    - kualitas sweep (wick & range)
    - displacement + minor BOS
    - FVG ada & berkualitas
    - RR bagus
    - SL% sehat
    - align dengan konteks HTF
    """

    score = 0

    has_liq = bool(meta.get("has_liquidity"))
    has_sweep = bool(meta.get("has_sweep"))
    sweep_quality = bool(meta.get("sweep_quality"))
    has_disp = bool(meta.get("has_displacement"))
    disp_bos = bool(meta.get("disp_bos"))
    has_fvg = bool(meta.get("has_fvg"))
    fvg_quality = bool(meta.get("fvg_quality"))
    good_rr = bool(meta.get("good_rr"))
    htf_alignment = bool(meta.get("htf_alignment"))

    sl_pct = float(meta.get("sl_pct", 0.0))

    if has_liq:
        score += 10
    if has_sweep:
        score += 20
    if sweep_quality:
        score += 10

    if has_disp:
        score += 20
    if disp_bos:
        score += 10

    if has_fvg:
        score += 15
    if fvg_quality:
        score += 10

    if good_rr:
        score += 10

    # SL% sehat (tidak terlalu kecil, tidak terlalu besar)
    # Target sehat: 0.35%–1.5%
    if 0.35 <= sl_pct <= 1.50:
        score += 10

    if htf_alignment:
        score += 15

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
      "sweep_quality": bool,
      "has_displacement": bool,
      "disp_bos": bool,
      "has_fvg": bool,
      "fvg_quality": bool,
      "good_rr": bool,
      "sl_pct": float,
      "htf_alignment": bool,
    }
    """
    score = score_signal(meta)
    tier = tier_from_score(score)

    # Hard filter kualitas supaya kasus "hit entry → langsung SL" berkurang
    sweep_quality = bool(meta.get("sweep_quality"))
    disp_bos = bool(meta.get("disp_bos"))
    fvg_quality = bool(meta.get("fvg_quality"))
    good_rr = bool(meta.get("good_rr"))
    htf_alignment = bool(meta.get("htf_alignment"))
    sl_pct = float(meta.get("sl_pct", 0.0))

    hard_ok = True

    if not sweep_quality:
        hard_ok = False
    if not disp_bos:
        hard_ok = False
    if not fvg_quality:
        hard_ok = False
    if not good_rr:
        hard_ok = False
    if not htf_alignment:
        hard_ok = False
    # SL terlalu kecil (<0.35%) atau terlalu besar (>1.5%) → buang
    if not (0.35 <= sl_pct <= 1.50):
        hard_ok = False

    send = should_send_tier(tier) and hard_ok

    return {
        "score": score,
        "tier": tier,
        "should_send": send,
        }

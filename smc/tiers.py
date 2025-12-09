# smc/tiers.py
# Evaluasi kualitas sinyal dan tentukan Tier (A+, A, B, NONE).

from typing import Dict, List

from core.bot_state import state

# Threshold constants (mudah di-tune)
MIN_SL_PCT = 0.35
MAX_SL_PCT = 1.50


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
    htf_alignment = bool(meta.get("htf_alignment", True))  # default netral if missing

    try:
        sl_pct = float(meta.get("sl_pct", 0.0))
    except Exception:
        sl_pct = 0.0

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
    if MIN_SL_PCT <= sl_pct <= MAX_SL_PCT:
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

    Returns:
      {
        "score": int,
        "tier": str,
        "should_send": bool,
        "reasons": List[str]   # optional: why not send
      }
    """
    score = score_signal(meta)
    tier = tier_from_score(score)

    # Hard filter kualitas supaya kasus "hit entry → langsung SL" berkurang
    reasons: List[str] = []

    sweep_quality = bool(meta.get("sweep_quality"))
    if not sweep_quality:
        reasons.append("sweep_quality_false")

    disp_bos = bool(meta.get("disp_bos"))
    if not disp_bos:
        reasons.append("disp_bos_false")

    fvg_quality = bool(meta.get("fvg_quality"))
    if not fvg_quality:
        reasons.append("fvg_quality_false")

    good_rr = bool(meta.get("good_rr"))
    if not good_rr:
        reasons.append("good_rr_false")

    # treat missing HTF alignment as neutral (True) to avoid false reject when HTF unavailable
    htf_alignment = meta.get("htf_alignment")
    if htf_alignment is None:
        htf_alignment = True
    if not bool(htf_alignment):
        reasons.append("htf_alignment_false")

    try:
        sl_pct = float(meta.get("sl_pct", 0.0))
    except Exception:
        sl_pct = 0.0
    if not (MIN_SL_PCT <= sl_pct <= MAX_SL_PCT):
        reasons.append("sl_pct_out_of_range")

    hard_ok = len(reasons) == 0
    send = should_send_tier(tier) and hard_ok

    return {
        "score": score,
        "tier": tier,
        "should_send": send,
        "reasons": reasons,
        }

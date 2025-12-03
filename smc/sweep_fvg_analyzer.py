# smc/sweep_fvg_analyzer.py
# Analisa utama SMC: Liquidity Sweep → Displacement → FVG → Entry/SL/TP.

from typing import List, Optional, Dict

from binance.ohlc_buffer import Candle
from smc.liquidity import detect_liquidity_zones, detect_sweep
from smc.displacement import detect_displacement
from smc.fvg_zones import detect_fvg_around
from smc.rr_leverage import build_levels_and_leverage
from smc.tiers import evaluate_signal_quality
from smc.htf_context import get_htf_context
from core.smc_settings import smc_settings
from core.signal_logger import log_signal   # logger sinyal


def analyze_symbol_smc(symbol: str, candles_5m: List[Candle]) -> Optional[Dict]:
    """
    Analisa SMC intraday untuk satu symbol menggunakan data 5m.
    Flow:
    - cari liquidity (equal highs / equal lows)
    - deteksi sweep (stop hunt) berkualitas
    - deteksi displacement + minor BOS
    - deteksi FVG (quality checked)
    - bangun Entry/SL/TP dan rekomendasi leverage
    - evaluasi kualitas (Tier) + konteks HTF (15m & 1h)
    - hanya kirim jika >= min_tier

    Return None jika tidak ada setup yang layak.
    """
    if len(candles_5m) < 30:
        return None

    # 1) Deteksi liquidity zones di history dekat
    liq = detect_liquidity_zones(candles_5m, lookback=40, tolerance_pct=0.001)
    upper_liq = liq.get("upper_liquidity")
    lower_liq = liq.get("lower_liquidity")

    if upper_liq is None and lower_liq is None:
        return None

    # 2) Deteksi sweep di beberapa candle terakhir
    sweep = detect_sweep(candles_5m, upper_liq, lower_liq, check_last_n=4)
    side = sweep.get("side")
    sweep_idx = sweep.get("index")
    sweep_quality = bool(sweep.get("quality"))

    if side not in ("long", "short") or sweep_idx is None:
        return None

    # 3) Deteksi displacement setelah sweep (arah & minor BOS)
    disp = detect_displacement(candles_5m, sweep_idx, side, look_ahead=2, body_factor=1.6)
    disp_idx = disp.get("index")
    disp_bos = bool(disp.get("bos_ok"))
    if disp_idx is None:
        return None

    # 4) Deteksi FVG di sekitar displacement
    fvg = detect_fvg_around(candles_5m, disp_idx, window=2)
    if not fvg.get("has_fvg"):
        return None

    fvg_dir = fvg.get("direction")
    fvg_low = fvg.get("low")
    fvg_high = fvg.get("high")
    fvg_quality = bool(fvg.get("quality_ok"))

    if fvg_low is None or fvg_high is None or fvg_high <= fvg_low:
        return None

    # Pastikan arah FVG selaras dengan side
    if side == "long" and fvg_dir != "bullish":
        return None
    if side == "short" and fvg_dir != "bearish":
        return None

    # 5) Bangun Entry/SL/TP dan SL% + leverage
    levels = build_levels_and_leverage(side, candles_5m, sweep_idx, fvg_low, fvg_high)

    entry = levels["entry"]
    sl = levels["sl"]
    tp1 = levels["tp1"]
    tp2 = levels["tp2"]
    tp3 = levels["tp3"]
    sl_pct = levels["sl_pct"]

    # Validasi R:R minimal (TP2 ~ >= RR 1.8–2.0)
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    rr_tp2 = abs(tp2 - entry) / risk
    good_rr = rr_tp2 >= 1.8

    # 6) Konteks HTF (15m & 1h)
    htf_ctx = get_htf_context(symbol)
    if side == "long":
        htf_alignment = bool(htf_ctx.get("htf_ok_long", True))
    else:
        htf_alignment = bool(htf_ctx.get("htf_ok_short", True))

    # 7) Evaluasi kualitas & Tier
    meta = {
        "has_liquidity": upper_liq is not None or lower_liq is not None,
        "has_sweep": True,
        "sweep_quality": sweep_quality,
        "has_displacement": True,
        "disp_bos": disp_bos,
        "has_fvg": True,
        "fvg_quality": fvg_quality,
        "good_rr": good_rr,
        "sl_pct": sl_pct,
        "htf_alignment": htf_alignment,
    }
    q = evaluate_signal_quality(meta)
    if not q["should_send"]:
        return None

    tier = q["tier"]
    score = q["score"]

    # 8) Bangun pesan Telegram (format ringkas + leverage + validitas + risk calc)
    direction_label = "LONG" if side == "long" else "SHORT"
    emoji = "🟢" if side == "long" else "🔴"

    lev_min = levels["lev_min"]
    lev_max = levels["lev_max"]

    lev_text = f"{lev_min:.0f}x–{lev_max:.0f}x"
    sl_pct_text = f"{sl_pct:.2f}%"

    # validitas sinyal (misal 6 candle 5m = 30 menit)
    max_age_candles = smc_settings.max_entry_age_candles
    approx_minutes = max_age_candles * 5
    valid_text = f"±{approx_minutes} menit" if approx_minutes > 0 else "singkat"

    # Risk calculator mini
    if sl_pct > 0:
        # multiplier = (1% / SL%) = 100 / sl_pct
        pos_mult = 100.0 / sl_pct
        example_balance = 100.0
        example_pos = pos_mult * example_balance
        risk_calc = (
            f"Risk Calc (contoh risiko 1%):\n"
            f"• SL : {sl_pct_text} → nilai posisi ≈ (1% / SL%) × balance ≈ {pos_mult:.1f}× balance\n"
            f"• Contoh balance 100 USDT → posisi ≈ {example_pos:.0f} USDT\n"
            f"(sesuaikan dengan balance & leverage kamu)"
        )
    else:
        risk_calc = "Risk Calc: SL% tidak valid (0), abaikan kalkulasi ini."

    text = (
        f"{emoji} SMC SIGNAL — {symbol.upper()} ({direction_label})\n"
        f"Entry : {entry:.4f}\n"
        f"SL    : {sl:.4f}\n"
        f"TP1   : {tp1:.4f}\n"
        f"TP2   : {tp2:.4f}\n"
        f"TP3   : {tp3:.4f}\n"
        f"Model : Sweep → FVG Retest\n"
        f"Rekomendasi Leverage : {lev_text} (SL {sl_pct_text})\n"
        f"Validitas Entry : {valid_text}\n"
        f"Tier : {tier} (Score {score})\n"
        f"{risk_calc}"
    )

    result = {
        "symbol": symbol.upper(),
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl_pct": sl_pct,
        "lev_min": lev_min,
        "lev_max": lev_max,
        "tier": tier,
        "score": score,
        "htf_context": htf_ctx,
        "message": text,
    }

    # 9) Log sinyal ke file
    log_signal(result)

    return result

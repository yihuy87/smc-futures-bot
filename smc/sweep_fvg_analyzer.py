# smc/sweep_fvg_analyzer.py
# Analisa utama SMC: Liquidity Sweep → Displacement → FVG → Entry/SL/TP.

from typing import List, Optional, Dict

from binance.ohlc_buffer import Candle
from smc.liquidity import detect_liquidity_zones, detect_sweep
from smc.displacement import detect_displacement
from smc.fvg_zones import detect_fvg_around
from smc.rr_leverage import build_levels_and_leverage
from smc.tiers import evaluate_signal_quality


def analyze_symbol_smc(symbol: str, candles_5m: List[Candle]) -> Optional[Dict]:
    """
    Analisa SMC intraday untuk satu symbol menggunakan data 5m.
    Fokus utama:
    - cari liquidity (equal highs / equal lows)
    - deteksi sweep (stop hunt)
    - deteksi displacement (impuls)
    - deteksi FVG
    - bangun Entry/SL/TP dan rekomendasi leverage
    - evaluasi kualitas → Tier → hanya kirim jika >= min_tier

    Return None jika tidak ada setup yang layak.
    """
    if len(candles_5m) < 30:
        return None

    # 1) Deteksi liquidity zones di history dekat
    liq = detect_liquidity_zones(candles_5m, lookback=40, tolerance_pct=0.001)
    upper_liq = liq.get("upper_liquidity")
    lower_liq = liq.get("lower_liquidity")

    if upper_liq is None and lower_liq is None:
        # tidak ada liquidity berarti, skip
        return None

    # 2) Deteksi sweep di beberapa candle terakhir
    sweep = detect_sweep(candles_5m, upper_liq, lower_liq, check_last_n=4)
    side = sweep.get("side")
    sweep_idx = sweep.get("index")

    if side not in ("long", "short") or sweep_idx is None:
        return None

    # 3) Deteksi displacement setelah sweep
    disp = detect_displacement(candles_5m, sweep_idx, look_ahead=2, body_factor=1.6)
    disp_idx = disp.get("index")
    if disp_idx is None:
        return None

    # 4) Deteksi FVG di sekitar displacement
    fvg = detect_fvg_around(candles_5m, disp_idx, window=2)
    if not fvg.get("has_fvg"):
        return None

    fvg_dir = fvg.get("direction")
    fvg_low = fvg.get("low")
    fvg_high = fvg.get("high")

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

    # Validasi R:R minimal
    # RR TP2 harus >= 2.0 (sekitar) agar setup sehat.
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    rr_tp2 = abs(tp2 - entry) / risk
    good_rr = rr_tp2 >= 1.8

    # 6) Evaluasi kualitas & Tier
    meta = {
        "has_liquidity": upper_liq is not None or lower_liq is not None,
        "has_sweep": True,
        "has_displacement": True,
        "has_fvg": True,
        "good_rr": good_rr,
        "sl_pct": sl_pct,
    }
    q = evaluate_signal_quality(meta)
    if not q["should_send"]:
        return None

    tier = q["tier"]

    # 7) Bangun pesan Telegram (format ringkas sesuai kesepakatan)
    direction_label = "LONG" if side == "long" else "SHORT"
    emoji = "🟢" if side == "long" else "🔴"

    lev_min = levels["lev_min"]
    lev_max = levels["lev_max"]

    # contoh: "15x–25x (SL 0.40%)"
    lev_text = f"{lev_min:.0f}x–{lev_max:.0f}x"
    sl_pct_text = f"{sl_pct:.2f}%"

    text = (
        f"{emoji} SMC SIGNAL — {symbol.upper()} ({direction_label})\n"
        f"Entry : {entry:.4f}\n"
        f"SL    : {sl:.4f}\n"
        f"TP1   : {tp1:.4f}\n"
        f"TP2   : {tp2:.4f}\n"
        f"TP3   : {tp3:.4f}\n"
        f"Model : Sweep → FVG Retest\n"
        f"Rekomendasi Leverage : {lev_text} (SL {sl_pct_text})"
    )

    return {
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
        "score": q["score"],
        "message": text,
  }

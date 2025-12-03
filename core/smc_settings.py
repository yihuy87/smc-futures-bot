# core/smc_settings.py
# Pengaturan umum strategi SMC Sweep → Displacement → FVG.

from dataclasses import dataclass

from config import (
    SMC_ENTRY_TF,
    SMC_MID_TF,
    SMC_HTF,
    SMC_MAX_ENTRY_AGE_CANDLES,
    MIN_TIER_TO_SEND,
)


@dataclass
class SMCSettings:
    """
    Konfigurasi strategi SMC intraday:
    - time frame entry & HTF
    - usia maksimal sinyal (berapa candle 5m)
    - minimum tier yang boleh dikirim (fallback)
    """

    entry_tf: str = SMC_ENTRY_TF      # misal "5m"
    mid_tf: str = SMC_MID_TF          # misal "15m"
    htf: str = SMC_HTF                # misal "1h"

    max_entry_age_candles: int = SMC_MAX_ENTRY_AGE_CANDLES

    # minimal tier yang boleh dikirim ("A+", "A", "B")
    min_tier_to_send: str = MIN_TIER_TO_SEND


smc_settings = SMCSettings()

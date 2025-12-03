# config.py
# Load konfigurasi dari environment (.env) dan sediakan default yang aman.

import os
from dotenv import load_dotenv

# Load variabel dari file .env (jika ada)
load_dotenv()

# === TELEGRAM ===
# Token bot Telegram (wajib diisi)
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "").strip()

# ID admin utama (chat_id Telegram kamu), simpan sebagai string agar aman dibandingkan langsung
TELEGRAM_ADMIN_ID: str = os.getenv("TELEGRAM_ADMIN_ID", "").strip()

# Username admin utama (misal: @namatelegramkamu)
TELEGRAM_ADMIN_USERNAME: str = os.getenv("TELEGRAM_ADMIN_USERNAME", "").strip()

# === BINANCE FUTURES (USDT PERPETUAL) ===
# REST & WebSocket endpoint resmi Binance Futures
BINANCE_REST_URL: str = os.getenv("BINANCE_REST_URL", "https://fapi.binance.com").strip()
BINANCE_STREAM_URL: str = os.getenv("BINANCE_STREAM_URL", "wss://fstream.binance.com/stream").strip()

# === FILTERING PASANGAN & SCAN BEHAVIOR ===

def _float_env(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        # izinkan underscore seperti 1_000_000.0
        return float(val.replace("_", ""))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return int(val.replace("_", ""))
    except ValueError:
        return default


# Minimum volume USDT 24 jam untuk pair yang akan discan
MIN_VOLUME_USDT: float = _float_env("MIN_VOLUME_USDT", 1_000_000.0)

# Berapa banyak pair USDT yang discan (set besar, nanti dibatasi filter volume)
MAX_USDT_PAIRS: int = _int_env("MAX_USDT_PAIRS", 1000)

# Tier minimum sinyal yang dikirim: "A+", "A", "B"
MIN_TIER_TO_SEND: str = os.getenv("MIN_TIER_TO_SEND", "A").strip().upper() or "A"

# Cooldown default antar sinyal per pair (detik)
SIGNAL_COOLDOWN_SECONDS: int = _int_env("SIGNAL_COOLDOWN_SECONDS", 1800)  # 30 menit

# Refresh interval untuk daftar pair (jam)
REFRESH_PAIR_INTERVAL_HOURS: int = _int_env("REFRESH_PAIR_INTERVAL_HOURS", 24)

# === SMC STRATEGY SETTINGS (GENERAL) ===
# Timeframe entry utama dan HTF yang digunakan di strategi Sweep → Displacement → FVG
SMC_ENTRY_TF: str = os.getenv("SMC_ENTRY_TF", "5m")
SMC_MID_TF: str = os.getenv("SMC_MID_TF", "15m")
SMC_HTF: str = os.getenv("SMC_HTF", "1h")

# Berapa banyak candle 5m ke depan sinyal dianggap masih valid (misal 6 = 30 menit)
SMC_MAX_ENTRY_AGE_CANDLES: int = _int_env("SMC_MAX_ENTRY_AGE_CANDLES", 6)

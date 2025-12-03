# binance/binance_stream.py
# WebSocket Binance Futures: listen 5m close, update OHLC buffer,
# panggil SMC analyzer, dan broadcast sinyal ke Telegram.

import asyncio
import json
import time
from typing import List, Optional

import websockets

from config import BINANCE_STREAM_URL, REFRESH_PAIR_INTERVAL_HOURS
from core.bot_state import (
    state,
    load_subscribers,
    load_vip_users,
    cleanup_expired_vip,
    load_bot_state,
)
from binance.binance_pairs import get_usdt_pairs
from binance.ohlc_buffer import OHLCBufferManager
from smc.sweep_fvg_analyzer import analyze_symbol_smc
from telegram.telegram_broadcast import broadcast_signal


async def run_smc_bot() -> None:
    """
    Loop utama SMC Futures scanner:
    - Load subscribers, VIP, dan bot_state.
    - Refresh daftar pair berdasarkan volume.
    - Buka WS untuk kline_5m multi-symbol.
    - Setiap candle 5m closed → update buffer → analisa SMC → kirim sinyal.
    """

    # load data persistent
    state.subscribers = load_subscribers()
    state.vip_users = load_vip_users()
    state.daily_date = time.strftime("%Y-%m-%d")
    cleanup_expired_vip()
    load_bot_state()

    print(f"Loaded {len(state.subscribers)} subscribers, {len(state.vip_users)} VIP users.")

    buffer_manager = OHLCBufferManager(max_candles=300)

    symbols: List[str] = []
    last_pairs_refresh: float = 0.0
    refresh_interval = REFRESH_PAIR_INTERVAL_HOURS * 3600

    while state.running:
        try:
            now = time.time()
            if (
                not symbols
                or (now - last_pairs_refresh) > refresh_interval
                or state.force_pairs_refresh
            ):
                print("Refresh daftar pair USDT berdasarkan volume...")
                symbols = get_usdt_pairs(state.max_pairs, state.min_volume_usdt)
                last_pairs_refresh = now
                state.force_pairs_refresh = False

                if not symbols:
                    print("Tidak ada pair yang cocok filter volume. Tunggu 30 detik...")
                    await asyncio.sleep(30)
                    continue

                print(f"Scan {len(symbols)} pair:", ", ".join(s.upper() for s in symbols))

            streams = "/".join([f"{s}@kline_5m" for s in symbols])
            ws_url = f"{BINANCE_STREAM_URL}?streams={streams}"

            print(f"Menghubungkan ke WebSocket: {ws_url}")
            async with websockets.connect(ws_url) as ws:
                print("WebSocket terhubung.")
                if state.scanning:
                    print("Scan sebelumnya AKTIF → melanjutkan scan otomatis.")
                else:
                    print("Bot dalam mode STANDBY. Gunakan /startscan untuk mulai scan.\n")

                while state.running:
                    # handle soft restart via admin
                    if state.request_soft_restart:
                        print("Soft restart diminta → memutus WS & refresh engine...")
                        state.request_soft_restart = False
                        break

                    # refresh pair jika interval tercapai
                    if time.time() - last_pairs_refresh > refresh_interval:
                        print("Interval refresh pair tercapai → refresh daftar pair & reconnect WebSocket...")
                        break

                    msg = await ws.recv()
                    data = json.loads(msg)

                    kline = data.get("data", {}).get("k", {})
                    if not kline:
                        continue

                    is_closed = kline.get("x", False)
                    symbol = kline.get("s", "")
                    if not symbol:
                        continue

                    # update buffer untuk semua kline (closed & updating),
                    # tapi analisa hanya di closed candle
                    buffer_manager.update_from_kline(symbol, kline)

                    if not is_closed:
                        continue

                    # Jika scanning OFF, skip analisa
                    if not state.scanning:
                        continue

                    now = time.time()

                    # Cooldown per symbol (sama seperti bot lama)
                    if state.cooldown_seconds > 0:
                        last_ts = state.last_signal_time.get(symbol)
                        if last_ts and now - last_ts < state.cooldown_seconds:
                            if state.debug:
                                print(
                                    f"[{symbol}] Skip cooldown "
                                    f"({int(now - last_ts)}s/{state.cooldown_seconds}s)"
                                )
                            continue

                    if state.debug:
                        print(f"[{time.strftime('%H:%M:%S')}] 5m close: {symbol}")

                    candles_5m = buffer_manager.get_candles(symbol)
                    if not candles_5m or len(candles_5m) < 20:
                        # butuh minimal beberapa candle untuk struktur
                        continue

                    # Analisa SMC Sweep → Displacement → FVG
                    signal = _analyze_with_smc(symbol, candles_5m)
                    if not signal:
                        continue

                    text = signal.get("message")
                    if not text:
                        continue

                    broadcast_signal(text)

                    state.last_signal_time[symbol] = now
                    tier = signal.get("tier", "?")
                    print(f"[{symbol}] Sinyal dikirim (Tier {tier}).")

        except websockets.ConnectionClosed:
            print("WebSocket terputus. Reconnect dalam 5 detik...")
            await asyncio.sleep(5)
        except Exception as e:
            print("Error di run_smc_bot (luar):", e)
            print("Coba reconnect dalam 5 detik...")
            await asyncio.sleep(5)

    print("run_smc_bot selesai karena state.running = False")


def _analyze_with_smc(symbol: str, candles_5m: list) -> Optional[dict]:
    """
    Wrapper kecil supaya jika nanti ada tambahan param (HTF, settings),
    cukup di sini saja yang diubah.
    """
    try:
        return analyze_symbol_smc(symbol, candles_5m)
    except Exception as e:
        # Jangan sampai satu error di SMC analyzer mematikan scanner
        print(f"[{symbol}] Error di analyze_symbol_smc:", e)
        return None

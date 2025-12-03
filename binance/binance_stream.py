# binance/binance_stream.py
# WebSocket scanner Binance Futures 5m + integrasi SMC Sweep–FVG analyzer.
#
# Fokus optimasi:
# - Hanya analisa di candle 5m yang sudah close (x == True)
# - Simpan candle dalam deque dengan panjang maksimum (hemat memori)
# - Refresh daftar pair berkala berdasarkan volume
# - Reconnect WebSocket otomatis jika putus
# - TIDAK mengubah logika strategi SMC (hanya cara data di-stream & di-manage)

import asyncio
import json
import time
from collections import deque
from typing import Dict, Deque

import websockets

from config import BINANCE_STREAM_URL, REFRESH_PAIR_INTERVAL_HOURS
from binance.binance_pairs import get_usdt_pairs
from core.bot_state import (
    state,
    load_subscribers,
    load_vip_users,
    cleanup_expired_vip,
    load_bot_state,
)
from core.smc_settings import smc_settings
from smc.sweep_fvg_analyzer import analyze_symbol_smc
from telegram.telegram_broadcast import broadcast_signal


# Tipe candle ringan untuk 5m
from typing import TypedDict


class Candle(TypedDict):
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


# Simpan maksimal N candle per symbol (strategi cuma perlu ~40, kita kasih buffer)
MAX_5M_CANDLES = 120


async def run_smc_bot():
    """
    Main loop SMC Futures bot:
    - Load subscribers/VIP/state
    - Ambil daftar pair USDT perpetual (filter volume)
    - Hubungkan WebSocket multi-stream kline_5m
    - Build candle 5m per symbol di memori (deque terbatas)
    - Setiap candle close → run SMC analyzer → kirim sinyal kalau valid
    """

    # Load state persistent (sama seperti bot lama, TIDAK mengubah akurasi)
    state.subscribers = load_subscribers()
    state.vip_users = load_vip_users()
    state.daily_date = time.strftime("%Y-%m-%d")
    cleanup_expired_vip()
    load_bot_state()

    print(f"Loaded {len(state.subscribers)} subscribers, {len(state.vip_users)} VIP users.")

    symbols: list[str] = []
    last_pairs_refresh: float = 0.0
    refresh_interval = REFRESH_PAIR_INTERVAL_HOURS * 3600

    # buffer candle per symbol
    candles_5m: Dict[str, Deque[Candle]] = {}

    while state.running:
        try:
            now = time.time()
            need_refresh_pairs = (
                not symbols
                or (now - last_pairs_refresh) > refresh_interval
                or state.force_pairs_refresh
            )

            if need_refresh_pairs:
                print("Refresh daftar pair USDT perpetual berdasarkan volume...")
                symbols = get_usdt_pairs(state.max_pairs, state.min_volume_usdt)
                last_pairs_refresh = now
                state.force_pairs_refresh = False

                # reset buffer hanya untuk symbol yang tidak lagi dipakai
                current_set = set(s.upper() for s in symbols)
                candles_5m = {
                    sym: buf for sym, buf in candles_5m.items() if sym in current_set
                }

                print(f"Scan {len(symbols)} pair:", ", ".join(s.upper() for s in symbols))

            if not symbols:
                print("Tidak ada symbol untuk discan. Tidur sebentar...")
                await asyncio.sleep(5)
                continue

            # Build multi-stream URL
            streams = "/".join(f"{s}@kline_5m" for s in symbols)
            ws_url = f"{BINANCE_STREAM_URL}?streams={streams}"

            print(f"Menghubungkan ke WebSocket: {ws_url}")
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                print("WebSocket terhubung.")
                if state.scanning:
                    print("Scan sebelumnya AKTIF → melanjutkan scan otomatis.")
                else:
                    print("Bot dalam mode STANDBY. Gunakan /startscan untuk mulai scan.\n")

                while state.running:
                    # Soft restart diminta dari Telegram
                    if state.request_soft_restart:
                        print("Soft restart diminta → memutus WS & refresh engine...")
                        state.request_soft_restart = False
                        break

                    # Perlu refresh daftar pair?
                    if time.time() - last_pairs_refresh > refresh_interval:
                        print("Interval refresh pair tercapai → refresh daftar pair & reconnect WebSocket...")
                        break

                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=60)
                    except asyncio.TimeoutError:
                        # Keep connection alive – kirim ping otomatis (handled by websockets)
                        if state.debug:
                            print("Timeout menunggu data WebSocket, lanjut...")
                        continue

                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        if state.debug:
                            print("Gagal decode JSON dari WebSocket.")
                        continue

                    kline = data.get("data", {}).get("k")
                    if not kline:
                        continue

                    is_closed = kline.get("x", False)
                    symbol = kline.get("s", "").upper()

                    if not symbol:
                        continue

                    # update buffer candle hanya ketika candle 5m close
                    if not is_closed:
                        continue

                    # Bangun candle 5m (ringan)
                    try:
                        candle: Candle = {
                            "open_time": int(kline["t"]),
                            "open": float(kline["o"]),
                            "high": float(kline["h"]),
                            "low": float(kline["l"]),
                            "close": float(kline["c"]),
                            "volume": float(kline["v"]),
                            "close_time": int(kline["T"]),
                        }
                    except (KeyError, ValueError, TypeError):
                        if state.debug:
                            print(f"[{symbol}] Gagal parse kline.")
                        continue

                    buf = candles_5m.get(symbol)
                    if buf is None:
                        buf = deque(maxlen=MAX_5M_CANDLES)
                        candles_5m[symbol] = buf
                    buf.append(candle)

                    if state.debug:
                        print(f"[{time.strftime('%H:%M:%S')}] 5m close: {symbol} — total candle: {len(buf)}")

                    # Kalau scan belum diaktifkan, skip analisa
                    if not state.scanning:
                        continue

                    # Pastikan cukup candle untuk SMC (strategi butuh ~40 candle)
                    if len(buf) < 40:
                        continue

                    # Cek cooldown per symbol
                    now_ts = time.time()
                    if state.cooldown_seconds > 0:
                        last_ts = state.last_signal_time.get(symbol)
                        if last_ts and now_ts - last_ts < state.cooldown_seconds:
                            if state.debug:
                                print(
                                    f"[{symbol}] Skip cooldown "
                                    f"({int(now_ts - last_ts)}s/{state.cooldown_seconds}s)"
                                )
                            continue

                    # ANALISA SMC — TIDAK DIUBAH (hanya diberi data 5m terakhir)
                    # Untuk efisiensi: cukup kirim ~80 candle terakhir (lebih dari cukup untuk lookback=40)
                    recent_candles = list(buf)[-80:]

                    result = analyze_symbol_smc(symbol, recent_candles)
                    if not result:
                        continue

                    text = result["message"]
                    broadcast_signal(text)

                    state.last_signal_time[symbol] = now_ts
                    print(
                        f"[{symbol}] Sinyal dikirim: "
                        f"Tier {result['tier']} (Score {result['score']}) "
                        f"Entry {result['entry']:.4f} SL {result['sl']:.4f}"
                    )

        except websockets.ConnectionClosed:
            print("WebSocket terputus. Reconnect dalam 5 detik...")
            await asyncio.sleep(5)
        except Exception as e:
            print("Error di run_smc_bot (luar):", e)
            print("Coba reconnect dalam 5 detik...")
            await asyncio.sleep(5)

    print("run_smc_bot selesai karena state.running = False")

# main.py
# Entry point: start Telegram command loop + SMC Futures scanner loop.

import asyncio
import threading

from core.bot_state import state
from telegram.telegram_core import telegram_command_loop
from binance.binance_stream import run_smc_bot


def main() -> None:
    """
    Start:
    - Telegram command loop (thread terpisah, sync, pakai getUpdates)
    - Binance SMC scanner (asyncio, WebSocket)
    """
    # Jalankan loop command Telegram di thread terpisah
    cmd_thread = threading.Thread(target=telegram_command_loop, daemon=True)
    cmd_thread.start()

    try:
        asyncio.run(run_smc_bot())
    except KeyboardInterrupt:
        state.running = False
        print("Bot dihentikan oleh user (CTRL+C).")
    except Exception as e:
        state.running = False
        print("Fatal error di main:", e)


if __name__ == "__main__":
    main()

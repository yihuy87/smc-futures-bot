# SMC Futures Sweep-FVG Bot

Bot Telegram untuk sinyal trading **SMC intraday (LONG & SHORT)** di Binance Futures USDT Perpetual.  
Bot akan otomatis scan banyak pair USDT, deteksi **Liquidity Sweep → Displacement → FVG Retest**, lalu kirim sinyal ke Telegram.

Contoh format sinyal:

🟢 SMC SIGNAL — BTCUSDT (LONG)  
Entry : 67350  
SL    : 67080  
TP1   : 67500  
TP2   : 67720  
TP3   : 68100  
Model : Sweep → FVG Retest  
Rekomendasi Leverage : 15x–25x (SL 0.40%)

---

## Setup

### 1. Buat bot Telegram

- Chat ke **@BotFather**
- `/newbot` → ambil **BOT TOKEN**

### 2. Ambil chat ID admin

- Chat ke **@userinfobot**
- Catat `Your user ID` → itu **TELEGRAM_ADMIN_ID**

### 3. Clone / download repo ini

```bash
git clone https://github.com/yihuy87/smc-futures-bot.git
cd smc-futures-bot

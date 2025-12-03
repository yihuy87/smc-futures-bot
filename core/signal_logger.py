# core/signal_logger.py
# Logging sinyal + auto-hapus file log lama

import os
import json
import time
from typing import Dict, Any

LOG_DIR = "logs"
RETENTION_DAYS = 14  # auto-hapus file log lebih dari 14 hari


def _cleanup_old_logs():
    """
    Hapus file log yang lebih tua dari RETENTION_DAYS.
    """
    if not os.path.exists(LOG_DIR):
        return

    now = time.time()
    cutoff = RETENTION_DAYS * 86400  # detik

    for fname in os.listdir(LOG_DIR):
        if not fname.startswith("signals_") or not fname.endswith(".log"):
            continue

        fpath = os.path.join(LOG_DIR, fname)
        try:
            mtime = os.path.getmtime(fpath)
        except Exception:
            continue

        if now - mtime > cutoff:
            try:
                os.remove(fpath)
                print(f"[LOG CLEANUP] Hapus file lama: {fname}")
            except Exception as e:
                print(f"[LOG CLEANUP] Gagal hapus {fname}: {e}")


def log_signal(signal: Dict[str, Any]) -> None:
    """
    Simpan sinyal ke file log, dan hapus file yang lebih tua dari RETENTION_DAYS.
    Dipanggil dari smc/sweep_fvg_analyzer.py
    """
    try:
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR, exist_ok=True)

        date_str = time.strftime("%Y-%m-%d")
        log_file = os.path.join(LOG_DIR, f"signals_{date_str}.log")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(signal, ensure_ascii=False) + "\n")

        _cleanup_old_logs()
    except Exception as e:
        print("Gagal menulis log sinyal:", e)

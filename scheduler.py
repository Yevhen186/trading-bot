"""
scheduler.py — Автозапуск оркестратора кожні 4 години
Запускається на Railway як worker процес
"""

import time
import traceback
from datetime import datetime
from orchestrator import run_orchestrator
from telegram_notify import send_error, send_startup

INTERVAL_HOURS = 4
INTERVAL_SEC   = INTERVAL_HOURS * 60 * 60


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


log("🚀 Trading Bot scheduler запущено на Railway")
log(f"⏰ Інтервал: кожні {INTERVAL_HOURS} години")

send_startup()

while True:
    try:
        log("▶️  Запускаю аналіз...")
        run_orchestrator()
        log(f"✅ Аналіз завершено. Наступний через {INTERVAL_HOURS} год.")
    except Exception as e:
        error_msg = traceback.format_exc()
        log(f"❌ Помилка: {e}")
        send_error(str(error_msg))

    time.sleep(INTERVAL_SEC)

"""
telegram_notify.py — Telegram нотифікації для Trading Bot
Імпортується в orchestrator.py
"""

import os
import requests
from datetime import datetime

# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = "ETHUSDT"
# ─────────────────────────────────────────────


def send_message(text: str) -> bool:
    """Відправляє повідомлення в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"⚠️ Telegram помилка: {e}")
        return False


def send_signal(result: dict) -> bool:
    """Формує і відправляє повний звіт оркестратора."""
    decision = result.get("decision", "WAIT")
    reason   = result.get("reason", "")
    trade    = result.get("trade", {})
    summary  = result.get("summary", "")
    signals  = result.get("signals", {})
    ts       = result.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    d_icon = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}.get(decision, "⚪")

    # Голоси кожного агента
    votes_lines = ""
    for agent, sig in signals.items():
        s_icon = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}.get(sig, "⚪")
        votes_lines += f"  {s_icon} {agent}: <b>{sig}</b>\n"

    # Параметри угоди якщо є сигнал
    trade_block = ""
    if trade and decision in ("BUY", "SELL"):
        trade_block = (
            f"\n💰 <b>ПАРАМЕТРИ УГОДИ</b>\n"
            f"  Вхід:        <code>${trade['entry']:,.2f}</code>\n"
            f"  Розмір:      <code>${trade['size_usd']}</code> ({trade['qty_eth']} ETH)\n"
            f"  Стоп-лос:    <code>${trade['sl']:,.2f}</code>  (ризик ${trade['risk']})\n"
            f"  Тейк-профіт: <code>${trade['tp']:,.2f}</code>  (профіт ${trade['profit']})\n"
            f"  R:R ratio:   <code>1:{trade['rr']}</code>\n"
        )

    # Обрізаємо до 800 символів — ліміт Telegram
    short_summary = summary[:800] + "..." if len(summary) > 800 else summary

    msg = (
        f"🤖 <b>TRADING BOT — {SYMBOL}</b>\n"
        f"🕐 {ts}\n"
        f"{'─'*30}\n"
        f"\n🗳️ <b>ГОЛОСУВАННЯ АГЕНТІВ</b>\n"
        f"{votes_lines}"
        f"\n{d_icon} <b>РІШЕННЯ: {decision}</b>\n"
        f"<i>{reason}</i>\n"
        f"{trade_block}"
        f"\n📋 <b>АНАЛІЗ</b>\n"
        f"{short_summary}\n"
        f"{'─'*30}\n"
        f"⚡ Multi-Agent Trading System"
    )

    return send_message(msg)


def send_error(error_text: str) -> bool:
    """Відправляє повідомлення про помилку."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"⚠️ <b>TRADING BOT — ПОМИЛКА</b>\n"
        f"🕐 {ts}\n\n"
        f"<code>{error_text[:500]}</code>"
    )
    return send_message(msg)


def send_startup() -> bool:
    """Стартове повідомлення при запуску бота."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"🚀 <b>Trading Bot запущено</b>\n"
        f"🕐 {ts}\n\n"
        f"📊 Пара: <b>{SYMBOL}</b>\n"
        f"🤖 Агенти: TA Agent + News Agent\n"
        f"⏰ Аналіз кожні 4 години\n\n"
        f"Система активна і моніторить ринок."
    )
    return send_message(msg)


if __name__ == "__main__":
    print("Відправляю тестове повідомлення...")
    ok = send_message(
        "✅ <b>Telegram нотифікації налаштовано!</b>\n\n"
        "Trading Bot підключено успішно.\n"
        "Будеш отримувати сигнали після кожного аналізу."
    )
    if ok:
        print("✅ Повідомлення відправлено! Перевір Telegram.")
    else:
        print("❌ Помилка. Перевір токен і chat_id.")

"""
orchestrator.py — Multi-Agent Crypto Trading Orchestrator
+ Telegram нотифікації

Запуск: python orchestrator.py
Всі файли мають лежати в одній папці (Desktop):
  - orchestrator.py
  - ta_agent_v2.py
  - news_agent.py
  - telegram_notify.py
"""

import sys
from datetime import datetime

# ─────────────────────────────────────────────
try:
    from ta_agent_v2 import get_candles, calculate_indicators, check_conditions, generate_signal
    from ta_agent_v2 import SYMBOL, INTERVAL, LIMIT
except ImportError as e:
    print(f"❌ Не знайдено ta_agent_v2.py: {e}")
    sys.exit(1)

try:
    from news_agent import run_news_agent, GROQ_API_KEY
    from groq import Groq
except ImportError as e:
    print(f"❌ Не знайдено news_agent.py або groq: {e}")
    sys.exit(1)

try:
    from telegram_notify import send_signal, send_error, send_startup
    TELEGRAM_ENABLED = True
except ImportError:
    print("⚠️  telegram_notify.py не знайдено — Telegram вимкнено")
    TELEGRAM_ENABLED = False


# ─────────────────────────────────────────────
DEPOSIT          = 100.0
RISK_PER_TRADE   = 0.02
STOP_LOSS_PCT    = 0.015
TAKE_PROFIT_PCT  = 0.03
GROQ_MODEL       = "llama-3.3-70b-versatile"
MIN_BUY_VOTES    = 2
TOTAL_AGENTS     = 2


# ─────────────────────────────────────────────
def get_ta_result() -> dict:
    df = get_candles(SYMBOL, INTERVAL, LIMIT)
    df = calculate_indicators(df)
    last, prev = df.iloc[-1], df.iloc[-2]
    data   = check_conditions(last, prev)
    result = generate_signal(data)

    raw = result.get("signal", "WAIT")
    if   "BUY"  in raw.upper(): norm = "BUY"
    elif "SELL" in raw.upper(): norm = "SELL"
    else:                        norm = "WAIT"

    return {
        "signal":         norm,
        "signal_raw":     raw,
        "current_price":  result["price"],
        "rsi":            round(result["rsi"], 2),
        "ema_fast":       round(result["ema_fast"], 2),
        "ema_slow":       round(result["ema_slow"], 2),
        "volume_ratio":   round(result["volume_ratio"], 2),
        "atr_pct":        round(result["atr_pct"], 2),
        "conditions_met": max(result["buy_score"], result["sell_score"]),
    }


def get_news_result() -> dict:
    result = run_news_agent()
    raw = result.get("signal", "NEUTRAL")
    if   "BULLISH" in raw.upper(): norm = "BUY"
    elif "BEARISH" in raw.upper(): norm = "SELL"
    else:                           norm = "WAIT"

    return {
        "signal":     norm,
        "signal_raw": raw,
        "fear_greed": result.get("fear_greed_value", 0),
        "fg_label":   result.get("fear_greed_label", ""),
        "analysis":   result.get("analysis", ""),
    }


def vote(signals: dict) -> tuple:
    buy  = sum(1 for s in signals.values() if s == "BUY")
    sell = sum(1 for s in signals.values() if s == "SELL")
    if buy  >= MIN_BUY_VOTES: return "BUY",  f"Консенсус BUY: {buy}/{TOTAL_AGENTS}"
    if sell >= MIN_BUY_VOTES: return "SELL", f"Консенсус SELL: {sell}/{TOTAL_AGENTS}"
    detail = " | ".join(f"{k}: {v}" for k, v in signals.items())
    return "WAIT", f"Немає консенсусу ({detail})"


def calc_trade(price: float, direction: str) -> dict:
    size = DEPOSIT * RISK_PER_TRADE
    sl = price * (1 - STOP_LOSS_PCT)   if direction == "BUY" else price * (1 + STOP_LOSS_PCT)
    tp = price * (1 + TAKE_PROFIT_PCT) if direction == "BUY" else price * (1 - TAKE_PROFIT_PCT)
    return {
        "size_usd": round(size, 2),
        "qty_eth":  round(size / price, 6),
        "entry":    round(price, 2),
        "sl":       round(sl, 2),
        "tp":       round(tp, 2),
        "risk":     round(size * STOP_LOSS_PCT, 3),
        "profit":   round(size * TAKE_PROFIT_PCT, 3),
        "rr":       round(TAKE_PROFIT_PCT / STOP_LOSS_PCT, 1),
    }


def llm_summary(ta, news, decision, reason, trade) -> str:
    client = Groq(api_key=GROQ_API_KEY)
    trade_block = ""
    if trade:
        trade_block = (f"\nПараметри: вхід ${trade['entry']} | SL ${trade['sl']} | "
                       f"TP ${trade['tp']} | Ризик ${trade['risk']} | Профіт ${trade['profit']}")
    prompt = f"""Ти — старший трейдинг-аналітик. Зроби фінальний звіт по ETHUSDT.

ТА АГЕНТ: {ta['signal']} ({ta['conditions_met']}/4 умов) | RSI={ta['rsi']} | EMA20={ta['ema_fast']} / EMA50={ta['ema_slow']} | Обсяг: {ta['volume_ratio']}x
NEWS АГЕНТ: {news['signal_raw']} | Fear & Greed: {news['fear_greed']}/100 ({news['fg_label']})
РІШЕННЯ: {decision} — {reason}{trade_block}

Напиши 4-5 речень українською: що показують індикатори, який настрій ринку, чому таке рішення, на що звернути увагу. Без води."""
    try:
        r = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=500,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"(LLM недоступний: {e})"


# ─────────────────────────────────────────────
def run_orchestrator():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "═"*58)
    print(f"  🤖 MULTI-AGENT TRADING ORCHESTRATOR")
    print(f"  {SYMBOL} | {ts}")
    print("═"*58)

    # ── 1. TA Agent ──
    print("\n📊 [1/3] TA Agent...")
    try:
        ta = get_ta_result()
        print(f"   {ta['signal_raw']} | RSI={ta['rsi']} | Умов: {ta['conditions_met']}/4 | ${ta['current_price']:,.2f}")
    except Exception as e:
        print(f"   ⚠️ Помилка: {e}")
        if TELEGRAM_ENABLED: send_error(f"TA Agent помилка: {e}")
        ta = {"signal":"WAIT","signal_raw":"WAIT","current_price":0,"rsi":0,
              "ema_fast":0,"ema_slow":0,"volume_ratio":0,"atr_pct":0,"conditions_met":0}

    # ── 2. News Agent ──
    print("\n📰 [2/3] News Agent...")
    try:
        news = get_news_result()
        print(f"   {news['signal_raw']} | F&G: {news['fear_greed']}/100 ({news['fg_label']})")
    except Exception as e:
        print(f"   ⚠️ Помилка: {e}")
        if TELEGRAM_ENABLED: send_error(f"News Agent помилка: {e}")
        news = {"signal":"WAIT","signal_raw":"NEUTRAL","fear_greed":0,"fg_label":"N/A","analysis":""}

    # ── 3. Голосування ──
    signals = {"TA Agent": ta["signal"], "News Agent": news["signal"]}

    print("\n🗳️  [3/3] Голосування:")
    for agent, sig in signals.items():
        icon = {"BUY":"🟢","SELL":"🔴","WAIT":"🟡"}.get(sig,"⚪")
        print(f"   {icon} {agent:<15} {sig}")

    decision, reason = vote(signals)

    trade = {}
    if decision in ("BUY","SELL") and ta["current_price"] > 0:
        trade = calc_trade(ta["current_price"], decision)

    print("\n🧠 Генерую фінальний аналіз...")
    summary = llm_summary(ta, news, decision, reason, trade)

    # ── Виводимо в консоль ──
    d_icon = {"BUY":"🟢 BUY","SELL":"🔴 SELL","WAIT":"🟡 WAIT"}.get(decision, decision)
    print("\n" + "═"*58)
    print(f"  РІШЕННЯ: {d_icon}")
    print(f"  {reason}")
    print("═"*58)

    if trade:
        print(f"\n💰 ПАРАМЕТРИ УГОДИ:")
        print(f"   Вхід:         ${trade['entry']:,.2f}")
        print(f"   Розмір:       ${trade['size_usd']} ({trade['qty_eth']} ETH)")
        print(f"   Стоп-лос:     ${trade['sl']:,.2f}  (ризик ${trade['risk']})")
        print(f"   Тейк-профіт:  ${trade['tp']:,.2f}  (профіт ${trade['profit']})")
        print(f"   R:R ratio:    1:{trade['rr']}")

    print(f"\n📋 АНАЛІЗ:")
    print(summary)
    print("\n" + "═"*58 + "\n")

    # ── Telegram ──
    result = {
        "timestamp": ts,
        "symbol":    SYMBOL,
        "signals":   signals,
        "decision":  decision,
        "reason":    reason,
        "trade":     trade,
        "summary":   summary,
    }

    if TELEGRAM_ENABLED:
        print("📲 Відправляю в Telegram...")
        ok = send_signal(result)
        print("   ✅ Відправлено!" if ok else "   ⚠️ Помилка відправки")

    return result


if __name__ == "__main__":
    if TELEGRAM_ENABLED:
        send_startup()
    run_orchestrator()

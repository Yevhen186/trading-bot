import requests
import pandas as pd
import ta
from datetime import datetime

# ─── НАЛАШТУВАННЯ ─────────────────────────────────────────
SYMBOL = "ETHUSDT"
INTERVAL = "4h"
LIMIT = 200  # більше даних = точніші індикатори

# Індикатори
RSI_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
VOLUME_SMA = 20
ATR_PERIOD = 14

# Умови сигналу
RSI_BUY_MIN = 40
RSI_BUY_MAX = 60
RSI_SELL_MIN = 60
RSI_SELL_MAX = 80
VOLUME_MULTIPLIER = 1.3  # обсяг має бути на 30% вище норми
MIN_CONDITIONS = 3        # мінімум умов для сигналу (з 4)
# ──────────────────────────────────────────────────────────


def get_candles(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Отримує свічки з Binance публічного API (з резервним URL)"""

    urls = [
        "https://api.binance.com/api/v3/klines",
        "https://api1.binance.com/api/v3/klines",
        "https://api2.binance.com/api/v3/klines",
        "https://api3.binance.com/api/v3/klines",
    ]

    params = {"symbol": symbol, "interval": interval, "limit": limit}
    last_error = None

    for url in urls:
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])

            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col])

            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            return df

        except requests.exceptions.HTTPError as e:
            last_error = f"❌ Binance API помилка: {e}"
            continue
        except requests.exceptions.ConnectionError:
            last_error = "❌ Немає з'єднання з Binance."
            continue

    raise Exception(last_error or "❌ Всі Binance endpoints недоступні.")


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Рахує всі індикатори"""
    df["ema_fast"] = ta.trend.EMAIndicator(df["close"], window=EMA_FAST).ema_indicator()
    df["ema_slow"] = ta.trend.EMAIndicator(df["close"], window=EMA_SLOW).ema_indicator()
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=RSI_PERIOD).rsi()
    df["volume_sma"] = df["volume"].rolling(window=VOLUME_SMA).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma"]
    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=ATR_PERIOD
    ).average_true_range()
    df["atr_pct"] = (df["atr"] / df["close"]) * 100
    return df


def check_conditions(last: pd.Series, prev: pd.Series) -> dict:
    """Перевіряє всі умови і повертає детальний звіт"""

    price = last["close"]
    rsi = last["rsi"]
    ema_fast = last["ema_fast"]
    ema_slow = last["ema_slow"]
    volume_ratio = last["volume_ratio"]
    atr_pct = last["atr_pct"]

    buy_conditions = {
        "trend_up": {
            "met": ema_fast > ema_slow,
            "label": f"Тренд ↑ (EMA{EMA_FAST} {ema_fast:.1f} > EMA{EMA_SLOW} {ema_slow:.1f})"
        },
        "momentum_ok": {
            "met": RSI_BUY_MIN <= rsi <= RSI_BUY_MAX,
            "label": f"RSI в зоні ({rsi:.1f} між {RSI_BUY_MIN}-{RSI_BUY_MAX})"
        },
        "volume_confirmed": {
            "met": volume_ratio >= VOLUME_MULTIPLIER,
            "label": f"Обсяг підвищений ({volume_ratio:.2f}x від норми)"
        },
        "volatility_ok": {
            "met": atr_pct < 3.0,
            "label": f"Волатильність прийнятна (ATR={atr_pct:.2f}%)"
        }
    }

    sell_conditions = {
        "trend_down": {
            "met": ema_fast < ema_slow,
            "label": f"Тренд ↓ (EMA{EMA_FAST} < EMA{EMA_SLOW})"
        },
        "momentum_weak": {
            "met": RSI_SELL_MIN <= rsi <= RSI_SELL_MAX,
            "label": f"RSI в зоні продажу ({rsi:.1f} між {RSI_SELL_MIN}-{RSI_SELL_MAX})"
        },
        "volume_confirmed": {
            "met": volume_ratio >= VOLUME_MULTIPLIER,
            "label": f"Обсяг підвищений ({volume_ratio:.2f}x від норми)"
        },
        "volatility_ok": {
            "met": atr_pct < 3.0,
            "label": f"Волатильність прийнятна (ATR={atr_pct:.2f}%)"
        }
    }

    buy_score = sum(1 for c in buy_conditions.values() if c["met"])
    sell_score = sum(1 for c in sell_conditions.values() if c["met"])

    return {
        "price": price,
        "rsi": rsi,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "volume_ratio": volume_ratio,
        "atr_pct": atr_pct,
        "buy_conditions": buy_conditions,
        "sell_conditions": sell_conditions,
        "buy_score": buy_score,
        "sell_score": sell_score,
    }


def generate_signal(data: dict) -> dict:
    """Генерує фінальний сигнал на основі умов"""

    buy_score = data["buy_score"]
    sell_score = data["sell_score"]
    price = data["price"]

    stop_loss = round(price * 0.985, 2)
    take_profit = round(price * 1.03, 2)

    if buy_score >= MIN_CONDITIONS and buy_score > sell_score:
        signal = "✅ BUY"
        strength = f"{buy_score}/4 умов виконано"
    elif sell_score >= MIN_CONDITIONS and sell_score > buy_score:
        signal = "🔴 SELL"
        strength = f"{sell_score}/4 умов виконано"
    elif buy_score == sell_score and buy_score >= 2:
        signal = "⚠️ КОНФЛІКТ"
        strength = f"BUY={buy_score} SELL={sell_score} — ринок невизначений"
    else:
        signal = "⏸ WAIT"
        strength = f"BUY={buy_score}/4, SELL={sell_score}/4 — недостатньо умов"

    return {**data, "signal": signal, "strength": strength,
            "stop_loss": stop_loss, "take_profit": take_profit}


def print_report(result: dict):
    """Виводить красивий звіт в консоль"""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    print(f"\n{'═'*55}")
    print(f"  TA AGENT v2 — {SYMBOL} [{INTERVAL}]  |  {now}")
    print(f"{'═'*55}")

    print(f"\n📊 РИНКОВІ ДАНІ:")
    print(f"   Ціна:          ${result['price']:,.2f}")
    print(f"   RSI({RSI_PERIOD}):        {result['rsi']:.2f}")
    print(f"   EMA{EMA_FAST}:          {result['ema_fast']:.2f}")
    print(f"   EMA{EMA_SLOW}:          {result['ema_slow']:.2f}")
    print(f"   Обсяг / норма: {result['volume_ratio']:.2f}x")
    print(f"   ATR (4h):      {result['atr_pct']:.2f}% від ціни")

    print(f"\n🔍 АНАЛІЗ УМОВ:")

    if result["buy_score"] >= result["sell_score"]:
        conditions = result["buy_conditions"]
    else:
        conditions = result["sell_conditions"]

    for key, cond in conditions.items():
        icon = "✅" if cond["met"] else "❌"
        print(f"   {icon} {cond['label']}")

    print(f"\n{'─'*55}")
    print(f"  🎯 СИГНАЛ:  {result['signal']}")
    print(f"  📊 Сила:    {result['strength']}")
    print(f"{'─'*55}")

    if "BUY" in result["signal"]:
        print(f"\n  📌 Стоп-лос:    ${result['stop_loss']:,.2f}  (-1.5%)")
        print(f"  📌 Тейк-профіт: ${result['take_profit']:,.2f}  (+3.0%)")

    print(f"{'═'*55}\n")


def run_ta_agent():
    print("📡 Отримую дані з Binance...")
    df = get_candles(SYMBOL, INTERVAL, LIMIT)

    print("📊 Рахую індикатори...")
    df = calculate_indicators(df)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    data = check_conditions(last, prev)
    result = generate_signal(data)
    print_report(result)


if __name__ == "__main__":
    run_ta_agent()

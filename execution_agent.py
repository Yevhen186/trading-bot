# execution_agent.py
import os
import json
import time
import logging
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Конфігурація ---
API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")
SYMBOL = "ETHUSDT"
TRADE_STATE_FILE = "trade_state.json"

# Ризик-параметри (мають збігатись з orchestrator.py)
MAX_OPEN_TRADES = 2
MAX_TRADE_USDT = 15.0        # 2% від $100
STOP_LOSS_PCT = 0.015       # 1.5%
TAKE_PROFIT_PCT = 0.03      # 3.0%


# --- Ініціалізація клієнта ---
def get_client() -> Client:
    client = Client(API_KEY, API_SECRET, testnet=True)
    # Тестнет використовує інший base URL для futures/spot
    client.API_URL = "https://testnet.binance.vision/api"
    return client


# --- Робота з файлом стану ---
def load_trade_state() -> dict:
    if os.path.exists(TRADE_STATE_FILE):
        with open(TRADE_STATE_FILE, "r") as f:
            return json.load(f)
    return {"open_trades": [], "closed_trades": [], "total_pnl": 0.0}


def save_trade_state(state: dict):
    with open(TRADE_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# --- Отримати поточну ціну ---
def get_current_price(client: Client, symbol: str) -> float:
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


# --- Розрахунок кількості BTC для угоди ---
def calculate_quantity(client: Client, usdt_amount: float, symbol: str) -> float:
    price = get_current_price(client, symbol)
    raw_qty = usdt_amount / price

    # Отримуємо точність символу з біржі
    info = client.get_symbol_info(symbol)
    lot_size_filter = next(f for f in info["filters"] if f["filterType"] == "LOT_SIZE")
    step_size = float(lot_size_filter["stepSize"])

    # Округлюємо вниз до дозволеного кроку
    precision = len(str(step_size).rstrip("0").split(".")[-1])
    quantity = float(f"{raw_qty - (raw_qty % step_size):.{precision}f}")

    logger.info(f"Ціна: {price} | Raw qty: {raw_qty:.8f} | Округлена qty: {quantity}")
    return quantity


# --- Відкриття позиції ---
def open_trade(signal: str, price: float, atr: float = None) -> dict | None:
    """
    signal: 'BUY' або 'SELL'
    price: поточна ціна (передається з orchestrator)
    atr: для динамічного SL/TP (опційно)
    """
    state = load_trade_state()

    # Перевірка ліміту відкритих угод
    if len(state["open_trades"]) >= MAX_OPEN_TRADES:
        logger.warning(f"Досягнуто максимум відкритих угод ({MAX_OPEN_TRADES}). Пропускаємо.")
        return None

    # Перевірка чи вже є угода по цьому символу
    for trade in state["open_trades"]:
        if trade["symbol"] == SYMBOL:
            logger.warning(f"Вже є відкрита угода по {SYMBOL}. Пропускаємо.")
            return None

    try:
        client = get_client()
        quantity = calculate_quantity(client, MAX_TRADE_USDT, SYMBOL)

        if quantity <= 0:
            logger.error("Розрахована кількість = 0. Перевір баланс або суму угоди.")
            return None

        # Розрахунок SL/TP
        if signal == "BUY":
            sl_price = round(price * (1 - STOP_LOSS_PCT), 2)
            tp_price = round(price * (1 + TAKE_PROFIT_PCT), 2)
            side = "BUY"
        else:  # SELL (short — тільки для futures, на spot не актуально)
            sl_price = round(price * (1 + STOP_LOSS_PCT), 2)
            tp_price = round(price * (1 - TAKE_PROFIT_PCT), 2)
            side = "SELL"

        # Відкриваємо ринковий ордер
        order = client.order_market_buy(symbol=SYMBOL, quantity=quantity) \
            if side == "BUY" else \
            client.order_market_sell(symbol=SYMBOL, quantity=quantity)

        logger.info(f"Ордер виконано: {order['orderId']} | Side: {side} | Qty: {quantity}")

        # Зберігаємо угоду в стан
        trade_record = {
            "id": order["orderId"],
            "symbol": SYMBOL,
            "side": side,
            "quantity": quantity,
            "entry_price": price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "opened_at": datetime.utcnow().isoformat(),
            "status": "OPEN"
        }

        state["open_trades"].append(trade_record)
        save_trade_state(state)

        logger.info(f"Угода збережена: SL={sl_price} | TP={tp_price}")
        return trade_record

    except BinanceAPIException as e:
        logger.error(f"Binance API Error: {e.status_code} — {e.message}")
        return None
    except Exception as e:
        logger.error(f"Неочікувана помилка: {e}")
        return None


# --- Закриття позиції ---
def close_trade(trade: dict, reason: str, current_price: float) -> dict:
    try:
        client = get_client()

        # Закриваємо зворотним ордером
        if trade["side"] == "BUY":
            order = client.order_market_sell(symbol=trade["symbol"], quantity=trade["quantity"])
        else:
            order = client.order_market_buy(symbol=trade["symbol"], quantity=trade["quantity"])

        # Розраховуємо PnL
        if trade["side"] == "BUY":
            pnl = (current_price - trade["entry_price"]) * trade["quantity"]
        else:
            pnl = (trade["entry_price"] - current_price) * trade["quantity"]

        pnl = round(pnl, 4)

        # Оновлюємо стан
        state = load_trade_state()
        state["open_trades"] = [t for t in state["open_trades"] if t["id"] != trade["id"]]

        closed_record = {
            **trade,
            "exit_price": current_price,
            "closed_at": datetime.utcnow().isoformat(),
            "close_reason": reason,   # "SL_HIT", "TP_HIT", "MANUAL"
            "pnl_usdt": pnl,
            "status": "CLOSED"
        }

        state["closed_trades"].append(closed_record)
        state["total_pnl"] = round(state.get("total_pnl", 0) + pnl, 4)
        save_trade_state(state)

        logger.info(f"Угода закрита [{reason}]: PnL = {pnl} USDT")
        return closed_record

    except BinanceAPIException as e:
        logger.error(f"Binance API Error при закритті: {e.status_code} — {e.message}")
        return {}


# --- Моніторинг відкритих угод (SL/TP check) ---
def monitor_trades() -> list[dict]:
    """
    Перевіряє відкриті угоди та закриває ті, що досягли SL або TP.
    Повертає список закритих угод за цей раунд.
    """
    state = load_trade_state()
    if not state["open_trades"]:
        logger.info("Немає відкритих угод для моніторингу.")
        return []

    try:
        client = get_client()
        current_price = get_current_price(client, SYMBOL)
        closed_this_round = []

        for trade in list(state["open_trades"]):  # list() щоб не мутувати під час ітерації
            symbol = trade["symbol"]

            if trade["side"] == "BUY":
                if current_price <= trade["sl_price"]:
                    logger.info(f"SL спрацював для угоди {trade['id']}: {current_price} <= {trade['sl_price']}")
                    result = close_trade(trade, "SL_HIT", current_price)
                    closed_this_round.append(result)
                elif current_price >= trade["tp_price"]:
                    logger.info(f"TP спрацював для угоди {trade['id']}: {current_price} >= {trade['tp_price']}")
                    result = close_trade(trade, "TP_HIT", current_price)
                    closed_this_round.append(result)
                else:
                    unrealized = round((current_price - trade["entry_price"]) * trade["quantity"], 4)
                    logger.info(f"Угода {trade['id']} в силі. Ціна: {current_price} | Unrealized PnL: {unrealized} USDT")

            else:  # SELL
                if current_price >= trade["sl_price"]:
                    result = close_trade(trade, "SL_HIT", current_price)
                    closed_this_round.append(result)
                elif current_price <= trade["tp_price"]:
                    result = close_trade(trade, "TP_HIT", current_price)
                    closed_this_round.append(result)

        return closed_this_round

    except Exception as e:
        logger.error(f"Помилка моніторингу: {e}")
        return []


# --- Статус портфеля ---
def get_portfolio_status() -> dict:
    state = load_trade_state()
    client = get_client()
    current_price = get_current_price(client, SYMBOL)

    unrealized_pnl = 0.0
    for trade in state["open_trades"]:
        if trade["side"] == "BUY":
            unrealized_pnl += (current_price - trade["entry_price"]) * trade["quantity"]

    return {
        "open_trades_count": len(state["open_trades"]),
        "open_trades": state["open_trades"],
        "realized_pnl": state.get("total_pnl", 0.0),
        "unrealized_pnl": round(unrealized_pnl, 4),
        "total_trades_closed": len(state["closed_trades"]),
        "current_price": current_price
    }


# --- Точка входу для тестування ---
if __name__ == "__main__":
    print("=== Тест Execution Agent ===")
    client = get_client()
    price = get_current_price(client, SYMBOL)
    print(f"Поточна ціна {SYMBOL}: {price}")

    # Тестова угода
    print("\n--- Відкриваємо тестову BUY угоду ---")
    trade = open_trade("BUY", price)
    if trade:
        print(f"Угода відкрита: {trade}")
    else:
        print("Угоду не відкрито")
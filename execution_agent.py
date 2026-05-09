# execution_agent.py
import os
import json
import logging
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from binance.client import Client
from binance.exceptions import BinanceAPIException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Конфігурація ---
API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET")
SYMBOL = "ETHUSDT"

SPREADSHEET_ID = "1MLwbGYgqMcyfjyVhYrneiHTlpWoTZU1BkzfXh6tuKeo"

MAX_OPEN_TRADES = 2
MAX_TRADE_USDT = 15.0
STOP_LOSS_PCT = 0.015
TAKE_PROFIT_PCT = 0.03

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# --- Google Sheets клієнт ---
def get_sheet():
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.sheet1


# --- Завантажити стан з Google Sheets ---
def load_trade_state() -> dict:
    try:
        sheet = get_sheet()
        rows = sheet.get_all_records()
        open_trades = []
        closed_trades = []
        total_pnl = 0.0

        for row in rows:
            if row.get("status") == "OPEN":
                open_trades.append({
                    "id": row["order_id"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "quantity": float(row["quantity"]),
                    "entry_price": float(row["entry_price"]),
                    "sl_price": float(row.get("sl_price", 0)),
                    "tp_price": float(row.get("tp_price", 0)),
                    "opened_at": row.get("opened_at", ""),
                    "status": "OPEN"
                })
            elif row.get("status") == "CLOSED":
                pnl = float(row.get("pnl_usdt", 0))
                closed_trades.append(row)
                total_pnl += pnl

        return {
            "open_trades": open_trades,
            "closed_trades": closed_trades,
            "total_pnl": round(total_pnl, 4)
        }

    except Exception as e:
        logger.error(f"Помилка завантаження стану з Sheets: {e}")
        return {"open_trades": [], "closed_trades": [], "total_pnl": 0.0}


# --- Зберегти нову угоду в Google Sheets ---
def save_open_trade(trade: dict):
    try:
        sheet = get_sheet()
        row = [
            trade["id"],
            trade["symbol"],
            trade["side"],
            trade["quantity"],
            trade["entry_price"],
            trade.get("sl_price", ""),
            trade.get("tp_price", ""),
            trade.get("opened_at", ""),
            "",   # exit_price
            "",   # closed_at
            "",   # close_reason
            "",   # pnl_usdt
            "OPEN"
        ]
        sheet.append_row(row)
        logger.info(f"Угода збережена в Sheets: {trade['id']}")
    except Exception as e:
        logger.error(f"Помилка збереження угоди в Sheets: {e}")


# --- Закрити угоду в Google Sheets (оновити рядок) ---
def close_trade_in_sheet(order_id, exit_price: float, reason: str, pnl: float):
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()

        for i, row in enumerate(rows[1:], start=2):  # пропускаємо заголовок
            if str(row[0]) == str(order_id):
                sheet.update_cell(i, 9, exit_price)                      # exit_price
                sheet.update_cell(i, 10, datetime.utcnow().isoformat())   # closed_at
                sheet.update_cell(i, 11, reason)                          # close_reason
                sheet.update_cell(i, 12, pnl)                             # pnl_usdt
                sheet.update_cell(i, 13, "CLOSED")                        # status
                logger.info(f"Угода {order_id} закрита в Sheets: {reason} | PnL={pnl}")
                return

        logger.warning(f"Угоду {order_id} не знайдено в Sheets для закриття")
    except Exception as e:
        logger.error(f"Помилка закриття угоди в Sheets: {e}")


# --- Binance клієнт ---
def get_client() -> Client:
    client = Client(API_KEY, API_SECRET, testnet=True)
    client.API_URL = "https://testnet.binance.vision/api"
    return client


def get_current_price(client: Client, symbol: str) -> float:
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def calculate_quantity(client: Client, usdt_amount: float, symbol: str) -> float:
    price = get_current_price(client, symbol)
    raw_qty = usdt_amount / price
    info = client.get_symbol_info(symbol)
    lot_size_filter = next(f for f in info["filters"] if f["filterType"] == "LOT_SIZE")
    step_size = float(lot_size_filter["stepSize"])
    precision = len(str(step_size).rstrip("0").split(".")[-1])
    quantity = float(f"{raw_qty - (raw_qty % step_size):.{precision}f}")
    logger.info(f"Ціна: {price} | Raw qty: {raw_qty:.8f} | Округлена qty: {quantity}")
    return quantity


# --- Відкриття позиції ---
def open_trade(signal: str, price: float, atr: float = None) -> dict | None:
    state = load_trade_state()

    if len(state["open_trades"]) >= MAX_OPEN_TRADES:
        logger.warning(f"Досягнуто максимум відкритих угод ({MAX_OPEN_TRADES}). Пропускаємо.")
        return None

    for trade in state["open_trades"]:
        if trade["symbol"] == SYMBOL:
            logger.warning(f"Вже є відкрита угода по {SYMBOL}. Пропускаємо.")
            return None

    try:
        client = get_client()
        quantity = calculate_quantity(client, MAX_TRADE_USDT, SYMBOL)

        if quantity <= 0:
            logger.error("Розрахована кількість = 0.")
            return None

        if signal == "BUY":
            sl_price = round(price * (1 - STOP_LOSS_PCT), 2)
            tp_price = round(price * (1 + TAKE_PROFIT_PCT), 2)
            side = "BUY"
        else:
            sl_price = round(price * (1 + STOP_LOSS_PCT), 2)
            tp_price = round(price * (1 - TAKE_PROFIT_PCT), 2)
            side = "SELL"

        order = client.order_market_buy(symbol=SYMBOL, quantity=quantity) \
            if side == "BUY" else \
            client.order_market_sell(symbol=SYMBOL, quantity=quantity)

        logger.info(f"Ордер виконано: {order['orderId']} | Side: {side} | Qty: {quantity}")

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

        save_open_trade(trade_record)
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

        if trade["side"] == "BUY":
            order = client.order_market_sell(symbol=trade["symbol"], quantity=trade["quantity"])
            pnl = (current_price - trade["entry_price"]) * trade["quantity"]
        else:
            order = client.order_market_buy(symbol=trade["symbol"], quantity=trade["quantity"])
            pnl = (trade["entry_price"] - current_price) * trade["quantity"]

        pnl = round(pnl, 4)
        close_trade_in_sheet(trade["id"], current_price, reason, pnl)

        closed_record = {
            **trade,
            "exit_price": current_price,
            "closed_at": datetime.utcnow().isoformat(),
            "close_reason": reason,
            "pnl_usdt": pnl,
            "status": "CLOSED"
        }

        logger.info(f"Угода закрита [{reason}]: PnL = {pnl} USDT")
        return closed_record

    except BinanceAPIException as e:
        logger.error(f"Binance API Error при закритті: {e.status_code} — {e.message}")
        return {}


# --- Моніторинг SL/TP ---
def monitor_trades() -> list[dict]:
    state = load_trade_state()
    if not state["open_trades"]:
        logger.info("Немає відкритих угод для моніторингу.")
        return []

    try:
        client = get_client()
        current_price = get_current_price(client, SYMBOL)
        closed_this_round = []

        for trade in list(state["open_trades"]):
            if trade["side"] == "BUY":
                if current_price <= trade["sl_price"]:
                    result = close_trade(trade, "SL_HIT", current_price)
                    closed_this_round.append(result)
                elif current_price >= trade["tp_price"]:
                    result = close_trade(trade, "TP_HIT", current_price)
                    closed_this_round.append(result)
                else:
                    unrealized = round((current_price - trade["entry_price"]) * trade["quantity"], 4)
                    logger.info(f"Угода {trade['id']} в силі. Ціна: {current_price} | Unrealized: {unrealized} USDT")
            else:
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


# --- Тест ---
if __name__ == "__main__":
    print("=== Тест Execution Agent ===")
    client = get_client()
    price = get_current_price(client, SYMBOL)
    print(f"Поточна ціна {SYMBOL}: {price}")
    state = load_trade_state()
    print(f"Відкритих угод: {len(state['open_trades'])}")

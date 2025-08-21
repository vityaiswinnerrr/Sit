import time
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'
STOP_PERCENT = 3.7
CHECK_DELAY = 20

BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'
LOG_INTERVAL_MINUTES = 2

# === Монети ===
SYMBOLS = {
    "DOGE": {"symbol": "DOGEUSDT", "qty": 750, "active": False},
    "SOL": {"symbol": "SOLUSDT", "qty": 500, "active": False},
    "WLD": {"symbol": "WLDUSDT", "qty": 300, "active": False},
}

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

# =========================
# Telegram
# =========================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    requests.post(url, data=payload)

def help_cmd(update: Update, context: CallbackContext):
    msg = """📖 *Доступні команди:*
/help – список команд
/status – статус бота
/clear – вимкнути всі монети
/qtydoge X – змінити QTY DOGE
/qtysol X – змінити QTY SOL
/qtywld X – змінити QTY WLD
/start – вибір монет кнопками
"""
    update.message.reply_text(msg, parse_mode="Markdown")

def clear_cmd(update: Update, context: CallbackContext):
    for coin in SYMBOLS:
        SYMBOLS[coin]["active"] = False
    update.message.reply_text("❌ Всі монети вимкнено. Бот не торгує.")

def qty_cmd(update: Update, context: CallbackContext):
    try:
        cmd = update.message.text.split()[0].lower()
        val = float(update.message.text.split()[1])   # ✅ дозволяємо float
        if cmd == "/qtydoge":
            SYMBOLS["DOGE"]["qty"] = val
        elif cmd == "/qtysol":
            SYMBOLS["SOL"]["qty"] = val
        elif cmd == "/qtywld":
            SYMBOLS["WLD"]["qty"] = val
        update.message.reply_text(f"🔄 QTY оновлено: {cmd.upper()} = {val}")
    except:
        update.message.reply_text("⚠️ Використання: /qtydoge 500 або /qtysol 0.005")

def choose_coin(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton(" DOGE", callback_data="DOGE"),
         InlineKeyboardButton(" SOL", callback_data="SOL"),
         InlineKeyboardButton(" WLD", callback_data="WLD")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Вибери монети для торгівлі:", reply_markup=reply_markup)

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    coin = query.data
    SYMBOLS[coin]["active"] = not SYMBOLS[coin]["active"]
    state = "✅ Увімкнено" if SYMBOLS[coin]["active"] else "❌ Виключено"
    query.edit_message_text(text=f"{coin}: {state}")
    choose_coin(query, context)

# =========================
# Трейдинг функції
# =========================
def round_tick(v): return round(v, 6)

def get_total_balance():
    try:
        balances = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"]
        for acc in balances:
            if acc["accountType"] == "UNIFIED":
                return round(float(acc["totalEquity"]), 2)
    except:
        return None

def get_position_info(symbol):
    try:
        positions = session.get_positions(category="linear", symbol=symbol)["result"]["list"]
        if not positions: return None
        pos = positions[0]
        if float(pos["size"]) == 0: return None

        entry_price = float(pos.get("avgPrice", 0))
        mark_price = float(pos.get("markPrice", 0))
        size = float(pos["size"])
        side = pos["side"]

        pnl_usdt = (mark_price - entry_price) * size if side == "Buy" else (entry_price - mark_price) * size
        pnl_percent = (pnl_usdt / (entry_price * size)) * 100 if entry_price > 0 else 0

        return {
            "side": side,
            "size": size,
            "entry": round_tick(entry_price),
            "mark": round_tick(mark_price),
            "pnl_usdt": round(pnl_usdt, 2),
            "pnl_percent": round(pnl_percent, 2),
            "stop": pos.get("stopLoss", "—"),
        }
    except:
        return None

def close_current_position(symbol):
    try:
        positions = session.get_positions(category="linear", symbol=symbol)["result"]["list"]
        if not positions: return
        pos = positions[0]
        size = float(pos["size"])
        if size == 0: return
        side = pos["side"]
        opposite = "Sell" if side == "Buy" else "Buy"
        session.place_order(category="linear", symbol=symbol, side=opposite,
                            order_type="Market", qty=size, reduce_only=True)
        send_telegram(f"❌ Закрито {side} {symbol}")
    except Exception as e:
        send_telegram(f"‼️ Помилка закриття {symbol}: {e}")

def open_position(symbol, side, qty):
    try:
        session.place_order(category="linear", symbol=symbol, side=side,
                            order_type="Market", qty=qty, reduce_only=False)
        send_telegram(f"✅ Відкрито {side} {qty} {symbol}")
    except Exception as e:
        send_telegram(f"‼️ Помилка відкриття {symbol}: {e}")

# =========================
# Сигнали з пошти
# =========================
def check_mail():
    with IMAPClient(IMAP_SERVER, ssl=True) as client:
        client.login(EMAIL, EMAIL_PASSWORD)
        client.select_folder("INBOX")
        messages = client.search(["UNSEEN"])
        for uid in messages:
            raw = client.fetch([uid], ["BODY[]"])
            msg = pyzmail.PyzMessage.factory(raw[uid][b"BODY[]"])
            body = ""
            if msg.text_part:
                body = msg.text_part.get_payload().decode(msg.text_part.charset)
            elif msg.html_part:
                body = BeautifulSoup(msg.html_part.get_payload().decode(msg.html_part.charset), "html.parser").get_text()
            body = body.upper()
            client.add_flags(uid, "\\Seen")

            if "BUY" in body: return ("DOGE", "Buy")
            if "SELL" in body: return ("DOGE", "Sell")
            if "3" in body: return ("SOL", "Buy")
            if "4" in body: return ("SOL", "Sell")
            if "1" in body: return ("WLD", "Buy")
            if "2" in body: return ("WLD", "Sell")
    return None

# =========================
# Статус
# =========================
def make_status():
    balance = get_total_balance()
    msg = f"📊 *Статус бота*\n\n💰 Баланс: {balance} USDT\n\n"

    for coin, data in SYMBOLS.items():
        symbol = data["symbol"]
        qty = data["qty"]

        if data["active"]:
            pos = get_position_info(symbol)
            if pos:
                msg += (
                    f"⚡️*{symbol}*\n"
                    f"✅ Активний\n\n"
                    f" QTY: {qty} {symbol}\n\n"
                    f"🔰 Позиція: {pos['side']} {pos['size']} {symbol}\n"
                    f"🎯 Ціна входу: {pos['entry']}\n"
                    f"📈 Поточна: {pos['mark']}\n"
                    f"📉 Стоп-лосс: {pos['stop']}\n"
                    f"📊 PnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)\n\n"
                )
            else:
                msg += (
                    f"⚡️*{symbol}*\n"
                    f"✅ Активний\n\n"
                    f"QTY: {qty} {symbol}\n"
                    f"❌ Позицій немає\n\n"
                )
        else:
            msg += f"*{symbol}*\n❌ Виключено\n\n"

    return msg

def status_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(make_status(), parse_mode="Markdown")

# =========================
# Основний цикл
# =========================
def main_loop():
    send_telegram("🟢 Бот запущено. Очікую сигнали...")
    last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)
    while True:
        try:
            now = datetime.now()
            if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
                send_telegram(make_status())
                last_log_time = now

            sig = check_mail()
            if sig:
                coin, side = sig
                if SYMBOLS[coin]["active"]:
                    close_current_position(SYMBOLS[coin]["symbol"])
                    open_position(SYMBOLS[coin]["symbol"], side, SYMBOLS[coin]["qty"])
        except Exception as e:
            send_telegram(f"‼️ Глобальна помилка: {e}")
        time.sleep(CHECK_DELAY)

# =========================
# Telegram запуск
# =========================
updater = Updater(BOT_TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(CommandHandler("help", help_cmd))
dp.add_handler(CommandHandler("clear", clear_cmd))
dp.add_handler(CommandHandler("status", status_cmd))
dp.add_handler(CommandHandler("qtydoge", qty_cmd))
dp.add_handler(CommandHandler("qtysol", qty_cmd))
dp.add_handler(CommandHandler("qtywld", qty_cmd))
dp.add_handler(CommandHandler("start", choose_coin))
dp.add_handler(CallbackQueryHandler(button_handler))

updater.start_polling()
main_loop()

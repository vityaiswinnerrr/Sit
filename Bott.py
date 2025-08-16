import time
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CallbackQueryHandler, CommandHandler, CallbackContext

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'

BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'

STOP_PERCENT = 3.7
CHECK_DELAY = 20
LOG_INTERVAL_MINUTES = 2

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

# === Монети та їх налаштування ===
COINS = {
    "DOGEUSDT": {"qty": 750, "active": False, "signal_map": {"BUY": "Buy", "SELL": "Sell"}},
    "SOLUSDT": {"qty": 50, "active": False, "signal_map": {"3": "Buy", "4": "Sell"}},
    "WLDUSDT": {"qty": 1000, "active": False, "signal_map": {"1": "Buy", "2": "Sell"}}
}

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

# --- Telegram функції ---
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        requests.post(url, data=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("DOGE", callback_data="coin_DOGEUSDT"),
         InlineKeyboardButton("SOL", callback_data="coin_SOLUSDT"),
         InlineKeyboardButton("WLD", callback_data="coin_WLDUSDT")],
        [InlineKeyboardButton("Змінити суму", callback_data="change_qty")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Вибери монету для торгівлі або змінити суму:", reply_markup=reply_markup)

def button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    global COINS

    if query.data.startswith("coin_"):
        coin = query.data.split("_")[1]
        COINS[coin]["active"] = not COINS[coin]["active"]  # Перемикаємо стан
        status = "активна" if COINS[coin]["active"] else "неактивна"
        query.edit_message_text(text=f"{coin} тепер {status} для торгівлі\nПоточна сума: {COINS[coin]['qty']}")
    elif query.data == "change_qty":
        query.edit_message_text(text="Введи нову суму командою /setqty <монета> <кількість>")

def setqty(update: Update, context: CallbackContext):
    global COINS
    if len(context.args) != 2 or context.args[1].isdigit() == False:
        update.message.reply_text("Використання: /setqty <монета> <кількість>")
        return
    coin = context.args[0].upper()
    if coin not in COINS:
        update.message.reply_text("Монета не знайдена")
        return
    COINS[coin]["qty"] = int(context.args[1])
    update.message.reply_text(f"✅ Сума ордера для {coin} змінена на {COINS[coin]['qty']}")

# === Позиції та торгівля ===
def get_position_info(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions:
            return None
        pos = positions[0]
        size = abs(float(pos.get('size', 0)))
        if size == 0: return None
        side = pos.get('side', 'Unknown')
        entry_price = float(pos.get('entryPrice') or 0)
        mark_price = float(pos.get('markPrice') or 0)
        pnl_usdt = (mark_price - entry_price) * size if side=='Buy' else (entry_price - mark_price)*size
        pnl_percent = (pnl_usdt / (entry_price*size))*100 if entry_price*size != 0 else 0
        return {"side": side, "size": size, "entry_price": entry_price, "mark_price": mark_price,
                "pnl_usdt": round(pnl_usdt,2), "pnl_percent": round(pnl_percent,2)}
    except:
        return None

def open_position(symbol, signal):
    side = COINS[symbol]["signal_map"][signal]
    qty = COINS[symbol]["qty"]
    try:
        order = session.place_order(category='linear', symbol=symbol, side=side, order_type='Market',
                                    qty=qty, time_in_force='GoodTillCancel', reduce_only=False)
        send_telegram(f"✅ Відкрито {side} {qty} {symbol}")
    except Exception as e:
        send_telegram(f"‼️ Помилка відкриття {symbol}: {e}")

def close_current_position(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions: return
        pos = positions[0]
        side = pos['side']
        size = float(pos['size'])
        if size == 0: return
        opposite = 'Sell' if side == 'Buy' else 'Buy'
        session.place_order(category='linear', symbol=symbol, side=opposite,
                            order_type='Market', qty=size, time_in_force='GoodTillCancel', reduce_only=True)
        send_telegram(f"❌ Позицію закрито {symbol} ({side})")
    except Exception as e:
        send_telegram(f"‼️ Помилка закриття {symbol}: {e}")

def get_current_position_side(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions: return None
        pos = positions[0]
        return pos['side'] if float(pos['size'])>0 else None
    except:
        return None

# === Пошта ===
def check_mail():
    with IMAPClient(IMAP_SERVER, ssl=True) as client:
        client.login(EMAIL, EMAIL_PASSWORD)
        client.select_folder('INBOX')
        messages = client.search(['UNSEEN'])
        for uid in messages:
            raw = client.fetch([uid], ['BODY[]'])
            msg = pyzmail.PyzMessage.factory(raw[uid][b'BODY[]'])
            body = ""
            if msg.text_part:
                body = msg.text_part.get_payload().decode(msg.text_part.charset)
            elif msg.html_part:
                html = msg.html_part.get_payload().decode(msg.html_part.charset)
                body = BeautifulSoup(html,'html.parser').get_text()
            body = body.upper()[:900]
            client.add_flags(uid, '\\Seen')
            for coin, cfg in COINS.items():
                if cfg["active"]:
                    for sig in cfg["signal_map"]:
                        if sig in body:
                            return sig, coin
    return None, None

# === Основний цикл ===
def bot_loop():
    global last_log_time
    send_telegram("🟢 Бот запущено. Очікую сигнали...")
    while True:
        try:
            now = datetime.now()
            if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES*60:
                msg = "📊 Бот активний\n\n"
                for coin, cfg in COINS.items():
                    status = "🟢" if cfg["active"] else "⚪"
                    msg += f"{status} {coin}: {cfg['qty']} шт\n"
                send_telegram(msg)
                last_log_time = now

            signal, coin = check_mail()
            if signal and coin:
                current = get_current_position_side(coin)
                side = COINS[coin]["signal_map"][signal]
                if current is None:
                    open_position(coin, signal)
                elif (current=="Buy" and side=="Sell") or (current=="Sell" and side=="Buy"):
                    close_current_position(coin)
                    time.sleep(2)
                    open_position(coin, signal)
            time.sleep(CHECK_DELAY)
        except Exception as e:
            send_telegram(f"‼️ Глобальна помилка: {e}")
            time.sleep(10)

# === Telegram Updater ===
updater = Updater(BOT_TOKEN)
updater.dispatcher.add_handler(CommandHandler('start', start))
updater.dispatcher.add_handler(CommandHandler('setqty', setqty))
updater.dispatcher.add_handler(CallbackQueryHandler(button))

updater.start_polling()
bot_loop()

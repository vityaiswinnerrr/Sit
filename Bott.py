import time
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'
SYMBOL = 'DOGEUSDT'
QTY = 750
STOP_PERCENT = 3.7
CHECK_DELAY = 20

# === Telegram ===
BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'  #⚠️ Вкажи свій chat_id
LOG_INTERVAL_MINUTES = 2

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

# === Допоміжні функції ===
def round_tick(value):
    return round(value, 6)

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        requests.post(url, data=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

def get_position_info():
    try:
        positions = session.get_positions(category='linear', symbol=SYMBOL)['result']['list']
        if not positions:
            return None

        pos = positions[0]
        size = abs(float(pos.get('size', 0)))
        if size == 0:
            return None

        side = pos.get('side', 'Unknown')
        entry_price = next((float(pos[k]) for k in ['entryPrice','avgEntryPrice','avgPrice'] if pos.get(k)), 0.0)
        stop_loss = pos.get('stopLoss', '—')
        try: stop_loss = float(stop_loss)
        except: stop_loss = '—'

        mark_price = float(pos.get('markPrice', 0))
        pnl_usdt = (mark_price - entry_price) * size if side == 'Buy' else (entry_price - mark_price) * size
        pnl_percent = (pnl_usdt / (entry_price * size) * 100) if (entry_price * size) != 0 else 0

        return {
            'side': side,
            'size': size,
            'entry_price': round_tick(entry_price),
            'mark_price': round_tick(mark_price),
            'stop_loss': stop_loss,
            'pnl_usdt': round(pnl_usdt, 3),
            'pnl_percent': round(pnl_percent, 2)
        }
    except Exception as e:
        print("‼️ Помилка позиції:", e)
        return None

def get_total_balance():
    try:
        balances = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"]
        for acc in balances:
            if acc["accountType"] == "UNIFIED":
                return round(float(acc["totalEquity"]), 2)
    except Exception as e:
        print("‼️ Помилка балансу:", e)
    return None

def status_report():
    msg = "📊 *Статус бота*\n✅ Активний\n\n"
    balance = get_total_balance()
    msg += f"💰 Баланс: {balance} USDT\n\n" if balance else "💰 Баланс: ?\n\n"
    pos = get_position_info()
    if pos:
        msg += f"📌 Позиція: *{pos['side']}* {pos['size']} {SYMBOL}\n"
        msg += f"🎯 Ціна входу: {pos['entry_price']}\n"
        msg += f"📈 Поточна: {pos['mark_price']}\n"
        msg += f"📉 Стоп-лосс: {pos['stop_loss']}\n"
        msg += f"📊 PnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)\n"
    else:
        msg += "📌 Позиція: немає відкритої\n"
    send_telegram(msg)

def close_current_position():
    try:
        positions = session.get_positions(category='linear', symbol=SYMBOL)['result']['list']
        if not positions: return
        pos = positions[0]
        side = pos['side']
        size = float(pos['size'])
        if size == 0: return
        opposite = 'Sell' if side == 'Buy' else 'Buy'
        session.place_order(category='linear', symbol=SYMBOL, side=opposite, order_type='Market',
                            qty=size, time_in_force='GoodTillCancel', reduce_only=True)
        send_telegram(f"❌ Позицію закрито ({side})")
    except Exception as e:
        send_telegram(f"‼️ Помилка закриття: {e}")

def open_position(signal):
    global QTY, STOP_PERCENT
    side = 'Buy' if signal == 'BUY' else 'Sell'
    try:
        order = session.place_order(category='linear', symbol=SYMBOL, side=side, order_type='Market',
                                    qty=QTY, time_in_force='GoodTillCancel', reduce_only=False)
        order_id = order['result']['orderId']
        send_telegram(f"✅ Відкрито {side} на {QTY} {SYMBOL}")

        avg_price = None
        for _ in range(10):
            orders = session.get_order_history(category='linear', symbol=SYMBOL)['result']['list']
            for ord in orders:
                if ord['orderId'] == order_id and ord['orderStatus'] == 'Filled':
                    avg_price = float(ord.get('avgPrice', 0))
                    break
            if avg_price: break
            time.sleep(1)

        if avg_price:
            sl = round_tick(avg_price * (1 - STOP_PERCENT/100)) if side=='Buy' else round_tick(avg_price * (1 + STOP_PERCENT/100))
            session.set_trading_stop(category='linear', symbol=SYMBOL, stopLoss=sl)
            send_telegram(f"📉 Стоп-лосс встановлено на {sl}")
    except Exception as e:
        send_telegram(f"‼️ Помилка відкриття позиції: {e}")

def get_current_position_side():
    try:
        positions = session.get_positions(category='linear', symbol=SYMBOL)['result']['list']
        if not positions: return None
        pos = positions[0]
        return pos['side'] if float(pos['size'])>0 else None
    except Exception as e:
        send_telegram(f"‼️ Помилка отримання позиції: {e}")
        return None

def check_mail():
    with IMAPClient(IMAP_SERVER, ssl=True) as client:
        client.login(EMAIL, EMAIL_PASSWORD)
        client.select_folder('INBOX')
        messages = client.search(['UNSEEN'])
        for uid in messages:
            raw = client.fetch([uid], ['BODY[]'])
            msg = pyzmail.PyzMessage.factory(raw[uid][b'BODY[]'])
            body = msg.text_part.get_payload().decode(msg.text_part.charset) if msg.text_part else ''
            if not body and msg.html_part:
                soup = BeautifulSoup(msg.html_part.get_payload().decode(msg.html_part.charset), 'html.parser')
                body = soup.get_text()
            body = body.upper()[:900]
            if 'BUY' in body:
                client.add_flags(uid, '\\Seen')
                return 'BUY'
            elif 'SELL' in body:
                client.add_flags(uid, '\\Seen')
                return 'SELL'
    return None

# === Telegram меню для зміни QTY і стоп-лосс ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text("🟢 Бот активний.\nВведи /status для статусу.\nВведи /setqty <число> для зміни кількості.\nВведи /setstop <процент> для зміни стоп-лоссу.")

def status(update: Update, context: CallbackContext):
    pos = get_position_info()
    msg = f"💰 Баланс: {get_total_balance()} USDT\n"
    if pos:
        msg += f"📌 Позиція: {pos['side']} {pos['size']} {SYMBOL}\n🎯 Ціна входу: {pos['entry_price']}\n📈 Поточна: {pos['mark_price']}\n📉 Стоп-лосс: {pos['stop_loss']}\n📊 PnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)"
    else:
        msg += "📌 Позиція: немає відкритої"
    update.message.reply_text(msg)

def set_qty(update: Update, context: CallbackContext):
    global QTY
    try:
        QTY = int(context.args[0])
        update.message.reply_text(f"✅ Кількість монети встановлено на {QTY}")
    except:
        update.message.reply_text("‼️ Помилка. Використовуй /setqty <число>")

def set_stop(update: Update, context: CallbackContext):
    global STOP_PERCENT
    try:
        STOP_PERCENT = float(context.args[0])
        update.message.reply_text(f"✅ Стоп-лосс встановлено на {STOP_PERCENT}%")
    except:
        update.message.reply_text("‼️ Помилка. Використовуй /setstop <процент>")

updater = Updater(BOT_TOKEN)
dp = updater.dispatcher
dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("status", status))
dp.add_handler(CommandHandler("setqty", set_qty))
dp.add_handler(CommandHandler("setstop", set_stop))
updater.start_polling()

# === Основний цикл для перевірки сигналів пошти ===
print("🟢 Бот запущено. Очікую сигнали...")
send_telegram("🟢 Бот запущено. Очікую сигнали...")

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

while True:
    try:
        now = datetime.now()
        if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
            status_report()
            last_log_time = now

        signal = check_mail()
        if signal:
            send_telegram(f"📩 Отримано сигнал: {signal}")
            current = get_current_position_side()
            if current is None:
                open_position(signal)
            elif (current=='Buy' and signal=='SELL') or (current=='Sell' and signal=='BUY'):
                close_current_position()
                time.sleep(2)
                open_position(signal)
        time.sleep(CHECK_DELAY)
    except Exception as e:
        send_telegram(f"‼️ Глобальна помилка: {e}")
        time.sleep(10)

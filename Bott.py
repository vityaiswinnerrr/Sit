import time
import threading
from imapclient import IMAPClient
import pyzmail
from pybit.unified_trading import HTTP
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# === Налаштування Gmail ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

# === Bybit API ===
API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'

# === Торгові налаштування ===
QTY = 300
STOP_PERCENT = 2.5
CHECK_DELAY = 20  # перевірка пошти кожні 20 секунд
STATUS_DELAY = 120  # розсилка статусу кожні 2 хвилини

# === Telegram ===
BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'

# === Глобальні змінні ===
active_symbol = None  # монета для торгівлі
session = HTTP(api_key=API_KEY, api_secret=API_SECRET)

# === Допоміжні функції ===
def send_telegram(msg):
    updater.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')

def round_tick(price):
    return round(price, 8)

def get_total_balance():
    try:
        res = session.get_wallet_balance(coin='USDT')
        return float(res['result']['USDT']['wallet_balance'])
    except:
        return None

def get_position_info():
    if not active_symbol:
        return None
    try:
        positions = session.get_positions(category='linear', symbol=active_symbol)['result']['list']
        if not positions:
            return None
        pos = positions[0]
        side = pos['side']
        size = float(pos['size'])
        entry_price = float(pos['entryPrice'])
        mark_price = float(session.get_mark_price(symbol=active_symbol)['result']['mark_price'])
        sl = float(pos.get('stopLoss', 0))
        pnl = float(pos.get('unrealisedPnl', 0))
        pnl_percent = round(pnl / entry_price * 100, 2) if entry_price else 0
        return {
            'side': side,
            'size': size,
            'entry_price': entry_price,
            'mark_price': mark_price,
            'stop_loss': sl,
            'pnl_usdt': round(pnl, 4),
            'pnl_percent': pnl_percent
        }
    except:
        return None

def close_current_position():
    if not active_symbol:
        return
    try:
        positions = session.get_positions(category='linear', symbol=active_symbol)['result']['list']
        if not positions:
            return
        pos = positions[0]
        side = pos['side']
        size = float(pos['size'])
        if size == 0:
            return
        opposite = 'Sell' if side == 'Buy' else 'Buy'
        session.place_order(
            category='linear',
            symbol=active_symbol,
            side=opposite,
            order_type='Market',
            qty=size,
            time_in_force='GoodTillCancel',
            reduce_only=True
        )
        send_telegram(f"❌ Позицію закрито ({side})")
        time.sleep(2)  # затримка 2 секунди перед новою позицією
    except Exception as e:
        send_telegram(f"‼️ Помилка закриття: {e}")

def open_position(signal):
    if not active_symbol:
        return
    side = None
    if active_symbol == 'DOGEUSDT':
        if signal.upper() not in ['BUY', 'SELL']:
            return
        side = signal.capitalize()
    else:  # SOL/WLD по цифрам
        mapping = {'1': 'Buy', '2': 'Sell', '3': 'Buy', '4': 'Sell'}
        if signal not in mapping:
            return
        side = mapping[signal]

    try:
        close_current_position()  # закриття старої позиції
        order = session.place_order(
            category='linear',
            symbol=active_symbol,
            side=side,
            order_type='Market',
            qty=QTY,
            time_in_force='GoodTillCancel',
            reduce_only=False
        )
        order_id = order['result']['orderId']
        send_telegram(f"✅ Відкрито {side} на {QTY} {active_symbol}")

        avg_price = None
        for _ in range(10):
            orders = session.get_order_history(category='linear', symbol=active_symbol)['result']['list']
            for ord in orders:
                if ord['orderId'] == order_id and ord['orderStatus'] == 'Filled':
                    avg_price = float(ord.get('avgPrice', 0))
                    break
            if avg_price and avg_price > 0:
                break
            time.sleep(1)

        if avg_price:
            sl = round_tick(avg_price * (1 - STOP_PERCENT / 100)) if side == 'Buy' else round_tick(avg_price * (1 + STOP_PERCENT / 100))
            session.set_trading_stop(
                category='linear',
                symbol=active_symbol,
                stopLoss=sl
            )
            send_telegram(f"📉 Стоп-лосс встановлено на {sl}")
        else:
            send_telegram("⚠️ Не вдалося отримати avgPrice — стоп-лосс не встановлено")
    except Exception as e:
        send_telegram(f"‼️ Помилка відкриття позиції: {e}")

def status_report():
    if not active_symbol:
        return
    msg = "📊 *Статус бота*\n✅ Активний\n\n"
    balance = get_total_balance()
    msg += f"💰 Баланс: {balance} USDT\n" if balance is not None else "💰 Баланс: ?\n"
    msg += f"⚙️ QTY: {QTY} {active_symbol}\n\n"
    pos = get_position_info()
    if pos:
        msg += f"📌 Позиція: *{pos['side']}* {pos['size']} {active_symbol}\n"
        msg += f"🎯 Ціна входу: {pos['entry_price']}\n"
        msg += f"📈 Поточна: {pos['mark_price']}\n"
        msg += f"📉 Стоп-лосс: {pos['stop_loss']}\n"
        msg += f"📊 PnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)\n"
    else:
        msg += "📌 Позиція: немає відкритої\n"
    send_telegram(msg)

def check_email_loop():
    while True:
        if not active_symbol:
            time.sleep(CHECK_DELAY)
            continue
        try:
            with IMAPClient(IMAP_SERVER) as client:
                client.login(EMAIL, EMAIL_PASSWORD)
                client.select_folder('INBOX')
                messages = client.search(['UNSEEN'])
                for msgid, data in client.fetch(messages, ['BODY[]']).items():
                    email_message = pyzmail.PyzMessage.factory(data[b'BODY[]'])
                    text = ''
                    if email_message.text_part:
                        text = email_message.text_part.get_payload().decode(email_message.text_part.charset)
                    elif email_message.html_part:
                        text = email_message.html_part.get_payload().decode(email_message.html_part.charset)
                    text = text.strip()
                    if text:
                        open_position(text)
                client.logout()
        except Exception as e:
            send_telegram(f"‼️ Помилка читання пошти: {e}")
        time.sleep(CHECK_DELAY)

def status_loop():
    while True:
        if active_symbol:
            status_report()
        time.sleep(STATUS_DELAY)

# === Telegram меню ===
def start(update: Update, context: CallbackContext):
    keyboard = [
        ['SOLUSDT', 'WLDUSDT', 'DOGEUSDT'],
        ['Статус бота', 'Очистити'],
        ['QTY +50', 'QTY -50'],
        ['STOP +0.5%', 'STOP -0.5%']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("Виберіть опцію:", reply_markup=reply_markup)

def handle_message(update: Update, context: CallbackContext):
    global active_symbol, QTY, STOP_PERCENT
    text = update.message.text.strip()

    if text in ['SOLUSDT', 'WLDUSDT', 'DOGEUSDT']:
        active_symbol = text
        update.message.reply_text(f"✅ Обрана монета: {active_symbol}")
    elif text == 'Очистити':
        active_symbol = None
        update.message.reply_text("🛑 Торгівля та статус призупинені")
    elif text == 'Статус бота':
        status_report()
    elif text == 'QTY +50':
        QTY += 50
        update.message.reply_text(f"⚙️ QTY: {QTY}")
    elif text == 'QTY -50':
        QTY = max(1, QTY - 50)
        update.message.reply_text(f"⚙️ QTY: {QTY}")
    elif text == 'STOP +0.5%':
        STOP_PERCENT += 0.5
        update.message.reply_text(f"📉 STOP: {STOP_PERCENT}%")
    elif text == 'STOP -0.5%':
        STOP_PERCENT = max(0.1, STOP_PERCENT - 0.5)
        update.message.reply_text(f"📉 STOP: {STOP_PERCENT}%")

# === Запуск Telegram бота ===
updater = Updater(BOT_TOKEN)
updater.dispatcher.add_handler(CommandHandler('start', start))
updater.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

# === Запуск потоків для email та статусу ===
threading.Thread(target=check_email_loop, daemon=True).start()
threading.Thread(target=status_loop, daemon=True).start()

# === Старт бота ===
updater.start_polling()
updater.idle()

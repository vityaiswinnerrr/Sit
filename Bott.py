import time
import threading
from imapclient import IMAPClient
import pyzmail
from pybit.unified_trading import HTTP
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext
import requests

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'

BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'

CHECK_DELAY = 20  # перевірка пошти кожні 20 секунд
LOG_INTERVAL = 120  # статус у Telegram кожні 2 хвилини
DELAY_BETWEEN_CLOSE_OPEN = 2  # затримка між закриттям і новою позицією

COINS = {
    'SOLUSDT': {'qty': 3, 'stop_percent': 3},
    'WLDUSDT': {'qty': 300, 'stop_percent': 2.5},
    'DOGEUSDT': {'qty': 100, 'stop_percent': 3.7}
}

client = HTTP(api_key=API_KEY, api_secret=API_SECRET)

selected_coin = None
trading_enabled = False
last_log_time = datetime.now()

# === Функції ===
def send_telegram(message):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    requests.post(url, data=data)

def status_report():
    global last_log_time
    if not selected_coin:
        send_telegram("🚫 Бот не торгує. Монета не обрана.")
        return
    try:
        balance = client.get_wallet_balance(coin="USDT")['result']['USDT']['wallet_balance']
        positions = client.get_position_list(symbol=selected_coin)['result']
        msg = f"📊 *Статус бота*\n✅ Активний\n💰 Баланс: {balance} USDT\n"
        if positions:
            pos = positions[0]
            msg += f"📌 Позиція: {pos['side']} {pos['size']} {selected_coin}\n🎯 Ціна входу: {pos['entry_price']}\n📉 Стоп-лосс: {pos['stop_loss']}\n"
        else:
            msg += "📌 Позиція: немає\n"
        send_telegram(msg)
        last_log_time = datetime.now()
    except Exception as e:
        send_telegram(f"⚠️ Статус не отримано: {e}")

def open_position(signal):
    global selected_coin
    if not trading_enabled or not selected_coin:
        return
    try:
        current_positions = client.get_position_list(symbol=selected_coin)['result']
        if current_positions:
            current_side = current_positions[0]['side']
            if (signal == 'Buy' and current_side == 'Sell') or (signal == 'Sell' and current_side == 'Buy'):
                close_position(selected_coin)
                time.sleep(DELAY_BETWEEN_CLOSE_OPEN)
        qty = COINS[selected_coin]['qty']
        client.place_active_order(
            symbol=selected_coin,
            side=signal,
            order_type='Market',
            qty=qty,
            time_in_force='PostOnly',
            reduce_only=False
        )
        send_telegram(f"✅ Відкрито {signal} позицію на {selected_coin}, qty={qty}")
    except Exception as e:
        send_telegram(f"⚠️ Помилка відкриття позиції: {e}")

def close_position(symbol):
    try:
        positions = client.get_position_list(symbol=symbol)['result']
        if positions:
            side = positions[0]['side']
            qty = positions[0]['size']
            opposite_side = 'Sell' if side == 'Buy' else 'Buy'
            client.place_active_order(
                symbol=symbol,
                side=opposite_side,
                order_type='Market',
                qty=qty,
                time_in_force='PostOnly',
                reduce_only=True
            )
            send_telegram(f"🛑 Закрито {side} позицію на {symbol}")
    except Exception as e:
        send_telegram(f"⚠️ Помилка закриття: {e}")

def check_mail():
    global selected_coin
    if not selected_coin or not trading_enabled:
        return None
    try:
        with IMAPClient(IMAP_SERVER, ssl=True) as mail_client:
            mail_client.login(EMAIL, EMAIL_PASSWORD)
            mail_client.select_folder('INBOX')
            messages = mail_client.search(['UNSEEN'])
            for uid in messages:
                raw_message = mail_client.fetch([uid], ['BODY[]', 'FLAGS'])
                message = pyzmail.PyzMessage.factory(raw_message[uid][b'BODY[]'])
                if message.text_part:
                    body = message.text_part.get_payload().decode(message.text_part.charset)
                    if selected_coin == 'DOGEUSDT':
                        if 'BUY' in body.upper():
                            return 'Buy'
                        elif 'SELL' in body.upper():
                            return 'Sell'
                    else:
                        if '1' in body:
                            return 'Buy'
                        elif '2' in body:
                            return 'Sell'
                        elif '3' in body:
                            return 'Buy'
                        elif '4' in body:
                            return 'Sell'
    except Exception as e:
        send_telegram(f"⚠️ Помилка читання пошти: {e}")
    return None

# === Telegram кнопки ===
def start(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("SOLUSDT", callback_data='SOLUSDT')],
        [InlineKeyboardButton("WLDUSDT", callback_data='WLDUSDT')],
        [InlineKeyboardButton("DOGEUSDT", callback_data='DOGEUSDT')],
        [InlineKeyboardButton("Очистити", callback_data='CLEAR')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Виберіть монету для торгівлі:', reply_markup=reply_markup)

def button(update: Update, context: CallbackContext):
    global selected_coin, trading_enabled
    query = update.callback_query
    query.answer()
    if query.data == 'CLEAR':
        selected_coin = None
        trading_enabled = False
        query.edit_message_text(text="🚫 Торгівля зупинена.")
    else:
        selected_coin = query.data
        trading_enabled = True
        query.edit_message_text(text=f"✅ Обрана монета: {selected_coin}")

def run_telegram_bot():
    updater = Updater(BOT_TOKEN)
    updater.dispatcher.add_handler(CommandHandler('start', start))
    updater.dispatcher.add_handler(CallbackQueryHandler(button))
    updater.start_polling()
    return updater

# === Фоновий потік для торгівлі ===
def trading_loop():
    global last_log_time
    while True:
        try:
            now = datetime.now()
            if (now - last_log_time).total_seconds() >= LOG_INTERVAL:
                status_report()
            signal = check_mail()
            if signal:
                open_position(signal)
        except Exception as e:
            send_telegram(f"⚠️ Помилка фонового циклу: {e}")
        time.sleep(CHECK_DELAY)

if __name__ == '__main__':
    updater = run_telegram_bot()
    thread = threading.Thread(target=trading_loop, daemon=True)
    thread.start()
    updater.idle()

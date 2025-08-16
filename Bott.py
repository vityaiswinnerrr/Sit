import time
from imapclient import IMAPClient
import pyzmail
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'

# Початкові налаштування
SYMBOLS = ['DOGEUSDT', 'SOLUSDT', 'WLDUSDT']
current_symbol = 'DOGEUSDT'
order_qty = 750
STOP_PERCENT = {'DOGEUSDT': 3.7, 'SOLUSDT': 3.0, 'WLDUSDT': 1.0}  # приклад
CHECK_DELAY = 20

# === Telegram ===
BOT_TOKEN = 'YOUR_BOT_TOKEN'
CHAT_ID = 'YOUR_CHAT_ID'

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

# === Функції Telegram ===
def send_telegram(message, keyboard=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    if keyboard:
        payload['reply_markup'] = keyboard
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("Telegram error:", e)

def set_order_qty(new_qty):
    global order_qty
    order_qty = new_qty
    send_telegram(f"✅ Сума ордера змінена на {order_qty} {current_symbol}")

def set_symbol(new_symbol):
    global current_symbol
    current_symbol = new_symbol
    send_telegram(f"✅ Монета для торгівлі змінена на {current_symbol}")

# === Меню кнопок ===
def send_main_menu():
    keyboard = {
        "inline_keyboard": [
            [{"text": "DOGE", "callback_data": "symbol_DOGEUSDT"},
             {"text": "SOL", "callback_data": "symbol_SOLUSDT"},
             {"text": "WLD", "callback_data": "symbol_WLDUSDT"}],
            [{"text": "Сума 100", "callback_data": "qty_100"},
             {"text": "Сума 500", "callback_data": "qty_500"},
             {"text": "Сума 1000", "callback_data": "qty_1000"}],
            [{"text": "Статус бота", "callback_data": "status"}]
        ]
    }
    send_telegram("🟢 Меню управління ботом:", keyboard=keyboard)

def handle_callback(callback_data):
    if callback_data.startswith("symbol_"):
        new_sym = callback_data.split("_")[1]
        set_symbol(new_sym)
    elif callback_data.startswith("qty_"):
        new_qty = int(callback_data.split("_")[1])
        set_order_qty(new_qty)
    elif callback_data == "status":
        send_telegram(f"🟢 Поточна монета: {current_symbol}\n💰 Сума: {order_qty}")

# === Функції торгівлі ===
def open_position(signal):
    global current_symbol
    side = None
    symbol = current_symbol

    # Логіка для сигналів 1,2,3,4
    if signal == '1':
        symbol = 'WLDUSDT'
        side = 'Buy'
    elif signal == '2':
        symbol = 'WLDUSDT'
        side = 'Sell'
    elif signal == '3':
        symbol = 'SOLUSDT'
        side = 'Buy'
    elif signal == '4':
        symbol = 'SOLUSDT'
        side = 'Sell'
    else:
        # стандартний сигнал для обраної монети
        side = 'Buy' if signal.upper() == 'BUY' else 'Sell'
    
    send_telegram(f"🚀 Відкрито позицію: {side} {symbol} на {order_qty} шт.")
    # Тут виклик API для відкриття позиції через session.place_active_order(...)

def close_current_position():
    send_telegram("🛑 Поточна позиція закрита")
    # Тут виклик API для закриття позиції

# === Перевірка пошти і отримання сигналів ===
def check_mail():
    # Твої функції для перевірки пошти
    # Повертає сигнал: '1','2','3','4','BUY','SELL'
    return None  # тимчасово

# === Перевірка Telegram команд і кнопок ===
def check_telegram_commands():
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=10"
        r = requests.get(url)
        data = r.json()
        for update in data.get('result', []):
            msg = update.get('message', {})
            chat_id = msg.get('chat', {}).get('id')
            text = msg.get('text', '')
            if chat_id == int(CHAT_ID):
                if text.startswith('/menu'):
                    send_main_menu()
                elif text.startswith('/setqty'):
                    parts = text.split()
                    if len(parts) == 2 and parts[1].isdigit():
                        set_order_qty(int(parts[1]))
            callback = update.get('callback_query', {})
            if callback:
                handle_callback(callback.get('data', ''))
    except Exception as e:
        print("Telegram command error:", e)

# === Основний цикл ===
print("🟢 Бот запущено. Очікую сигнали...")
send_telegram("🟢 Бот запущено. Очікую сигнали...")
last_log_time = datetime.now() - timedelta(minutes=2)

while True:
    try:
        now = datetime.now()
        if (now - last_log_time).total_seconds() >= 120:
            send_telegram(f"🟢 Поточна монета: {current_symbol}\n💰 Сума: {order_qty}")
            last_log_time = now
        check_telegram_commands()
        signal = check_mail()
        if signal:
            open_position(signal)
        time.sleep(CHECK_DELAY)
    except Exception as e:
        print("Глобальна помилка:", e)
        send_telegram(f"‼️ Глобальна помилка: {e}")
        time.sleep(10)

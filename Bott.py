import time
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta

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
CHAT_ID = '5369718011'
LOG_INTERVAL_MINUTES = 2

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

# === Глобальні змінні ===
order_qty = QTY
last_qty_sent = None
waiting_for_qty = False  # очікуємо введення нової суми

# === Функції ===
def round_tick(value):
    return round(value, 6)

def send_telegram(message, keyboard=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        if keyboard:
            payload['reply_markup'] = keyboard
        requests.post(url, json=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

def set_order_qty(new_qty):
    global order_qty, last_qty_sent
    order_qty = new_qty
    if last_qty_sent != order_qty:
        send_telegram(f"✅ Сума ордера змінена на {order_qty} {SYMBOL}", keyboard={"remove_keyboard": True})
        last_qty_sent = order_qty

def is_number(s):
    try:
        float(s.replace(",", "."))
        return True
    except:
        return False

def show_keyboard():
    keyboard = {
        "keyboard": [["💰 Змінити суму DOGE"]],
        "one_time_keyboard": True,
        "resize_keyboard": True
    }
    send_telegram("Виберіть дію:", keyboard=keyboard)

def check_telegram_commands():
    global waiting_for_qty
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=10"
        r = requests.get(url)
        data = r.json()
        for update in data.get('result', []):
            msg = update.get('message', {})
            chat_id = msg.get('chat', {}).get('id')
            text = msg.get('text', '')

            if str(chat_id) != str(CHAT_ID):
                continue

            if waiting_for_qty:
                cleaned_text = text.strip().replace(",", ".")
                if is_number(cleaned_text):
                    set_order_qty(float(cleaned_text))
                    waiting_for_qty = False
                else:
                    send_telegram("‼️ Введи тільки число, будь ласка:")
                continue

            if text == "💰 Змінити суму DOGE":
                send_telegram("Введи нову суму ордера в DOGE:")
                waiting_for_qty = True

# --- Всі інші функції get_position_info(), get_total_balance(), status_report(), close_current_position(), open_position(), get_current_position_side(), check_mail() залишаються без змін ---

# === Основний цикл ===
print("🟢 Бот запущено. Очікую сигнали...")
send_telegram("🟢 Бот запущено. Очікую сигнали...")
show_keyboard()

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

while True:
    try:
        now = datetime.now()
        # Лог статусу
        if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
            status_report()
            last_log_time = now

        check_telegram_commands()

        signal = check_mail()
        if signal:
            print(f"\n📩 Сигнал з пошти: {signal}")
            send_telegram(f"📩 Отримано сигнал з пошти: {signal}")

            current = get_current_position_side()
            if current is None:
                open_position(signal)
            elif (current == 'Buy' and signal == 'SELL') or (current == 'Sell' and signal == 'BUY'):
                close_current_position()
                time.sleep(2)
                open_position(signal)
            else:
                print("⏸️ Позиція вже відкрита правильно")

        time.sleep(CHECK_DELAY)
    except Exception as e:
        print("‼️ Глобальна помилка:", e)
        send_telegram(f"‼️ Глобальна помилка: {e}")
        time.sleep(10)

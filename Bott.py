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
QTY = 750   # стартова кількість
STOP_PERCENT = 3.7
CHECK_DELAY = 20

# === Telegram ===
BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'
LOG_INTERVAL_MINUTES = 2

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

def round_tick(value):
    return round(value, 6)

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        requests.post(url, data=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

### NEW: функція для перевірки команд у Telegram
def check_telegram_commands():
    global QTY
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        response = requests.get(url).json()

        if "result" not in response:
            return

        for update in response["result"]:
            if "message" in update and "text" in update["message"]:
                chat_id = str(update["message"]["chat"]["id"])
                text = update["message"]["text"].strip()

                if chat_id == CHAT_ID:  # приймаємо тільки від твого чату
                    if text.startswith("/qty"):
                        try:
                            new_qty = int(text.split()[1])
                            QTY = new_qty
                            send_telegram(f"🔄 Кількість оновлено: {QTY} {SYMBOL}")
                        except:
                            send_telegram("⚠️ Використовуй команду так: /qty 1000")
    except Exception as e:
        print("‼️ Telegram command error:", e)

# ... (інші функції залишаються без змін)

# === Основний цикл ===
print("🟢 Бот запущено. Очікую сигнали...")
send_telegram("🟢 Бот запущено. Очікую сигнали...")

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

while True:
    try:
        now = datetime.now()

        # Перевірка Telegram команд
        check_telegram_commands()   ### NEW

        # Статус бота в Telegram кожні LOG_INTERVAL_MINUTES хвилин
        if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
            status_report()
            last_log_time = now

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

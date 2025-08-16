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

# === Flask сервер для кнопок ===
from flask import Flask, request
import threading

app = Flask(__name__)
user_state = {}

def round_tick(value):
    return round(value, 6)

def telegram_keyboard():
    return {
        "keyboard": [
            [{"text": f"Змінити QTY (зараз {QTY} DOGE)"}],
            [{"text": "Статус"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def send_telegram(message, keyboard=False):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown'
        }
        if keyboard:
            payload['reply_markup'] = telegram_keyboard()
        requests.post(url, json=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

# === Логіка кнопок ===
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    global QTY
    data = request.get_json()
    if not data:
        return {"ok": True}

    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id"))
    text = message.get("text", "").strip()

    if chat_id != CHAT_ID:
        return {"ok": True}

    if text.startswith("Змінити QTY"):
        user_state[chat_id] = "awaiting_qty"
        send_telegram("Введи нову кількість DOGE:")
    elif user_state.get(chat_id) == "awaiting_qty":
        try:
            new_qty = int(text)
            if new_qty > 0:
                QTY = new_qty
                user_state[chat_id] = None
                send_telegram(f"✅ Кількість DOGE оновлено: {QTY}", keyboard=True)
            else:
                send_telegram("❌ Введи число більше 0")
        except:
            send_telegram("❌ Невірний формат. Введи число.")
    elif text == "Статус":
        status_report()
    else:
        send_telegram("⚠️ Використовуй кнопки нижче", keyboard=True)

    return {"ok": True}

def run_flask():
    app.run(host="0.0.0.0", port=5000)

# === Тут залишаємо твій існуючий код (get_position_info, get_total_balance, status_report, close_current_position, open_position, get_current_position_side, check_mail) ===

# === Запуск ===
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()

    print("🟢 Бот запущено. Очікую сигнали...")
    send_telegram("🟢 Бот запущено. Очікую сигнали...", keyboard=True)

    last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

    while True:
        try:
            now = datetime.now()

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

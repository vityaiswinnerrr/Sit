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
QTY = 750  # початкова кількість
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

# --- Нове: обробка команди для зміни кількості ---
def check_telegram_commands():
    global QTY
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        r = requests.get(url)
        data = r.json()
        if not data['ok']:
            return
        for update in data.get('result', []):
            if 'message' in update and str(update['message']['chat']['id']) == CHAT_ID:
                text = update['message'].get('text', '')
                if text.startswith('/set_qty'):
                    try:
                        new_qty = float(text.split()[1])
                        QTY = new_qty
                        send_telegram(f"✅ Кількість DOGE для торгівлі оновлено на {QTY}")
                    except:
                        send_telegram("⚠️ Використання: /set_qty 500")
    except Exception as e:
        print("‼️ Telegram command error:", e)

# --- Тут йде весь твій код get_position_info(), get_total_balance(), status_report(), close_current_position(), open_position(), get_current_position_side(), check_mail() ---
# вставляємо все без змін, крім використання глобальної QTY у open_position()

def open_position(signal):
    global QTY
    side = 'Buy' if signal == 'BUY' else 'Sell'
    try:
        order = session.place_order(
            category='linear',
            symbol=SYMBOL,
            side=side,
            order_type='Market',
            qty=QTY,
            time_in_force='GoodTillCancel',
            reduce_only=False
        )
        order_id = order['result']['orderId']
        print(f"✅ Відкрито {side} на {QTY} {SYMBOL} (orderId: {order_id})")
        send_telegram(f"✅ Відкрито {side} на {QTY} {SYMBOL}")
        # далі твій код по avgPrice і стоп-лоссу
        avg_price = None
        for _ in range(10):
            orders = session.get_order_history(category='linear', symbol=SYMBOL)['result']['list']
            for ord in orders:
                if ord['orderId'] == order_id and ord['orderStatus'] == 'Filled':
                    avg_price = float(ord.get('avgPrice', 0))
                    break
            if avg_price and avg_price > 0:
                break
            print("⌛ Очікуємо avgPrice...")
            time.sleep(1)

        if avg_price:
            sl = round_tick(avg_price * (1 - STOP_PERCENT / 100)) if side == 'Buy' else round_tick(avg_price * (1 + STOP_PERCENT / 100))
            session.set_trading_stop(
                category='linear',
                symbol=SYMBOL,
                stopLoss=sl
            )
            print(f"📉 Стоп-лосс встановлено на {sl}")
            send_telegram(f"📉 Стоп-лосс встановлено на {sl}")
        else:
            print("⚠️ Не вдалося отримати avgPrice — стоп-лосс не встановлено")
            send_telegram("⚠️ Не вдалося отримати avgPrice — стоп-лосс не встановлено")

    except Exception as e:
        print("‼️ Помилка відкриття позиції:", e)
        send_telegram(f"‼️ Помилка відкриття позиції: {e}")

# === Основний цикл ===
print("🟢 Бот запущено. Очікую сигнали...")
send_telegram("🟢 Бот запущено. Очікую сигнали...")

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

while True:
    try:
        now = datetime.now()

        # Статус бота
        if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
            status_report()
            last_log_time = now

        # Перевірка команд Telegram
        check_telegram_commands()

        # Перевірка сигналів з пошти
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

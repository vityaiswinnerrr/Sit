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

def is_number(s):
    try:
        float(s.strip().replace(",", "."))
        return True
    except:
        return False

def send_telegram_with_keyboard(message, keyboard=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        if keyboard:
            payload['reply_markup'] = keyboard
        requests.post(url, json=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

def show_keyboard():
    keyboard = {
        "keyboard": [["💰 Змінити суму DOGE"]],
        "one_time_keyboard": True,
        "resize_keyboard": True
    }
    send_telegram_with_keyboard("Виберіть дію:", keyboard=keyboard)

def set_order_qty(new_qty):
    global order_qty, last_qty_sent
    order_qty = new_qty
    if last_qty_sent != order_qty:
        send_telegram(f"✅ Сума ордера змінена на {order_qty} {SYMBOL}")
        last_qty_sent = order_qty

# === Функції для Bybit ===
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
        entry_price = None
        for key in ['entryPrice', 'avgEntryPrice', 'avgPrice']:
            val = pos.get(key)
            if val not in [None, '', '0', 0]:
                try:
                    entry_price = float(val)
                    break
                except:
                    continue
        if entry_price is None:
            entry_price = 0.0
        stop_loss = pos.get('stopLoss')
        if stop_loss in [None, 0, '0', '']:
            stop_loss = '—'
        else:
            try:
                stop_loss = float(stop_loss)
            except:
                stop_loss = '—'
        mark_price = None
        try:
            mark_price = float(pos.get('markPrice', 0))
        except:
            mark_price = 0.0
        if entry_price == 0.0 or mark_price == 0.0:
            pnl_usdt = 0.0
            pnl_percent = 0.0
        else:
            pnl_usdt = (mark_price - entry_price) * size if side == 'Buy' else (entry_price - mark_price) * size
            pnl_percent = (pnl_usdt / (entry_price * size)) * 100 if (entry_price * size) != 0 else 0
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
                usdt_balance = float(acc["totalEquity"])
                return round(usdt_balance, 2)
    except Exception as e:
        print("‼️ Помилка балансу:", e)
    return None

def status_report():
    msg = "📊 *Статус бота*\n✅ Активний\n\n"
    balance = get_total_balance()
    msg += f"💰 Баланс: {balance} USDT\n\n" if balance is not None else "💰 Баланс: ?\n\n"
    pos = get_position_info()
    if pos:
        msg += f"📌 Позиція: *{pos['side']}* {pos['size']} {SYMBOL}\n"
        msg += f"🎯 Ціна входу: {pos['entry_price']}\n"
        msg += f"📈 Поточна: {pos['mark_price']}\n"
        msg += f"📉 Стоп-лосс: {pos['stop_loss']}\n"
        msg += f"📊 PnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)\n"
    else:
        msg += "📌 Позиція: немає відкритої\n"
    msg += f"\n💵 Поточна сума ордера: {order_qty} {SYMBOL}"
    send_telegram(msg)

# === Telegram команди з клавіатури ===
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

            if chat_id != int(CHAT_ID):
                continue

            if waiting_for_qty:
                cleaned_text = text.strip().replace(",", ".")
                if is_number(cleaned_text):
                    set_order_qty(float(cleaned_text))
                    waiting_for_qty = False
                else:
                    send_telegram_with_keyboard("‼️ Введи тільки число, будь ласка:")
                continue

            if text == "💰 Змінити суму DOGE":
                send_telegram_with_keyboard("Введи нову суму ордера (число):")
                waiting_for_qty = True

# === Основний цикл ===
print("🟢 Бот запущено. Очікую сигнали...")
send_telegram("🟢 Бот запущено. Очікую сигнали...")

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

while True:
    try:
        now = datetime.now()
        if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
            status_report()
            last_log_time = now

        check_telegram_commands()
        # Тут маєш вставити решту логіки відкриття/закриття позицій та обробки сигналів з пошти

        time.sleep(CHECK_DELAY)
    except Exception as e:
        print("‼️ Глобальна помилка:", e)
        send_telegram(f"‼️ Глобальна помилка: {e}")
        time.sleep(10)

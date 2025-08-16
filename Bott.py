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
SYMBOL = 'SOLUSDT'
QTY = 0.03
STOP_PERCENT = 2.5
CHECK_DELAY = 20

# === Telegram ===
BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'
LOG_INTERVAL_MINUTES = 1  # звіт кожну 1 хвилину

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

last_update_id = 0  # щоб уникнути спаму від Telegram


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
    msg = "📊 *Статус бота*\n"
    msg += "✅ Активний\n\n"

    balance = get_total_balance()
    msg += f"💰 Баланс: {balance} USDT\n" if balance is not None else "💰 Баланс: ?\n"
    msg += f"⚙️ QTY: {QTY} {SYMBOL}\n\n"

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
        if not positions:
            print("ℹ️ Немає активної позиції для закриття")
            return
        pos = positions[0]
        side = pos['side']
        size = float(pos['size'])
        if size == 0:
            print("ℹ️ Немає активної позиції")
            return
        opposite = 'Sell' if side == 'Buy' else 'Buy'
        session.place_order(
            category='linear',
            symbol=SYMBOL,
            side=opposite,
            order_type='Market',
            qty=size,
            time_in_force='GoodTillCancel',
            reduce_only=True
        )
        print("❌ Позицію закрито")
        send_telegram(f"❌ Позицію закрито ({side})")
    except Exception as e:
        print("‼️ Помилка закриття:", e)
        send_telegram(f"‼️ Помилка закриття: {e}")


def open_position(signal):
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


def get_current_position_side():
    try:
        positions = session.get_positions(category='linear', symbol=SYMBOL)['result']['list']
        if not positions:
            return None
        pos = positions[0]
        return pos['side'] if float(pos['size']) > 0 else None
    except Exception as e:
        print("‼️ Помилка отримання позиції:", e)
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
            body = ""

            if msg.text_part:
                body = msg.text_part.get_payload().decode(msg.text_part.charset)
            elif msg.html_part:
                html = msg.html_part.get_payload().decode(msg.html_part.charset)
                soup = BeautifulSoup(html, 'html.parser')
                body = soup.get_text()

            body = body.upper()[:900]

            if '1' in body:
                client.add_flags(uid, '\\Seen')
                return 'BUY'
            elif '2' in body:
                client.add_flags(uid, '\\Seen')
                return 'SELL'
    return None


# === Telegram: перевірка команд ===
def check_telegram_commands():
    global QTY, last_update_id
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id+1}"
        response = requests.get(url).json()

        if "result" not in response:
            return

        for update in response["result"]:
            last_update_id = update["update_id"]
            if "message" in update and "text" in update["message"]:
                chat_id = str(update["message"]["chat"]["id"])
                text = update["message"]["text"].strip()

                if chat_id == CHAT_ID:
                    if text.startswith("/qty"):
                        try:
                            new_qty = float(text.split()[1])
                            QTY = new_qty
                            send_telegram(f"🔄 Кількість оновлено: {QTY} {SYMBOL}")
                        except:
                            send_telegram("⚠️ Використовуй команду так: /qty 0.05")

                    elif text.startswith("/status"):
                        status_report()
    except Exception as e:
        print("‼️ Telegram command error:", e)


# === Основний цикл ===
print("🟢 Бот запущено. Очікую сигнали...")
send_telegram("🟢 Бот запущено. Очікую сигнали...")

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

while True:
    try:
        now = datetime.now()

        # перевірка команд з Telegram
        check_telegram_commands()

        # статус кожну хвилину
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

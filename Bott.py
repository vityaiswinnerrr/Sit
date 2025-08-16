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
STOP_PERCENT = 2.5
CHECK_DELAY = 20

# === Telegram ===
BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'
LOG_INTERVAL_MINUTES = 1

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)
last_update_id = 0

# === Монети та їхні QTY ===
coins = {
    'SOLUSDT': {'qty': 0.03},
    'WLDUSDT': {'qty': 1},
    'DOGEUSDT': {'qty': 0.03}  # приклад
}

active_coin = None  # поточна активна монета, None якщо /clear
bot_active = True

def round_tick(value):
    return round(value, 6)

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        requests.post(url, data=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

def get_position_info(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
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
    if not active_coin:
        send_telegram("⏸️ Бот неактивний. Виберіть монету для торгівлі.")
        return
    msg = f"📊 *Статус бота ({active_coin})*\n✅ Активний\n\n"
    balance = get_total_balance()
    msg += f"💰 Баланс: {balance} USDT\n" if balance is not None else "💰 Баланс: ?\n"
    msg += f"⚙️ QTY: {coins[active_coin]['qty']} {active_coin}\n\n"
    pos = get_position_info(active_coin)
    if pos:
        msg += f"📌 Позиція: *{pos['side']}* {pos['size']} {active_coin}\n"
        msg += f"🎯 Ціна входу: {pos['entry_price']}\n"
        msg += f"📈 Поточна: {pos['mark_price']}\n"
        msg += f"📉 Стоп-лосс: {pos['stop_loss']}\n"
        msg += f"📊 PnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)\n"
    else:
        msg += "📌 Позиція: немає відкритої\n"
    send_telegram(msg)

def close_current_position(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions:
            return
        pos = positions[0]
        size = float(pos['size'])
        if size == 0:
            return
        opposite = 'Sell' if pos['side'] == 'Buy' else 'Buy'
        session.place_order(category='linear', symbol=symbol, side=opposite,
                            order_type='Market', qty=size, time_in_force='GoodTillCancel', reduce_only=True)
        send_telegram(f"❌ Позицію {symbol} закрито ({pos['side']})")
    except Exception as e:
        send_telegram(f"‼️ Помилка закриття {symbol}: {e}")

def open_position(signal, symbol):
    side = 'Buy' if signal in ['BUY', '1'] else 'Sell'
    try:
        order = session.place_order(category='linear', symbol=symbol, side=side,
                                    order_type='Market', qty=coins[symbol]['qty'], time_in_force='GoodTillCancel', reduce_only=False)
        order_id = order['result']['orderId']
        send_telegram(f"✅ Відкрито {side} {coins[symbol]['qty']} {symbol}")
        avg_price = None
        for _ in range(10):
            orders = session.get_order_history(category='linear', symbol=symbol)['result']['list']
            for ord in orders:
                if ord['orderId'] == order_id and ord['orderStatus'] == 'Filled':
                    avg_price = float(ord.get('avgPrice', 0))
                    break
            if avg_price:
                break
            time.sleep(1)
        if avg_price:
            sl = round_tick(avg_price * (1 - STOP_PERCENT / 100)) if side == 'Buy' else round_tick(avg_price * (1 + STOP_PERCENT / 100))
            session.set_trading_stop(category='linear', symbol=symbol, stopLoss=sl)
            send_telegram(f"📉 Стоп-лосс встановлено на {sl}")
    except Exception as e:
        send_telegram(f"‼️ Помилка відкриття {symbol}: {e}")

def get_current_position_side(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions:
            return None
        pos = positions[0]
        return pos['side'] if float(pos['size']) > 0 else None
    except:
        return None

def check_mail():
    if not active_coin or not bot_active:
        return None
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
                body = BeautifulSoup(html, 'html.parser').get_text()
            body = body.upper()[:900]
            if '1' in body or 'BUY' in body:
                client.add_flags(uid, '\\Seen')
                return 'BUY'
            elif '2' in body or 'SELL' in body:
                client.add_flags(uid, '\\Seen')
                return 'SELL'
    return None

def check_telegram_commands():
    global QTY, last_update_id, active_coin, bot_active
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
                    # зміна QTY монети
                    if text.startswith("/qtysol"):
                        try:
                            coins['SOLUSDT']['qty'] = float(text.split()[1])
                            send_telegram(f"🔄 Кількість для SOLUSDT оновлено: {coins['SOLUSDT']['qty']}")
                        except:
                            send_telegram("⚠️ Використовуй команду так: /qtysol 0.03")
                    elif text.startswith("/qtywld"):
                        try:
                            coins['WLDUSDT']['qty'] = float(text.split()[1])
                            send_telegram(f"🔄 Кількість для WLDUSDT оновлено: {coins['WLDUSDT']['qty']}")
                        except:
                            send_telegram("⚠️ Використовуй команду так: /qtywld 1")
                    elif text.startswith("/qtydoge"):
                        try:
                            coins['DOGEUSDT']['qty'] = float(text.split()[1])
                            send_telegram(f"🔄 Кількість для DOGEUSDT оновлено: {coins['DOGEUSDT']['qty']}")
                        except:
                            send_telegram("⚠️ Використовуй команду так: /qtydoge 0.03")
                    # вибір активної монети
                    elif text.upper() in ['SOLUSDT', 'WLDUSDT', 'DOGEUSDT']:
                        active_coin = text.upper()
                        bot_active = True
                        send_telegram(f"✅ Активна монета: {active_coin}")
                        status_report()
                    elif text.startswith("/clear"):
                        active_coin = None
                        bot_active = False
                        send_telegram("⏸️ Бот зупинено. Монети очищені.")
                    elif text.startswith("/status"):
                        status_report()
                    elif text.startswith("/help"):
                        help_text = (
                            "📌 Доступні команди:\n"
                            "/status - показати статус активної монети\n"
                            "/qtysol <число> - змінити кількість SOLUSDT\n"
                            "/qtywld <число> - змінити кількість WLDUSDT\n"
                            "/qtydoge <число> - змінити кількість DOGEUSDT\n"
                            "SOLUSDT / WLDUSDT / DOGEUSDT - вибір активної монети\n"
                            "/clear - зупинити бота та очистити активну монету\n"
                            "/help - ця довідка"
                        )
                        send_telegram(help_text)
    except Exception as e:
        print("‼️ Telegram command error:", e)

# === Основний цикл ===
send_telegram("🟢 Бот запущено. Очікую сигналів...")

last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

while True:
    try:
        now = datetime.now()
        check_telegram_commands()
        if active_coin and bot_active:
            if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
                status_report()
                last_log_time = now
            signal = check_mail()
            if signal:
                current = get_current_position_side(active_coin)
                if current is None:
                    open_position(signal, active_coin)
                elif (current == 'Buy' and signal == 'SELL') or (current == 'Sell' and signal == 'BUY'):
                    close_current_position(active_coin)
                    time.sleep(2)
                    open_position(signal, active_coin)
        time.sleep(CHECK_DELAY)
    except Exception as e:
        send_telegram(f"‼️ Глобальна помилка: {e}")
        time.sleep(10)

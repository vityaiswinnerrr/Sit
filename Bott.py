import time
import threading
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'

# Монети та налаштування
symbols = {
    'SOLUSDT': {'qty': 300, 'stop_percent': 3.0, 'signals': {'long': 3, 'short': 4}},
    'WLDUSDT': {'qty': 300, 'stop_percent': 3.0, 'signals': {'long': 1, 'short': 2}},
    'DOGEUSDT': {'qty': 750, 'stop_percent': 3.7, 'signals': {'long': 1, 'short': 2}},
}

# Telegram
BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'

# Інші параметри
CHECK_DELAY = 20  # перевірка сигналів
LOG_INTERVAL_MINUTES = 2
status_thread = None
active_symbol = None

# === Підключення до Bybit ===
session = HTTP(endpoint="https://api.bybit.com", api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

# === Функції Telegram ===
def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e:
        print("‼️ Telegram error:", e)

# === Позиції ===
def round_tick(value, tick_size=0.0001):
    return round(round(value / tick_size) * tick_size, 8)

def get_position_info(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions or float(positions[0]['size']) == 0:
            return None
        pos = positions[0]
        mark_price = float(pos.get('markPrice', 0))
        size = float(pos['size'])
        entry_price = float(pos['entryPrice'])
        side = pos['side']
        stop_loss = float(pos['stopLoss']) if pos.get('stopLoss') else 0
        pnl_usdt = (mark_price - entry_price) * size if side == 'Buy' else (entry_price - mark_price) * size
        pnl_percent = (pnl_usdt / (entry_price * size)) * 100
        return {
            'side': side,
            'size': size,
            'entry_price': entry_price,
            'mark_price': mark_price,
            'stop_loss': stop_loss,
            'pnl_usdt': round(pnl_usdt, 4),
            'pnl_percent': round(pnl_percent, 2)
        }
    except:
        return None

def get_total_balance():
    try:
        wallet = session.get_wallet_balance(accountType="UNIFIED")['result']['list']
        for item in wallet:
            if item['accountType'] == 'UNIFIED':
                return round(float(item['totalEquity']), 2)
        return None
    except:
        return None

def status_report(symbol):
    info = symbols[symbol]
    msg = f"📊 *Статус {symbol}*\n"
    msg += "✅ Активний\n\n"
    balance = get_total_balance()
    msg += f"💰 Баланс: {balance} USDT\n" if balance else "💰 Баланс: ?\n"
    msg += f"⚙️ QTY: {info['qty']} {symbol}\n\n"
    pos = get_position_info(symbol)
    if pos:
        msg += f"📌 Позиція: *{pos['side']}* {pos['size']} {symbol}\n"
        msg += f"🎯 Ціна входу: {pos['entry_price']}\n"
        msg += f"📈 Поточна: {pos['mark_price']}\n"
        msg += f"📉 Стоп-лосс: {pos['stop_loss']}\n"
        msg += f"📊 PnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)\n"
    else:
        msg += "📌 Позиція: немає відкритої\n"
    send_telegram(msg)

def open_position(symbol, signal):
    info = symbols[symbol]
    if symbol in ['SOLUSDT', 'WLDUSDT']:
        # Використовуємо сигнали довгий/короткий відповідно до налаштувань
        if signal.isdigit():
            num_signal = int(signal)
            if num_signal == info['signals']['long']:
                action = 'BUY'
            elif num_signal == info['signals']['short']:
                action = 'SELL'
            else:
                print(f"⚠️ Сигнал {num_signal} не відповідає {symbol}")
                return
        else:
            action = 'BUY' if signal.upper() == 'BUY' else 'SELL'
    else:
        action = 'BUY' if signal.upper() == 'BUY' else 'SELL'

    side = 'Buy' if action == 'BUY' else 'Sell'
    try:
        order = session.place_order(
            category='linear',
            symbol=symbol,
            side=side,
            order_type='Market',
            qty=info['qty'],
            time_in_force='GoodTillCancel',
            reduce_only=False
        )
        order_id = order['result']['orderId']
        print(f"✅ Відкрито {side} на {info['qty']} {symbol} (orderId: {order_id})")
        send_telegram(f"✅ Відкрито {side} на {info['qty']} {symbol}")

        avg_price = None
        for _ in range(10):
            orders = session.get_order_history(category='linear', symbol=symbol)['result']['list']
            for ord in orders:
                if ord['orderId'] == order_id and ord['orderStatus'] == 'Filled':
                    avg_price = float(ord.get('avgPrice', 0))
                    break
            if avg_price and avg_price > 0:
                break
            time.sleep(1)

        if avg_price:
            sl = round_tick(avg_price * (1 - info['stop_percent']/100)) if side == 'Buy' else round_tick(avg_price * (1 + info['stop_percent']/100))
            session.set_trading_stop(category='linear', symbol=symbol, stopLoss=sl)
            send_telegram(f"📉 Стоп-лосс встановлено на {sl}")
    except Exception as e:
        send_telegram(f"‼️ Помилка відкриття позиції: {e}")

def close_current_position(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
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
            symbol=symbol,
            side=opposite,
            order_type='Market',
            qty=size,
            time_in_force='GoodTillCancel',
            reduce_only=True
        )
        send_telegram(f"❌ Позицію закрито ({side})")
    except Exception as e:
        send_telegram(f"‼️ Помилка закриття: {e}")

def get_current_position_side(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions or float(positions[0]['size']) == 0:
            return None
        return positions[0]['side']
    except:
        return None

# === Пошта ===
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
            body = body.upper().strip()[:900]
            client.add_flags(uid, '\\Seen')
            return body
    return None

# === Основний цикл для перевірки пошти ===
def mail_loop():
    while True:
        try:
            if active_symbol:
                signal_body = check_mail()
                if signal_body:
                    action = signal_body
                    send_telegram(f"📩 Отримано сигнал: {signal_body}\n🔹 Дія: {action} на {active_symbol}")
                    current = get_current_position_side(active_symbol)
                    if current is None:
                        open_position(active_symbol, action)
                    elif (current == 'Buy' and action == 'SELL') or (current == 'Sell' and action == 'BUY'):
                        close_current_position(active_symbol)
                        time.sleep(2)
                        open_position(active_symbol, action)
            time.sleep(CHECK_DELAY)
        except Exception as e:
            send_telegram(f"‼️ Помилка головного циклу: {e}")
            time.sleep(10)

# === Telegram команди ===
def set_active_symbol(symbol_name):
    global active_symbol
    active_symbol = symbol_name
    send_telegram(f"✅ Активна монета: {symbol_name}")

def cmd_sol(update: Update, context: CallbackContext):
    set_active_symbol('SOLUSDT')

def cmd_wld(update: Update, context: CallbackContext):
    set_active_symbol('WLDUSDT')

def cmd_doge(update: Update, context: CallbackContext):
    set_active_symbol('DOGEUSDT')

def cmd_clear(update: Update, context: CallbackContext):
    global active_symbol
    active_symbol = None
    send_telegram("❌ Всі розсилки статусу зупинено")

def cmd_status(update: Update, context: CallbackContext):
    if active_symbol:
        status_report(active_symbol)
    else:
        send_telegram("❌ Активна монета не обрана")

def cmd_help(update: Update, context: CallbackContext):
    text = (
        "/sol - вибрати SOLUSDT\n"
        "/wld - вибрати WLDUSDT\n"
        "/doge - вибрати DOGEUSDT\n"
        "/clear - зупинити розсилку статусу\n"
        "/status - показати статус активної монети\n"
        "/help - всі команди\n"
        "/qtysol [число] - змінити QTY для SOL\n"
        "/qtywld [число] - змінити QTY для WLD\n"
        "/qtydoge [число] - змінити QTY для DOGE"
    )
    send_telegram(text)

def cmd_qtysol(update: Update, context: CallbackContext):
    if context.args:
        symbols['SOLUSDT']['qty'] = float(context.args[0])
        send_telegram(f"✅ QTY для SOLUSDT встановлено {context.args[0]}")

def cmd_qtywld(update: Update, context: CallbackContext):
    if context.args:
        symbols['WLDUSDT']['qty'] = float(context.args[0])
        send_telegram(f"✅ QTY для WLDUSDT встановлено {context.args[0]}")

def cmd_qtydoge(update: Update, context: CallbackContext):
    if context.args:
        symbols['DOGEUSDT']['qty'] = float(context.args[0])
        send_telegram(f"✅ QTY для DOGEUSDT встановлено {context.args[0]}")

def periodic_status():
    while True:
        if active_symbol:
            status_report(active_symbol)
        time.sleep(LOG_INTERVAL_MINUTES*60)

# === Запуск Telegram та циклів ===
def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('sol', cmd_sol))
    dp.add_handler(CommandHandler('wld', cmd_wld))
    dp.add_handler(CommandHandler('doge', cmd_doge))
    dp.add_handler(CommandHandler('clear', cmd_clear))
    dp.add_handler(CommandHandler('status', cmd_status))
    dp.add_handler(CommandHandler('help', cmd_help))
    dp.add_handler(CommandHandler('qtysol', cmd_qtysol))
    dp.add_handler(CommandHandler('qtywld', cmd_qtywld))
    dp.add_handler(CommandHandler('qtydoge', cmd_qtydoge))

    threading.Thread(target=mail_loop, daemon=True).start()
    threading.Thread(target=periodic_status, daemon=True).start()

    updater.start_polling()
    print("🤖 Бот запущено")
    updater.idle()

if __name__ == "__main__":
    main()

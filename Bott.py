import time
import threading
from pybit.unified_trading import HTTP
import requests
from datetime import datetime

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
    'DOGEUSDT': {'qty': 500, 'stop_percent': 3.7, 'signals': {'long': 1, 'short': 2}},
}

# Telegram
BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'

# Інші параметри
CHECK_DELAY = 20  # перевірка сигналів
status_thread = None
active_symbol = None

# === Підключення до Bybit ===
session = HTTP(endpoint="https://api.bybit.com", api_key=API_KEY, api_secret=API_SECRET)

# === Функції Telegram ===
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})

# === Позиції ===
def get_position_info(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions or float(positions[0]['size']) == 0:
            return None
        pos = positions[0]
        mark_price = float(session.get_mark_price(symbol=symbol)['result']['markPrice'])
        size = float(pos['size'])
        entry_price = float(pos['entryPrice'])
        side = pos['side']
        stop_loss = float(pos['stopLoss']) if pos['stopLoss'] else 0
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
        wallet = session.get_wallet_balance()['result']['list']
        for item in wallet:
            if item['coin'] == 'USDT':
                return round(float(item['equity']), 2)
        return None
    except:
        return None

# === Статус бота ===
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

def round_tick(value, tick_size=0.0001):
    return round(round(value / tick_size) * tick_size, 8)

def open_position(symbol, signal):
    side = 'Buy' if signal == 'BUY' else 'Sell'
    info = symbols[symbol]
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
            print("⌛ Очікуємо avgPrice...")
            time.sleep(1)

        if avg_price:
            sl = round_tick(avg_price * (1 - info['stop_percent']/100)) if side == 'Buy' else round_tick(avg_price * (1 + info['stop_percent']/100))
            session.set_trading_stop(category='linear', symbol=symbol, stopLoss=sl)
            print(f"📉 Стоп-лосс встановлено на {sl}")
            send_telegram(f"📉 Стоп-лосс встановлено на {sl}")
        else:
            print("⚠️ Не вдалося отримати avgPrice — стоп-лосс не встановлено")
            send_telegram("⚠️ Не вдалося отримати avgPrice — стоп-лосс не встановлено")
    except Exception as e:
        print("‼️ Помилка відкриття позиції:", e)
        send_telegram(f"‼️ Помилка відкриття позиції: {e}")

def close_current_position(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
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
            symbol=symbol,
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

# === Авто-статус кожні 2 хвилини ===
def periodic_status():
    while True:
        if active_symbol:
            status_report(active_symbol)
        time.sleep(120)

# === Telegram команди ===
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

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

def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('sol', cmd_sol))
    dp.add_handler(CommandHandler('wld', cmd_wld))
    dp.add_handler(CommandHandler('doge', cmd_doge))
    dp.add_handler(CommandHandler('clear', cmd_clear))
    dp.add_handler(CommandHandler('status', cmd_status))

    # старт Telegram бота
    updater.start_polling()
    
    # старт періодичної розсилки
    threading.Thread(target=periodic_status, daemon=True).start()
    
    print("🤖 Бот запущено")
    updater.idle()

if __name__ == "__main__":
    main()

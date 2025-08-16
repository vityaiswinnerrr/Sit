import time
import threading
from pybit.unified_trading import HTTP
import requests
from datetime import datetime
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'

symbols = {
    'SOLUSDT': {'qty': 300, 'stop_percent': 3.0},
    'WLDUSDT': {'qty': 300, 'stop_percent': 3.0},
    'DOGEUSDT': {'qty': 500, 'stop_percent': 3.7},
}

BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'
CHECK_DELAY = 20
active_symbol = None

session = HTTP(api_key=API_KEY, api_secret=API_SECRET)

# === Telegram клавіатура ===
keyboard = ReplyKeyboardMarkup([
    ['SOLUSDT', 'WLDUSDT', 'DOGEUSDT'],
    ['Очистити']
], resize_keyboard=True)

# === Функції ===
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})

def round_tick(value, tick_size=0.0001):
    return round(round(value / tick_size) * tick_size, 8)

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
        if not positions or float(positions[0]['size']) == 0:
            return
        pos = positions[0]
        side = pos['side']
        size = float(pos['size'])
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

def check_mail(symbol):
    try:
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
                client.add_flags(uid, '\\Seen')
                if '1' in body:
                    return 'BUY'
                elif '2' in body:
                    return 'SELL'
    except Exception as e:
        send_telegram(f"‼️ Помилка читання пошти: {e}")
    return None

def periodic_status():
    while True:
        if active_symbol:
            status_report(active_symbol)
            signal = check_mail(active_symbol)
            if signal:
                pos = get_position_info(active_symbol)
                current_side = pos['side'] if pos else None
                if not current_side:
                    open_position(active_symbol, signal)
                elif (current_side == 'Buy' and signal == 'SELL') or (current_side == 'Sell' and signal == 'BUY'):
                    close_current_position(active_symbol)
                    time.sleep(2)
                    open_position(active_symbol, signal)
        time.sleep(CHECK_DELAY)

# === Telegram обробка кнопок ===
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_symbol
    text = update.message.text
    if text in symbols:
        active_symbol = text
        await update.message.reply_text(f"✅ Активна монета: {text}", reply_markup=keyboard)
    elif text == 'Очистити':
        active_symbol = None
        await update.message.reply_text("❌ Всі розсилки статусу зупинено", reply_markup=keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Виберіть монету для торгівлі:", reply_markup=keyboard)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button))

    threading.Thread(target=periodic_status, daemon=True).start()

    print("🤖 Бот запущено")
    app.run_polling()

if __name__ == "__main__":
    main()

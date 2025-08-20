import time
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler
)
import asyncio

# === Налаштування ===
EMAIL = 'tradebotv1@gmail.com'
EMAIL_PASSWORD = 'xotv aadd sqnx ggmp'
IMAP_SERVER = 'imap.gmail.com'

API_KEY = 'm4qlJh0Vec5PzYjHiC'
API_SECRET = 'bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54'

BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'
LOG_INTERVAL_MINUTES = 2
CHECK_DELAY = 20
STOP_PERCENT = {
    "DOGEUSDT": 3.7,
    "SOLUSDT": 3.0,
    "WLDUSDT": 3.0
}

# === Глобальні змінні ===
active_symbols = set()
qty_map = {
    "DOGEUSDT": 750,
    "SOLUSDT": 300,
    "WLDUSDT": 300
}
session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)

# === Допоміжні ===
def round_tick(value): 
    return round(value, 6)

async def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        await asyncio.to_thread(requests.post, url, data=payload)
    except Exception as e:
        print("‼️ Telegram error:", e)

def get_position_info(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions: return None
        pos = positions[0]
        size = abs(float(pos.get('size', 0)))
        if size == 0: return None
        side = pos.get('side', 'Unknown')
        entry_price = float(pos.get('avgPrice', 0) or 0)
        mark_price = float(pos.get('markPrice', 0) or 0)
        pnl_usdt = (mark_price - entry_price) * size if side == 'Buy' else (entry_price - mark_price) * size
        pnl_percent = (pnl_usdt / (entry_price * size)) * 100 if entry_price * size > 0 else 0
        return {
            'side': side,
            'size': size,
            'entry_price': round_tick(entry_price),
            'mark_price': round_tick(mark_price),
            'pnl_usdt': round(pnl_usdt, 3),
            'pnl_percent': round(pnl_percent, 2)
        }
    except:
        return None

def get_total_balance():
    try:
        balances = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"]
        for acc in balances:
            if acc["accountType"] == "UNIFIED":
                return round(float(acc["totalEquity"]), 2)
    except:
        return None

async def open_position(symbol, side):
    try:
        qty = qty_map[symbol]
        order = session.place_order(
            category='linear',
            symbol=symbol,
            side=side,
            order_type='Market',
            qty=qty,
            time_in_force='GoodTillCancel'
        )
        await send_telegram(f"✅ Відкрито {side} на {qty} {symbol}")
        avg_price = float(order['result'].get('avgPrice', 0) or 0)
        if avg_price:
            sl = round_tick(avg_price * (1 - STOP_PERCENT[symbol] / 100)) if side == 'Buy' else round_tick(avg_price * (1 + STOP_PERCENT[symbol] / 100))
            session.set_trading_stop(category='linear', symbol=symbol, stopLoss=sl)
            await send_telegram(f"📉 Стоп-лосс {symbol}: {sl}")
    except Exception as e:
        await send_telegram(f"‼️ Помилка відкриття {symbol}: {e}")

async def close_position(symbol):
    try:
        positions = session.get_positions(category='linear', symbol=symbol)['result']['list']
        if not positions: return
        pos = positions[0]
        side = pos['side']
        size = float(pos['size'])
        if size == 0: return
        opposite = 'Sell' if side == 'Buy' else 'Buy'
        session.place_order(category='linear', symbol=symbol, side=opposite,
                            order_type='Market', qty=size, reduce_only=True)
        await send_telegram(f"❌ Закрито {symbol} ({side})")
    except Exception as e:
        await send_telegram(f"‼️ Помилка закриття {symbol}: {e}")

async def status_report():
    msg = "📊 *Статус бота*\n"
    balance = get_total_balance()
    msg += f"💰 Баланс: {balance} USDT\n\n"
    if not active_symbols:
        msg += "⛔ Бот виключений (монети не вибрані)\n"
    for sym in active_symbols:
        pos = get_position_info(sym)
        if pos:
            msg += f"📌 {sym}: {pos['side']} {pos['size']} @ {pos['entry_price']} → {pos['mark_price']}\nPnL: {pos['pnl_usdt']} USDT ({pos['pnl_percent']}%)\n\n"
        else:
            msg += f"📌 {sym}: немає відкритої позиції\n\n"
    await send_telegram(msg)

# === Пошта (сигнали) ===
def check_mail():
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
                    body = BeautifulSoup(msg.html_part.get_payload().decode(msg.html_part.charset), 'html.parser').get_text()
                body = body.upper()[:900]
                client.add_flags(uid, '\\Seen')
                if 'BUY' in body: return ("DOGEUSDT", "Buy")
                if 'SELL' in body: return ("DOGEUSDT", "Sell")
                if '1' in body: return ("WLDUSDT", "Buy")
                if '2' in body: return ("WLDUSDT", "Sell")
                if '3' in body: return ("SOLUSDT", "Buy")
                if '4' in body: return ("SOLUSDT", "Sell")
    except Exception as e:
        print("‼️ Mail check error:", e)
    return None

# === Telegram меню ===
def main_menu():
    keyboard = [
        [InlineKeyboardButton("🐕 DOGE", callback_data="DOGEUSDT"),
         InlineKeyboardButton("🌞 SOL", callback_data="SOLUSDT"),
         InlineKeyboardButton("🌐 WLD", callback_data="WLDUSDT")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help"),
         InlineKeyboardButton("📊 Status", callback_data="status"),
         InlineKeyboardButton("🧹 Clear", callback_data="clear")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Меню бота:", reply_markup=main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ["DOGEUSDT", "SOLUSDT", "WLDUSDT"]:
        if data in active_symbols:
            active_symbols.remove(data)
            await query.edit_message_text(f"❌ {data} виключено", reply_markup=main_menu())
        else:
            active_symbols.add(data)
            await query.edit_message_text(f"✅ {data} включено", reply_markup=main_menu())
    elif data == "help":
        await query.edit_message_text(
            "📖 Команди:\n"
            "DOGE / SOL / WLD – вибір монет\n"
            "/qtydoge 500 – задати QTY DOGE\n"
            "/qtysol 400 – задати QTY SOL\n"
            "/qtywld 350 – задати QTY WLD\n",
            reply_markup=main_menu()
        )
    elif data == "status":
        await status_report()
        await query.edit_message_text("📊 Статус відправлено у бот.", reply_markup=main_menu())
    elif data == "clear":
        active_symbols.clear()
        await query.edit_message_text("🧹 Всі монети очищено.", reply_markup=main_menu())

# === Основний цикл ===
last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)
async def main_loop():
    global last_log_time
    while True:
        try:
            now = datetime.now()
            if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
                if active_symbols:
                    await status_report()
                last_log_time = now

            signal = check_mail()
            if signal and signal[0] in active_symbols:
                symbol, side = signal
                await send_telegram(f"📩 Сигнал: {symbol} {side}")
                await open_position(symbol, side)

            await asyncio.sleep(CHECK_DELAY)
        except Exception as e:
            await send_telegram(f"‼️ Глобальна помилка: {e}")
            await asyncio.sleep(10)

# === Запуск ===
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))

async def run():
    await asyncio.gather(app.run_polling(), main_loop())

print("🟢 Бот запущено. Очікую сигнали...")
asyncio.run(run())

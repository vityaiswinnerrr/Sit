import time
from imapclient import IMAPClient
import pyzmail
from bs4 import BeautifulSoup
from pybit.unified_trading import HTTP
import requests
from datetime import datetime, timedelta
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters

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

BOT_TOKEN = '7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k'
CHAT_ID = '5369718011'
LOG_INTERVAL_MINUTES = 2

session = HTTP(api_key=API_KEY, api_secret=API_SECRET, recv_window=10000)
bot = Bot(BOT_TOKEN)

# === Глобальна змінна для суми ордера ===
order_qty = QTY

# === Telegram функції ===
def send_telegram(message):
    try:
        bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
    except Exception as e:
        print("‼️ Telegram error:", e)

def set_order_qty(new_qty):
    global order_qty
    if new_qty <= 0:
        send_telegram("❌ Сума не може бути <= 0")
        return
    if new_qty != order_qty:  # Відправляємо повідомлення тільки якщо змінилася сума
        order_qty = new_qty
        send_telegram(f"✅ Сума ордера змінена на {order_qty} {SYMBOL}")

# === Кнопки для зміни суми ===
def qty_buttons():
    keyboard = [
        [InlineKeyboardButton("Змінити суму", callback_data="change_qty")]
    ]
    return InlineKeyboardMarkup(keyboard)

def show_qty_buttons(update: Update, context: CallbackContext):
    update.message.reply_text(
        f"💵 Поточна сума ордера: {order_qty} {SYMBOL}\nНатисніть кнопку, щоб змінити суму:",
        reply_markup=qty_buttons()
    )

def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    if query.data == "change_qty":
        query.message.reply_text("Введіть нову кількість DOGE:")
        context.user_data['awaiting_qty'] = True

def handle_qty_message(update: Update, context: CallbackContext):
    if context.user_data.get('awaiting_qty'):
        try:
            new_qty = float(update.message.text)
            set_order_qty(new_qty)
            update.message.reply_text(f"✅ Сума ордера встановлена: {order_qty} {SYMBOL}", reply_markup=qty_buttons())
        except:
            update.message.reply_text("❌ Некоректне число. Спробуйте ще раз:")
        finally:
            context.user_data['awaiting_qty'] = False

# === Статус ===
def status_report():
    msg = "📊 *Статус бота*\n✅ Активний\n\n"
    try:
        balances = session.get_wallet_balance(accountType="UNIFIED")["result"]["list"]
        usdt_balance = round(float(balances[0]["totalEquity"]), 2) if balances else 0
        msg += f"💰 Баланс: {usdt_balance} USDT\n\n"
    except:
        msg += "💰 Баланс: ?\n\n"

    try:
        positions = session.get_positions(category='linear', symbol=SYMBOL)['result']['list']
        if positions:
            pos = positions[0]
            side = pos.get('side', 'Unknown')
            size = abs(float(pos.get('size', 0)))
            entry_price = float(pos.get('entryPrice', 0))
            mark_price = float(pos.get('markPrice', 0))
            pnl_usdt = (mark_price - entry_price) * size if side == 'Buy' else (entry_price - mark_price) * size
            pnl_percent = (pnl_usdt / (entry_price * size)) * 100 if entry_price*size !=0 else 0
            stop_loss = pos.get('stopLoss', '—')
            msg += f"📌 Позиція: *{side}* {size} {SYMBOL}\n"
            msg += f"🎯 Ціна входу: {entry_price}\n"
            msg += f"📈 Поточна: {mark_price}\n"
            msg += f"📉 Стоп-лосс: {stop_loss}\n"
            msg += f"📊 PnL: {round(pnl_usdt,3)} USDT ({round(pnl_percent,2)}%)\n"
        else:
            msg += "📌 Позиція: немає відкритої\n"
    except:
        msg += "📌 Позиція: ?\n"

    msg += f"\n💵 Поточна сума ордера: {order_qty} {SYMBOL}"
    send_telegram(msg)

# === Основний Telegram бот ===
def run_telegram_bot():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("qty", show_qty_buttons))
    dp.add_handler(CallbackQueryHandler(button_callback))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_qty_message))
    updater.start_polling()
    updater.idle()

# === Основний цикл ===
if __name__ == '__main__':
    from threading import Thread
    Thread(target=run_telegram_bot).start()  # Telegram в окремому потоці

    print("🟢 Бот запущено. Очікую сигнали...")
    send_telegram("🟢 Бот запущено. Очікую сигнали...")

    last_log_time = datetime.now() - timedelta(minutes=LOG_INTERVAL_MINUTES)

    while True:
        try:
            now = datetime.now()
            # Лог статусу
            if (now - last_log_time).total_seconds() >= LOG_INTERVAL_MINUTES * 60:
                status_report()
                last_log_time = now

            # Тут можна вставити check_mail() і відкриття/закриття позицій
            # signal = check_mail()
            # if signal:
            #     ...

            time.sleep(CHECK_DELAY)
        except Exception as e:
            print("‼️ Глобальна помилка:", e)
            send_telegram(f"‼️ Глобальна помилка: {e}")
            time.sleep(10)

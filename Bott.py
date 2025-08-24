#!/usr/bin/env python3
# bot_pro.py — 1m Smart-Money Bot (SMC + MTF + Risk + Anti-spam) — Bybit live with TP/SL/BE/size

import time
import math
import os
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from collections import deque
from telegram import Bot

from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volume import OnBalanceVolumeIndicator
from ta.volatility import AverageTrueRange
import re

# === Екранування спецсимволів для MarkdownV2 ===
def escape_md(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+\\-=|{}.!])', r'\\\1', text)

# === Функція відправки повідомлення ===
def send_msg(bot: Bot, chat_id: str, text: str):
    safe_text = escape_md(text)   # екрануємо весь текст
    try:
        bot.send_message(chat_id=chat_id, text=safe_text, parse_mode="MarkdownV2")
    except Exception as e:
        print(f"[TG ERROR] {e}")
        # fallback — відправити без форматування
        bot.send_message(chat_id=chat_id, text=text)

# =================== ПАРАМЕТРИ ===================

SYMBOLS = ["DOGE/USDT", "ARB/USDT", "SOL/USDT", "ETH/USDT", "WLD/USDT", "SUI/USDT"]
BENCH_FOR_SMT = {
    "DOGE/USDT":"BTC/USDT",
    "ARB/USDT":"BTC/USDT",
    "SOL/USDT":"BTC/USDT",
    "ETH/USDT":"BTC/USDT",
    "WLD/USDT":"BTC/USDT",
    "SUI/USDT":"BTC/USDT"
}  # бенчмарк для SMT

TIMEFRAME = "1m"
HTF_TIMEFRAME = "5m"    # тренд-фільтр
EMA_FAST = 50
EMA_SLOW = 200

# Фічі (ON/OFF)
FEAT_OB_ORDERBLOCK   = True
FEAT_BOS_CHOCH       = True
FEAT_SWEEP           = True
FEAT_FVG_BPR         = True
FEAT_SMT             = True
FEAT_HTF_LEVELS      = True
FEAT_PREMIUM_DISCOUNT= True
FEAT_CLASSIC_PATTERNS= True
FEAT_OBV_CVD_DELTA   = True
FEAT_VOL_IMBAL       = True
FEAT_MTF_CONFIRM     = True
FEAT_SESSIONS        = True
FEAT_CORREL_FILTER   = True
FEAT_TRAILING_SWING  = True
FEAT_DAILY_RISK_GUARD= True

# Антиспам / скоринг
ORDERBOOK_LEVELS = 20
CONFIRMATIONS_REQUIRED = 2
MIN_SCORE = 3.2
SCORE_MARGIN = 0.7

# Флет/вола
FLAT_THRESHOLD = 0.0006
ATR_MIN_REL = 0.0008
ATR_MAX_REL = 0.02

# TP/SL / трейл
TP1_ATR = 0.6
TP2_ATR = 1.2
TP3_ATR = 2.0
SL_ATR  = 0.8
MIN_RR  = 1.25

# Кулдауни
COOLDOWN_SEC = 150
COOLDOWN_AFTER_SL_SEC = 420
ONE_SIGNAL_PER_BAR = True

# Кореляції
ROLL_CORR_WINDOW = 60      # 60 хвилин 1m (~1 год)
CORR_BLOCK_THR   = 0.80    # не брати однонапрямні угоди з сильно корельованими активами

# Сесії (UTC)
SESSIONS_UTC = [
    (7, 11),   # Лондон open
    (12, 16),  # Перекриття Лондон/НЙ
    (18, 20),  # НЙ актив
]

# Денний ризик
DAILY_MAX_LOSS = -0.03   # -3% від "умовного" капіталу
DAILY_MAX_WIN  =  0.06   # +6% — далі пауза
ACCOUNT_EQUITY = 1.0     # умовний 1.0 (PnL рахуємо від нього)

# Розмір позиції в живій торгівлі
SIZE_PCT = 0.15  # 5% від вільного USDT
TRADE_LIVE = True  # вмикай False для dry-run

# Telegram (⚠️ заміни токен на новий!)
TG_TOKEN = "7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k"
TG_CHAT_ID = "5369718011"

# =================== ІНІТ ===================

# Ключі Bybit з env:
BYBIT_KEY = os.getenv("BYBIT_KEY", "m4qlJh0Vec5PzYjHiC")
BYBIT_SECRET = os.getenv("BYBIT_SECRET", "bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54")

# Bybit USDT-перпи
exchange = ccxt.bybit({
    "apiKey": BYBIT_KEY,
    "secret": BYBIT_SECRET,
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",      # derivatives
        "defaultSettle": "USDT",    # USDT-settled
    },
})
# Для тестнету розкоментуй:
# exchange.set_sandbox_mode(True)

tg = Bot(TG_TOKEN)

def send(msg):
    try:
        tg.send_message(chat_id=TG_CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        print("[TG ERROR]", e)

def now_utc():
    return datetime.now(timezone.utc)

# =================== УТИЛІТИ МАРКЕТУ/ОРДЕРІВ ===================

def mkt(symbol_spot_like: str) -> str:
    """DOGE/USDT -> DOGE/USDT:USDT (перп Bybit)."""
    if ":USDT" in symbol_spot_like:
        return symbol_spot_like
    base, quote = symbol_spot_like.split("/")
    return f"{base}/{quote}:USDT"

def free_usdt():
    try:
        bal = exchange.fetch_balance(params={"type": "swap"})
        return float(bal.get("USDT", {}).get("free", 0.0) or bal.get("free", {}).get("USDT", 0.0) or 0.0)
    except Exception as e:
        print("[BALANCE ERROR]", e)
        return 0.0

def clamp_amount(symbol, amount):
    try:
        market = exchange.market(mkt(symbol))
        amount = float(exchange.amount_to_precision(mkt(symbol), amount))
        min_amt = market.get("limits", {}).get("amount", {}).get("min", None)
        if min_amt:
            amount = max(amount, float(min_amt))
        return amount
    except Exception:
        return amount

def place_entry_with_tpsl(symbol, side, entry, tp1, tp2, tp3, sl):
    """
    1) Ринковий вхід на 5% від вільного USDT
    2) Часткові TP1/TP2 (reduceOnly, market on trigger)
    3) Загальний SL (reduceOnly, market on trigger)
    4) TP3 на решту
    """
    quote_to_spend = free_usdt() * SIZE_PCT
    if quote_to_spend <= 0:
        print("[ORDER] No free USDT.")
        return None

    amt = quote_to_spend / max(1e-9, entry)
    amt = clamp_amount(symbol, amt)
    if amt <= 0:
        print("[ORDER] Amount too small.")
        return None

    sym = mkt(symbol)
    entry_side = "buy" if side == "LONG" else "sell"
    exit_side  = "sell" if side == "LONG" else "buy"

    try:
        # 1) Вхід
        entry_order = exchange.create_order(sym, "market", entry_side, amt, None, {})

        # 2) TP1, TP2 — reduceOnly, market on trigger
        amt_tp1 = clamp_amount(symbol, amt * 0.33)
        amt_tp2 = clamp_amount(symbol, amt * 0.33)

        if amt_tp1 > 0:
            exchange.create_order(
                sym, "market", exit_side, amt_tp1, None,
                {
                    "reduceOnly": True,
                    "takeProfitPrice": float(tp1),
                }
            )
        if amt_tp2 > 0:
            exchange.create_order(
                sym, "market", exit_side, amt_tp2, None,
                {
                    "reduceOnly": True,
                    "takeProfitPrice": float(tp2),
                }
            )

        # 3) SL — reduceOnly, market on trigger (на повну к-сть)
        exchange.create_order(
            sym, "market", exit_side, amt, None,
            {
                "reduceOnly": True,
                "stopLossPrice": float(sl),
            }
        )

        # 4) TP3 — reduceOnly на решту
        amt_rest = clamp_amount(symbol, max(0.0, amt - amt_tp1 - amt_tp2))
        if amt_rest > 0:
            exchange.create_order(
                sym, "market", exit_side, amt_rest, None,
                {
                    "reduceOnly": True,
                    "takeProfitPrice": float(tp3),
                }
            )

        return entry_order

    except Exception as e:
        print("[ORDER ERROR]", e)
        return None

def move_sl_to_be(symbol, side, be_price):
    """
    Перенос SL у BE: ставимо новий reduceOnly stop-ордер (market on trigger) на ціну входу.
    """
    sym = mkt(symbol)
    exit_side = "sell" if side == "LONG" else "buy"
    try:
        exchange.create_order(
            sym, "market", exit_side, 1e8, None,  # велика к-сть: біржа скоригує під розмір позиції
            {
                "reduceOnly": True,
                "stopLossPrice": float(be_price),
            }
        )
    except Exception as e:
        print("[BE SL ERROR]", e)

# =================== УТИЛІТИ ДАНИХ ===================

def get_ohlcv(symbol, timeframe="1m", limit=300):
    try:
        data = exchange.fetch_ohlcv(mkt(symbol), timeframe=timeframe, limit=limit)
        df = pd.DataFrame(data, columns=["ts","open","high","low","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df
    except Exception as e:
        print(f"[ERROR] OHLCV {symbol}: {e}")
        return None

def get_trades_delta(symbol, limit=200):
    """Псевдо-дельта/СVD з публічних трейдів (груба оцінка buy/sell через mid)."""
    try:
        trades = exchange.fetch_trades(mkt(symbol), limit=limit)
    except Exception:
        return 0.0, 0.0  # delta, cvd change

    if not trades:
        return 0.0, 0.0

    try:
        ob = exchange.fetch_order_book(mkt(symbol), limit=5)
        mid = (ob["bids"][0][0] + ob["asks"][0][0]) / 2.0
    except Exception:
        mid = trades[-1]["price"]

    delta = 0.0
    for t in trades:
        side_est = 1 if t["price"] >= mid else -1
        delta += side_est * t["amount"]

    # СVD проста інкрементаальна апроксимація — повертаємо тільки зміни
    return float(delta), float(delta)

def get_orderbook_bias(symbol):
    try:
        ob = exchange.fetch_order_book(mkt(symbol), limit=ORDERBOOK_LEVELS)
        bid_vol = sum(v for p, v in ob["bids"])
        ask_vol = sum(v for p, v in ob["asks"])
        imb = (bid_vol - ask_vol) / max(1e-9, (bid_vol + ask_vol))
        if bid_vol > ask_vol * 1.1:
            return "LONG", 1.4, imb
        if ask_vol > bid_vol * 1.1:
            return "SHORT", 1.4, imb
        return None, 0.2, imb  # слабкий сигнал
    except Exception:
        return None, 0.0, 0.0

# =================== SMC БЛОКИ ===================

def find_fvg(df):
    if len(df) < 5:
        return None, None
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if c["low"] > a["high"]:
        return ("BULL", (a["high"], c["low"])), "📐 Bullish FVG"
    if c["high"] < a["low"]:
        return ("BEAR", (c["high"], a["low"])), "📐 Bearish FVG"
    return None, None

def find_bpr(df):
    if len(df) < 6:
        return None, None
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if (c["close"] > b["open"]) and (b["low"] < a["low"]) and (c["low"] > a["low"]):
        lo = min(b["low"], a["low"]); hi = c["low"]
        return ("BULL", (lo, hi)), "🟩 BPR (bullish)"
    if (c["close"] < b["open"]) and (b["high"] > a["high"]) and (c["high"] < a["high"]):
        lo = c["high"]; hi = max(b["high"], a["high"])
        return ("BEAR", (lo, hi)), "🟥 BPR (bearish)"
    return None, None

def detect_bos_choch(df):
    if len(df) < 10:
        return None
    highs = df["high"].iloc[-6:-1].max()
    lows  = df["low"].iloc[-6:-1].min()
    last_close = df["close"].iloc[-1]
    if last_close > highs:
        return "BOS_UP"
    if last_close < lows:
        return "BOS_DOWN"
    return None

def detect_sweep(df):
    if len(df) < 10:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-6:-1]
    if last["high"] > prev["high"].max() and last["volume"] > prev["volume"].mean()*1.5:
        return "SWEEP_UP"
    if last["low"] < prev["low"].min() and last["volume"] > prev["volume"].mean()*1.5:
        return "SWEEP_DOWN"
    return None

def order_block_hint(df):
    recent = df.iloc[-6:]
    vol_thr = recent["volume"].mean()*1.6
    bull = any((recent["volume"] > vol_thr) & (recent["close"] > recent["open"]))
    bear = any((recent["volume"] > vol_thr) & (recent["close"] < recent["open"]))
    return bull, bear

def premium_discount_zone(df, lookback=50):
    if len(df) < lookback:
        return None
    seg = df.iloc[-lookback:]
    hi = seg["high"].max()
    lo = seg["low"].min()
    mid = (hi + lo) / 2.0  # Fibo 0.5 як базова лінія
    return lo, mid, hi

def htf_levels(symbol):
    """Daily/Weekly High-Low (закриті бари)."""
    d = get_ohlcv(symbol, "1d", 10)
    w = get_ohlcv(symbol, "1w", 10)
    if d is None or w is None or len(d) < 2 or len(w) < 2:
        return None
    d_prev = d.iloc[-2]   # вчорашній
    w_prev = w.iloc[-2]   # минулий тиждень
    return {
        "daily_high": float(d_prev["high"]),
        "daily_low":  float(d_prev["low"]),
        "weekly_high":float(w_prev["high"]),
        "weekly_low": float(w_prev["low"]),
    }

def smt_div_pair(sym_close, bench_close):
    """Проста SMT: актив робить lower low, бенч — ні (bull), і навпаки."""
    if len(sym_close) < 10 or len(bench_close) < 10:
        return None
    s = sym_close.iloc[-5:]
    b = bench_close.iloc[-5:]
    bull = (s.min() < s.iloc[0]*0.999) and (b.min() >= b.iloc[0]*0.999)
    bear = (s.max() > s.iloc[0]*1.001) and (b.max() <= b.iloc[0]*1.001)
    if bull: return "SMT_BULL"
    if bear: return "SMT_BEAR"
    return None

# =================== ПАТЕРНИ ===================

def double_bottom(df, lookback=22, tol=0.003):
    if len(df) < lookback: return False
    seg = df.iloc[-lookback:]
    l1 = seg["low"].idxmin()
    seg2 = seg.drop(index=l1)
    l2 = seg2["low"].idxmin()
    v1, v2 = df.loc[l1, "low"], df.loc[l2, "low"]
    return abs(v1 - v2) / ((v1 + v2) / 2) < tol

def double_top(df, lookback=22, tol=0.003):
    if len(df) < lookback: return False
    seg = df.iloc[-lookback:]
    h1 = seg["high"].idxmax()
    seg2 = seg.drop(index=h1)
    h2 = seg2["high"].idxmax()
    v1, v2 = df.loc[h1, "high"], df.loc[h2, "high"]
    return abs(v1 - v2) / ((v1 + v2) / 2) < tol

def hs_hint(df, lookback=34):
    if len(df) < lookback: return False
    seg = df["close"].iloc[-lookback:]
    peaks = seg[(seg.shift(1) < seg) & (seg.shift(-1) < seg)]
    return len(peaks) >= 3

def trendline_breakout(df, lookback=30):
    """Грубий брейкаут: регресія на low (up) / high (down) + остання свічка пробила."""
    if len(df) < lookback: return None
    seg = df.iloc[-lookback:]
    x = np.arange(len(seg))
    coef_up = np.polyfit(x, seg["low"].values, 1)
    tl_up = np.poly1d(coef_up)(x)
    coef_dn = np.polyfit(x, seg["high"].values, 1)
    tl_dn = np.poly1d(coef_dn)(x)

    last = seg.iloc[-1]
    if last["close"] > tl_dn[-1] and coef_dn[0] < 0:
        return "BREAK_UP"
    if last["close"] < tl_up[-1] and coef_up[0] > 0:
        return "BREAK_DOWN"
    return None

# =================== РИЗИК/СЕСІЇ ===================

def in_sessions_utc(dt_utc):
    if not FEAT_SESSIONS:
        return True
    h = dt_utc.hour
    for a, b in SESSIONS_UTC:
        if a <= h <= b:
            return True
    return False

# Позиції/історія/PnL
class PositionManager:
    def __init__(self):
        self.pos = {}
        self.history = []
        self.daily_pnl = 0.0
        self.daily_date = now_utc().date()

    def rollover_daily(self):
        d = now_utc().date()
        if d != self.daily_date:
            self.daily_pnl = 0.0
            self.daily_date = d

    def open(self, symbol, side, entry, tp1, tp2, tp3, sl, size=1.0):
        self.pos[symbol] = {
            "side": side, "entry": entry,
            "tp1": tp1, "tp2": tp2, "tp3": tp3,
            "sl": sl, "tp_hit": 0, "opened_at": now_utc(),
            "size": size
        }
        self.history.append({"event":"OPEN","symbol":symbol,"side":side,"entry":entry,
                             "tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"time":now_utc()})

    def close(self, symbol, reason, exit_price=None):
        if symbol in self.pos:
            p = self.pos.pop(symbol)
            if exit_price is None:
                exit_price = p["entry"]
            pnl = (exit_price - p["entry"]) * (1 if p["side"]=="LONG" else -1)
            rr_unit = max(1e-9, abs(p["entry"] - p["sl"]))
            pnl_rel = (pnl / rr_unit) * 0.01  # скейлінг
            self.daily_pnl += pnl_rel
            self.history.append({"event":"CLOSE","symbol":symbol,"reason":reason,
                                 "exit":exit_price,"pnl_rel":pnl_rel, "pos":p, "time":now_utc()})

    def get(self, symbol):
        return self.pos.get(symbol)

    def all_positions(self):
        return self.pos.copy()

    def all_history(self):
        return list(self.history)

pos_manager = PositionManager()

# Антиспам/стан
class State:
    def __init__(self, symbols):
        self.last_bar_ts = {s: None for s in symbols}
        self.last_signal_time = {s: 0 for s in symbols}
        self.last_sl_time = {s: 0 for s in symbols}
        self.cvd_cache = {s: 0.0 for s in symbols}

state = State(SYMBOLS)

# Кореляції (буфер котирувань)
price_buffers = {s: deque(maxlen=ROLL_CORR_WINDOW) for s in SYMBOLS}

def pairwise_corr_block(new_sym, new_side):
    if not FEAT_CORREL_FILTER:
        return False, None
    for s, p in pos_manager.all_positions().items():
        if s == new_sym:
            continue
        if p["side"] == new_side:
            if len(price_buffers[s]) >= 20 and len(price_buffers[new_sym]) >= 20:
                a = pd.Series(price_buffers[s]).pct_change().dropna()
                b = pd.Series(price_buffers[new_sym]).pct_change().dropna()
                L = min(len(a), len(b))
                if L >= 20:
                    c = a.iloc[-L:].corr(b.iloc[-L:])
                    if c is not None and c > CORR_BLOCK_THR:
                        return True, (s, c)
    return False, None

# =================== СКОРИНГ ===================

def build_scores(df_closed, symbol):
    reasons = []
    long_score = 0.0
    short_score = 0.0

    # Флет
    rng = (df_closed["high"].iloc[-6:] - df_closed["low"].iloc[-6:]).mean()
    mean_close = df_closed["close"].iloc[-6:].mean()
    if rng / mean_close < FLAT_THRESHOLD:
        return None

    # ATR
    atr = AverageTrueRange(df_closed["high"], df_closed["low"], df_closed["close"], window=14).average_true_range().iloc[-1]
    atr_rel = atr / df_closed["close"].iloc[-1]
    if not (ATR_MIN_REL <= atr_rel <= ATR_MAX_REL):
        return None

    last_close = df_closed["close"].iloc[-1]

    # Orderbook bias + volume imbalance
    if FEAT_VOL_IMBAL:
        ob_side, ob_w, imb = get_orderbook_bias(symbol)
    else:
        ob_side, ob_w, imb = get_orderbook_bias(symbol)
    if ob_side == "LONG":
        long_score += ob_w; reasons.append("📊 Orderbook: сильні покупки")
    elif ob_side == "SHORT":
        short_score += ob_w; reasons.append("📊 Orderbook: сильні продажі")

    # BOS/CHoCH
    if FEAT_BOS_CHOCH:
        bos = detect_bos_choch(df_closed)
        if bos == "BOS_UP":
            long_score += 1.2; reasons.append("📈 BOS: злам вгору")
        elif bos == "BOS_DOWN":
            short_score += 1.2; reasons.append("📉 BOS: злам вниз")

    # Sweep
    if FEAT_SWEEP:
        sw = detect_sweep(df_closed)
        if sw == "SWEEP_UP":
            long_score += 0.9; reasons.append("🚀 Sweep: забрали ліквідність зверху")
        elif sw == "SWEEP_DOWN":
            short_score += 0.9; reasons.append("🔥 Sweep: забрали ліквідність знизу")

    # Order Block hints
    if FEAT_OB_ORDERBLOCK:
        bull, bear = order_block_hint(df_closed)
        if bull:
            long_score += 0.7; reasons.append("💎 Order Block: покупець")
        if bear:
            short_score += 0.7; reasons.append("💎 Order Block: продавець")

    # FVG / BPR
    if FEAT_FVG_BPR:
        fvg, fvg_reason = find_fvg(df_closed)
        if fvg:
            if fvg[0] == "BULL":
                long_score += 0.7; reasons.append(f"{fvg_reason} {fvg[1][0]:.6f}-{fvg[1][1]:.6f}")
            else:
                short_score += 0.7; reasons.append(f"{fvg_reason} {fvg[1][0]:.6f}-{fvg[1][1]:.6f}")
        bpr, bpr_reason = find_bpr(df_closed)
        if bpr:
            if bpr[0] == "BULL":
                long_score += 0.6; reasons.append(f"{bpr_reason} {bpr[1][0]:.6f}-{bpr[1][1]:.6f}")
            else:
                short_score += 0.6; reasons.append(f"{bpr_reason} {bpr[1][0]:.6f}-{bpr[1][1]:.6f}")

    # SMT
    if FEAT_SMT and symbol in BENCH_FOR_SMT:
        bench = BENCH_FOR_SMT[symbol]
        bdf = get_ohlcv(bench, timeframe=TIMEFRAME, limit=120)
        if bdf is not None and len(bdf) >= 20:
            sig = smt_div_pair(df_closed["close"], bdf.iloc[:-1]["close"])
            if sig == "SMT_BULL": long_score += 0.6; reasons.append(f"🔁 SMT bull vs {bench}")
            if sig == "SMT_BEAR": short_score += 0.6; reasons.append(f"🔁 SMT bear vs {bench}")

    # HTF тренд + рівні
    if FEAT_MTF_CONFIRM:
        d5 = get_ohlcv(symbol, timeframe=HTF_TIMEFRAME, limit=EMA_SLOW+30)
        if d5 is not None and len(d5) > EMA_SLOW+5:
            close5 = d5["close"].iloc[:-1]
            ema_fast = EMAIndicator(close5, EMA_FAST).ema_indicator().iloc[-1]
            ema_slow = EMAIndicator(close5, EMA_SLOW).ema_indicator().iloc[-1]
            if ema_fast > ema_slow:
                long_score += 0.5; reasons.append("⏫ HTF тренд UP")
            elif ema_fast < ema_slow:
                short_score += 0.5; reasons.append("⏬ HTF тренд DOWN")

    if FEAT_HTF_LEVELS:
        lv = htf_levels(symbol)
        if lv:
            for name, val in lv.items():
                dist = abs(last_close - val) / last_close
                if dist < 0.002:
                    reasons.append(f"📎 Біля рівня {name}: {val:.6f}")

    # Патерни
    if FEAT_CLASSIC_PATTERNS:
        if double_bottom(df_closed): long_score += 0.5; reasons.append("🔹 Double Bottom")
        if double_top(df_closed):    short_score += 0.5; reasons.append("🔹 Double Top")
        if hs_hint(df_closed):       short_score += 0.3; reasons.append("🔹 Head & Shoulders (hint)")
        brk = trendline_breakout(df_closed)
        if brk == "BREAK_UP": long_score += 0.4; reasons.append("📐 Trendline breakout UP")
        if brk == "BREAK_DOWN": short_score += 0.4; reasons.append("📐 Trendline breakout DOWN")

    # OBV + «дельта»
    if FEAT_OBV_CVD_DELTA:
        try:
            obv = OnBalanceVolumeIndicator(df_closed["close"], df_closed["volume"]).on_balance_volume()
            if obv.iloc[-1] > obv.iloc[-3]:
                long_score += 0.2; reasons.append("📦 OBV up")
            elif obv.iloc[-1] < obv.iloc[-3]:
                short_score += 0.2; reasons.append("📦 OBV down")
        except Exception:
            pass

        dlt, cvd = get_trades_delta(symbol, limit=120)
        if dlt > 0:
            long_score += 0.2; reasons.append("🟢 Delta buy>sell")
        elif dlt < 0:
            short_score += 0.2; reasons.append("🔴 Delta sell>buy")

    # Преміум/Діскаунт (Fibo 0.5)
    if FEAT_PREMIUM_DISCOUNT:
        z = premium_discount_zone(df_closed, lookback=60)
        if z:
            lo, mid, hi = z
            if last_close < mid:
                long_score += 0.15; reasons.append("💚 Discount zone (<0.5)")
            else:
                short_score += 0.15; reasons.append("❤️ Premium zone (>0.5)")

    return (long_score, short_score, reasons, atr, atr_rel, last_close)

# =================== TP/SL / ТРЕЙЛІНГ ===================

def last_swing_levels(df, lookback=10):
    sw_hi = df["high"].iloc[-lookback-1:-1].max()
    sw_lo = df["low"].iloc[-lookback-1:-1].min()
    return sw_hi, sw_lo

def manage_open_position(symbol, df_closed):
    p = pos_manager.get(symbol)
    if not p: return

    last = df_closed.iloc[-1]
    side = p["side"]

    # Стандартний контроль TP/SL по high/low свічки
    if side == "LONG":
        if last["low"] <= p["sl"]:
            pos_manager.close(symbol, "SL", exit_price=p["sl"])
            send(f"🔔 *{symbol}*: 🛑 SL спрацював")
            state.last_sl_time[symbol] = time.time()
            return
        if p["tp_hit"] < 1 and last["high"] >= p["tp1"]:
            p["tp_hit"] = 1
            p["sl"] = p["entry"]   # BE локально
            if TRADE_LIVE and BYBIT_KEY and BYBIT_SECRET:
                move_sl_to_be(symbol, side, p["entry"])
            send(f"🎯 *{symbol}*: TP1 `{p['tp1']:.6f}` — SL -> BE")
        if p["tp_hit"] < 2 and last["high"] >= p["tp2"]:
            p["tp_hit"] = 2
            send(f"🎯 *{symbol}*: TP2 `{p['tp2']:.6f}`")
        if p["tp_hit"] < 3 and last["high"] >= p["tp3"]:
            p["tp_hit"] = 3
            pos_manager.close(symbol, "TP3", exit_price=p["tp3"])
            send(f"🎯 *{symbol}*: TP3 `{p['tp3']:.6f}` — позицію закрито")
            return

        # трейл по свінгу
        if FEAT_TRAILING_SWING and p["tp_hit"] >= 1:
            sw_hi, sw_lo = last_swing_levels(df_closed, lookback=8)
            p["sl"] = max(p["sl"], sw_lo)

    if side == "SHORT":
        if last["high"] >= p["sl"]:
            pos_manager.close(symbol, "SL", exit_price=p["sl"])
            send(f"🔔 *{symbol}*: 🛑 SL спрацював")
            state.last_sl_time[symbol] = time.time()
            return
        if p["tp_hit"] < 1 and last["low"] <= p["tp1"]:
            p["tp_hit"] = 1
            p["sl"] = p["entry"]   # BE локально
            if TRADE_LIVE and BYBIT_KEY and BYBIT_SECRET:
                move_sl_to_be(symbol, side, p["entry"])
            send(f"🎯 *{symbol}*: TP1 `{p['tp1']:.6f}` — SL -> BE")
        if p["tp_hit"] < 2 and last["low"] <= p["tp2"]:
            p["tp_hit"] = 2
            send(f"🎯 *{symbol}*: TP2 `{p['tp2']:.6f}`")
        if p["tp_hit"] < 3 and last["low"] <= p["tp3"]:
            p["tp_hit"] = 3
            pos_manager.close(symbol, "TP3", exit_price=p["tp3"])
            send(f"🎯 *{symbol}*: TP3 `{p['tp3']:.6f}` — позицію закрито")
            return

        if FEAT_TRAILING_SWING and p["tp_hit"] >= 1:
            sw_hi, sw_lo = last_swing_levels(df_closed, lookback=8)
            p["sl"] = min(p["sl"], sw_hi)

# =================== ОСНОВНА ЛОГІКА ===================

def process_symbol(symbol):
    df = get_ohlcv(symbol, timeframe=TIMEFRAME, limit=280)
    if df is None or len(df) < 50:
        return

    # заповнюємо буфер для кореляцій
    price_buffers[symbol].append(float(df["close"].iloc[-1]))

    df_closed = df.iloc[:-1].copy()
    if len(df_closed) < 50:
        return

    # сесії
    if not in_sessions_utc(now_utc()):
        return

    # один сигнал на бар
    last_ts = df_closed["ts"].iloc[-1]
    if ONE_SIGNAL_PER_BAR and state.last_bar_ts[symbol] == last_ts:
        return
    state.last_bar_ts[symbol] = last_ts

    # керування відкритою позицією
    manage_open_position(symbol, df_closed)

    # кулдауни
    nowt = time.time()
    if nowt - state.last_sl_time[symbol] < COOLDOWN_AFTER_SL_SEC:
        return
    if nowt - state.last_signal_time[symbol] < COOLDOWN_SEC:
        return

    # денний ризик-guard
    pos_manager.rollover_daily()
    if FEAT_DAILY_RISK_GUARD:
        if pos_manager.daily_pnl <= DAILY_MAX_LOSS or pos_manager.daily_pnl >= DAILY_MAX_WIN:
            return

    built = build_scores(df_closed, symbol)
    if not built:
        return
    long_score, short_score, reasons, atr, atr_rel, last_close = built

    # вибірна логіка з порогами
    final_signal = None
    if long_score >= MIN_SCORE and long_score >= short_score + SCORE_MARGIN:
        final_signal = "LONG"
    elif short_score >= MIN_SCORE and short_score >= long_score + SCORE_MARGIN:
        final_signal = "SHORT"

    if not final_signal:
        return

    # блок через кореляцію з існуючими позиціями
    blocked, info = pairwise_corr_block(symbol, final_signal)
    if blocked:
        pair, corr = info
        reasons.append(f"⛔ Кореляція з {pair} = {corr:.2f} — скіп")
        return

    # якщо вже є така ж позиція — не дублюємо; якщо протилежна — реверс
    cur = pos_manager.get(symbol)

    # розрахунок TP/SL
    entry = last_close
    tp1 = entry + TP1_ATR*atr if final_signal=="LONG" else entry - TP1_ATR*atr
    tp2 = entry + TP2_ATR*atr if final_signal=="LONG" else entry - TP2_ATR*atr
    tp3 = entry + TP3_ATR*atr if final_signal=="LONG" else entry - TP3_ATR*atr

    # SL по структурі (свінг) як пріоритет; якщо нема — ATR
    sw_hi, sw_lo = last_swing_levels(df_closed, lookback=8)
    if final_signal == "LONG":
        sl_struct = sw_lo
        sl = min(entry - 0.1*atr, sl_struct) if sl_struct < entry else entry - SL_ATR*atr
    else:
        sl_struct = sw_hi
        sl = max(entry + 0.1*atr, sl_struct) if sl_struct > entry else entry + SL_ATR*atr

    # RR check (до TP2)
    rr = abs(tp2 - entry) / max(1e-9, abs(entry - sl))
    if rr < MIN_RR:
        return

    if cur:
        pos_manager.close(symbol, "REVERSE", exit_price=entry)

    pos_manager.open(symbol, final_signal, entry, tp1, tp2, tp3, sl, size=1.0)
    state.last_signal_time[symbol] = time.time()

    # Жива торгівля: виставляємо ордери
    if TRADE_LIVE and BYBIT_KEY and BYBIT_SECRET:
        place_entry_with_tpsl(symbol, final_signal, entry, tp1, tp2, tp3, sl)

    msg = (
        f"⚡ *{symbol}* {TIMEFRAME}\n"
        f"✅ Нова позиція: *{final_signal}*\n"
        f"💰 Entry: `{entry:.6f}`\n"
        f"🎯 TP1/TP2/TP3: `{tp1:.6f}` / `{tp2:.6f}` / `{tp3:.6f}`\n"
        f"🛑 SL: `{sl:.6f}`\n"
        f"📊 Score L/S: {long_score:.2f} / {short_score:.2f}\n"
        f"📉 ATR(rel): {atr_rel:.4f}\n\n"
        f"*Причини:*\n- " + "\n- ".join(dict.fromkeys(reasons))
    )
    send(msg)

# =================== HEARTBEAT ===================
def get_total_balance(asset: str = "USDT", params: dict = None):
    """
    Повертає total-баланс у вказаній валюті (за замовчанням USDT).
    Для ф'ючерсів/перпів можна передати params={"type": "future"} або {"type": "swap"}.
    """
    try:
        if params is None:
            params = {}
        bal = exchange.fetch_balance(params)

        total_val = None
        # ccxt зазвичай має форму bal["total"]["USDT"]
        if isinstance(bal, dict):
            if "total" in bal and isinstance(bal["total"], dict) and asset in bal["total"]:
                total_val = bal["total"][asset]
            elif asset in bal and isinstance(bal[asset], dict) and "total" in bal[asset]:
                total_val = bal[asset]["total"]

        return float(total_val) if total_val is not None else None
    except Exception as e:
        print(f"[BALANCE ERROR] {e}")
        return None


def heartbeat():
    balance = get_total_balance(asset="USDT")  # для деривативів: get_total_balance("USDT", {"type": "swap"})
    msg = f"💰 Баланс: {balance:.2f} USDT" if balance is not None else "💰 Баланс: ?"
    send(msg)



# =================== ЗАПУСК ===================

send(f"💚 Бот запущено та працює ✅\n🕒 {now_utc().strftime('%Y-%m-%d %H:%M:%S UTC')}")

last_hb = time.time()
while True:
    try:
        for sym in SYMBOLS:
            process_symbol(sym)
        if time.time() - last_hb > 60:
            heartbeat()
            last_hb = time.time()
        time.sleep(5)
    except Exception as e:
        print("[LOOP ERROR]", e)
        time.sleep(2)

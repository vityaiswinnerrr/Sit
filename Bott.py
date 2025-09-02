#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI+SMC Bybit Trading Bot (single-file) — FIXED
- Fixes KeyError caused by symbol normalization mismatch (e.g., 'ARB/USDT' vs 'ARB/USDT:USDT').
- Normalizes SYMBOLS once up-front and uses the SAME form everywhere.
- Adds setdefault guards for state.price_buffers to avoid missing-key crashes.
- Removes late re-normalization in __main__ to prevent drift with prebuilt State.

IMPORTANT: Replace the placeholder API and Telegram tokens with your OWN credentials.

Requirements (pip):
  pip install ccxt pandas numpy ta python-telegram-bot==20.* pybi

Env vars you must set:
  BYBIT_KEY, BYBIT_SECRET
  TG_TOKEN, TG_CHAT_ID
Optional:
  TIMEFRAME (default "5m"), TRADE_LIVE ("true"/"false"), BYBIT_TESTNET ("true"/"false")
  CUSTOM1, CUSTOM2, CUSTOM3 — extra symbols like "SOL/USDT" (":USDT" will be added automatically)
"""

import os, time, math, traceback, re
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from collections import deque

# --- Third-party (optional availability handled) ---
try:
    from telegram import Bot
except Exception:
    Bot = None

try:
    from pybit.unified_trading import HTTP
except Exception:
    HTTP = None

# TA
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator

# ====================== EARLY HELPERS (for symbol normalization) ======================

def ccxt_sym(sym: str) -> str:
    """Ensure CCXT linear market form 'BASE/USDT:USDT'. Works BEFORE exchange init."""
    if not isinstance(sym, str):
        return sym
    if ":USDT" in sym:
        return sym
    if sym.endswith("/USDT"):
        return sym + ":USDT"
    return sym

def bybit_v5_sym(sym: str) -> str:
    return ccxt_sym(sym).replace("/", "").replace(":USDT", "").upper()

# ====================== CONFIG ======================
BYBIT_KEY    = os.getenv("BYBIT_KEY", "m4qlJh0Vec5PzYjHiC")
BYBIT_SECRET = os.getenv("BYBIT_SECRET", "bv4MJZaIOkV3SSBbiH7ugxqyjDww4CEUTp54")
TG_TOKEN     = os.getenv("TG_TOKEN", "7844283362:AAHuxfe22q3K0uvtGcrcgm6iqOEqduU9r-k")
TG_CHAT_ID   = os.getenv("TG_CHAT_ID", "5369718011")

TIMEFRAME    = os.getenv("TIMEFRAME", "5m")            # 1m .. 1h
LEVERAGE     = int(os.getenv("LEVERAGE", "50"))
TRADE_LIVE   = os.getenv("TRADE_LIVE", "true").lower() in ("1","true","yes","y")
TESTNET      = os.getenv("BYBIT_TESTNET", "false").lower() in ("1","true","yes","y")

# Default symbols + 3 custom slots via env (allow plain 'BASE/USDT')
raw_syms = [
    "ARB/USDT", "DOGE/USDT", "WLD/USDT",
    os.getenv("CUSTOM1", ""), os.getenv("CUSTOM2", ""), os.getenv("CUSTOM3", "")
]
# Normalize ONCE, up-front, so every component uses the same exact form
SYMBOLS = [ccxt_sym(s) for s in raw_syms if s and s.strip()]

# Sizing
SIZE_PCT_BASE = 0.10   # 10% of USDT balance
SIZE_PCT_CONF = 0.20   # 20% if AI confidence >= 0.80
CONF_STRONG   = 0.80

# TP distribution (default, AI may override per trade)
TP_PCTS_DEFAULT = (0.30, 0.30, 0.40)

# SMC / filters
ONE_SIGNAL_PER_BAR   = True
MIN_SCORE            = 3.2
SCORE_MARGIN         = 0.7
FLAT_THRESHOLD       = 0.0006
ATR_MIN_REL          = 0.0008
ATR_MAX_REL          = 0.02
TP1_ATR              = 0.8
TP2_ATR              = 1.5
TP3_ATR              = 2.5
SL_ATR               = 1.5
MIN_RR               = 1.5
ROLL_CORR_WINDOW     = 60
CORR_BLOCK_THR       = 0.80
HTF_TIMEFRAME        = "15m"
EMA_FAST             = 50
EMA_SLOW             = 200
BENCH_FOR_SMT        = {}

# Build bench map (vs BTC) lazily from SYMBOLS — using the already-normalized forms
for s in SYMBOLS:
    BENCH_FOR_SMT[s] = "BTC/USDT"  # we'll normalize again inside get_ohlcv

# Sessions for optional scheduling (not enforced by default)
FEAT_SESSIONS  = False
SESSIONS_UTC   = [(4,11),(12,17),(18,20)]

# Telegram init

def escape_md(text: str) -> str:
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\\-])', r'\\\\\\1', text)

def safe_send(text: str):
    if TG_TOKEN and TG_CHAT_ID and Bot is not None:
        try:
            bot = Bot(TG_TOKEN)
            bot.send_message(chat_id=TG_CHAT_ID, text=escape_md(text), parse_mode="MarkdownV2")
            return
        except Exception as e:
            print(f"[TG ERROR] {e}")
    print(f"[TG LOG] {text}")

# Exchange init (ccxt)
exchange = ccxt.bybit({
    "apiKey": BYBIT_KEY,
    "secret": BYBIT_SECRET,
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
        "defaultSettle": "USDT",
        "adjustForTimeDifference": True,
    },
    "recvWindow": 700000,
    "urls": {"api": {"public": "https://api.bybit.com", "private": "https://api.bybit.com"}} if not TESTNET else None,
})

# pybit session for precise SL
session = None
if HTTP and BYBIT_KEY and BYBIT_SECRET:
    try:
        session = HTTP(api_key=BYBIT_KEY, api_secret=BYBIT_SECRET, testnet=TESTNET)
    except Exception as e:
        print("[PYBIT WARN] session init failed:", e)

# ====================== HELPERS ======================

def now_utc():
    return datetime.now(timezone.utc)

# Precision wrappers

def px(symbol, price):
    s = ccxt_sym(symbol)
    return float(exchange.price_to_precision(s, float(price)))


def amt(symbol, amount):
    s = ccxt_sym(symbol)
    try:
        return float(exchange.amount_to_precision(s, float(amount)))
    except Exception:
        return float(amount)

# Market limits

def get_market(symbol):
    return exchange.market(ccxt_sym(symbol))


def get_min_cost(symbol):
    try:
        m = get_market(symbol)
        return float(((m.get('limits', {}) or {}).get('cost', {}) or {}).get('min', 0) or 0)
    except Exception:
        return 0.0


def get_min_amount(symbol):
    try:
        m = get_market(symbol)
        return float(((m.get('limits', {}) or {}).get('amount', {}) or {}).get('min', 0) or 0)
    except Exception:
        return 0.0

# Balance / price

def get_total_balance(asset: str = "USDT"):
    try:
        bal = exchange.fetch_balance({"type": "swap"})
        if isinstance(bal, dict):
            if "total" in bal and asset in bal["total"]:
                return float(bal["total"][asset] or 0.0)
            if asset in bal and isinstance(bal[asset], dict):
                return float(bal[asset].get("total", 0.0) or 0.0)
    except Exception as e:
        print("[BALANCE ERROR]", e)
    return 0.0


def get_last_price(symbol):
    s = ccxt_sym(symbol)
    try:
        ob = exchange.fetch_order_book(s, limit=1)
        bid = ob["bids"][0][0] if ob["bids"] else None
        ask = ob["asks"][0][0] if ob["asks"] else None
        if bid and ask:
            return (bid + ask) / 2.0
    except Exception:
        pass
    try:
        t = exchange.fetch_ticker(s)
        return float(t.get("last") or t.get("close"))
    except Exception:
        return None


def calc_amount_by_usdt(symbol, usdt, leverage=1.0):
    price = get_last_price(symbol)
    if not price or price <= 0:
        return 0.0
    notional = float(usdt) * float(leverage)
    qty = notional / price
    min_cost = get_min_cost(symbol)
    if min_cost and price * qty < min_cost:
        qty = max(qty, min_cost / price)
    min_amt = get_min_amount(symbol)
    if min_amt and qty < min_amt:
        qty = max(qty, min_amt)
    qty = amt(symbol, qty)
    return max(qty, 0.0)

# OHLCV fetcher

def get_ohlcv(symbol, timeframe=TIMEFRAME, limit=300):
    try:
        df = pd.DataFrame(
            exchange.fetch_ohlcv(ccxt_sym(symbol), timeframe=timeframe, limit=limit),
            columns=["ts","open","high","low","close","volume"],
        )
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df
    except Exception as e:
        print(f"[OHLCV ERROR] {symbol}", e)
        return None

# ====================== SMC / PATTERNS ======================

def detect_bos_choch(df):
    if len(df) < 12:
        return None
    highs = df["high"].iloc[-7:-1].max()
    lows  = df["low"].iloc[-7:-1].min()
    last_close = df["close"].iloc[-1]
    if last_close > highs: return "BOS_UP"
    if last_close < lows:  return "BOS_DOWN"
    return None


def find_fvg(df):
    if len(df) < 5:
        return None, None
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if c.low > a.high:
        return ("BULL", (a.high, c.low)), "FVG⬆️"
    if c.high < a.low:
        return ("BEAR", (c.high, a.low)), "FVG⬇️"
    return None, None


def order_block_hint(df):
    recent = df.iloc[-8:]
    vol_thr = recent["volume"].mean() * 1.6
    bull = any((recent["volume"] > vol_thr) & (recent["close"] > recent["open"]))
    bear = any((recent["volume"] > vol_thr) & (recent["close"] < recent["open"]))
    return bull, bear


def premium_discount_zone(df, lookback=60):
    if len(df) < lookback:
        return None
    seg = df.iloc[-lookback:]
    hi = seg["high"].max()
    lo = seg["low"].min()
    mid = (hi + lo) / 2.0
    return lo, mid, hi


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
    if len(df) < lookback: return None
    seg = df.iloc[-lookback:]
    x = np.arange(len(seg))
    coef_up = np.polyfit(x, seg["low"].values, 1)
    coef_dn = np.polyfit(x, seg["high"].values, 1)
    tl_up = np.poly1d(coef_up)(x)
    tl_dn = np.poly1d(coef_dn)(x)
    last = seg.iloc[-1]
    if last.close > tl_dn[-1] and coef_dn[0] < 0:
        return "BREAK_UP"
    if last.close < tl_up[-1] and coef_up[0] > 0:
        return "BREAK_DOWN"
    return None

# SMT divergence against BTC

def smt_div_pair(sym_close, bench_close):
    if len(sym_close) < 10 or len(bench_close) < 10:
        return None
    s = sym_close.iloc[-5:]
    b = bench_close.iloc[-5:]
    bull = (s.min() < s.iloc[0]*0.999) and (b.min() >= b.iloc[0]*0.999)
    bear = (s.max() > s.iloc[0]*1.001) and (b.max() <= b.iloc[0]*1.001)
    if bull: return "SMT_BULL"
    if bear: return "SMT_BEAR"
    return None

# ====================== AI SCORING ======================

def build_scores(df_closed, symbol):
    reasons = []
    long_score = 0.0
    short_score = 0.0

    rng = (df_closed["high"].iloc[-6:] - df_closed["low"].iloc[-6:]).mean()
    mean_close = df_closed["close"].iloc[-6:].mean()
    if rng / mean_close < FLAT_THRESHOLD:
        return None

    atr = AverageTrueRange(df_closed["high"], df_closed["low"], df_closed["close"], window=14).average_true_range().iloc[-1]
    atr_rel = atr / df_closed["close"].iloc[-1]
    if not (ATR_MIN_REL <= atr_rel <= ATR_MAX_REL):
        return None

    last_close = df_closed["close"].iloc[-1]

    # BOS/CHOCH
    bos = detect_bos_choch(df_closed)
    if bos == "BOS_UP":
        long_score += 1.2; reasons.append("📈 BOS up")
    elif bos == "BOS_DOWN":
        short_score += 1.2; reasons.append("📉 BOS down")

    # FVG / imbalance
    fvg, fvg_reason = find_fvg(df_closed)
    if fvg:
        if fvg[0] == "BULL":
            long_score += 0.7; reasons.append(f"{fvg_reason}")
        else:
            short_score += 0.7; reasons.append(f"{fvg_reason}")

    # OB hint
    bull, bear = order_block_hint(df_closed)
    if bull: long_score += 0.6; reasons.append("💎 OB buyer")
    if bear: short_score += 0.6; reasons.append("💎 OB seller")

    # HTF EMA trend
    d5 = get_ohlcv(symbol, timeframe=HTF_TIMEFRAME, limit=EMA_SLOW+40)
    if d5 is not None and len(d5) > EMA_SLOW+5:
        close5 = d5["close"].iloc[:-1]
        ema_fast = EMAIndicator(close5, EMA_FAST).ema_indicator().iloc[-1]
        ema_slow = EMAIndicator(close5, EMA_SLOW).ema_indicator().iloc[-1]
        if ema_fast > ema_slow:
            long_score += 0.5; reasons.append("⏫ HTF trend up")
        elif ema_fast < ema_slow:
            short_score += 0.5; reasons.append("⏬ HTF trend down")

    # SMT divergence vs BTC
    bench = BENCH_FOR_SMT.get(ccxt_sym(symbol), "BTC/USDT")
    bdf = get_ohlcv(bench, timeframe=TIMEFRAME, limit=120)
    if bdf is not None and len(bdf) >= 20:
        sig = smt_div_pair(df_closed["close"], bdf.iloc[:-1]["close"])
        if sig == "SMT_BULL": long_score += 0.6; reasons.append("🔁 SMT bull")
        if sig == "SMT_BEAR": short_score += 0.6; reasons.append("🔁 SMT bear")

    # Classic patterns
    if double_bottom(df_closed): long_score += 0.5; reasons.append("🔹 Double Bottom")
    if double_top(df_closed):    short_score += 0.5; reasons.append("🔹 Double Top")
    if hs_hint(df_closed):       short_score += 0.3; reasons.append("🔹 H&S hint")
    brk = trendline_breakout(df_closed)
    if brk == "BREAK_UP":   long_score += 0.4; reasons.append("📐 TL breakout up")
    if brk == "BREAK_DOWN": short_score += 0.4; reasons.append("📐 TL breakout down")

    # OBV momentum
    try:
        obv = OnBalanceVolumeIndicator(df_closed["close"], df_closed["volume"]).on_balance_volume()
        if obv.iloc[-1] > obv.iloc[-3]: long_score += 0.2; reasons.append("📦 OBV up")
        elif obv.iloc[-1] < obv.iloc[-3]: short_score += 0.2; reasons.append("📦 OBV down")
    except Exception:
        pass

    # Premium/Discount zone
    z = premium_discount_zone(df_closed, lookback=60)
    if z:
        lo, mid, hi = z
        if last_close < mid:
            long_score += 0.15; reasons.append("💚 Discount (<0.5)")
        else:
            short_score += 0.15; reasons.append("❤️ Premium (>0.5)")

    return (long_score, short_score, reasons, atr, atr_rel, last_close)


def ai_decision(df_closed, symbol):
    built = build_scores(df_closed, symbol)
    if not built:
        return None
    long_score, short_score, reasons, atr, atr_rel, last_close = built

    # Choose direction
    direction = None
    if long_score >= MIN_SCORE and long_score >= short_score + SCORE_MARGIN:
        direction = "LONG"
    elif short_score >= MIN_SCORE and short_score >= long_score + SCORE_MARGIN:
        direction = "SHORT"
    if not direction:
        return None

    # Dynamic RR choice
    trend_strength = abs(long_score - short_score)
    if trend_strength > 1.6 and atr_rel > (ATR_MIN_REL*1.5):
        rr_target = 3.0  # stronger trend → larger RR
    elif trend_strength > 1.0:
        rr_target = 2.2
    else:
        rr_target = 1.6

    # Baseline ATR multiples
    if direction == "LONG":
        tp1 = last_close + TP1_ATR*atr
        tp2 = last_close + TP2_ATR*atr
        tp3 = last_close + TP3_ATR*atr
        sl  = last_close - SL_ATR*atr
    else:
        tp1 = last_close - TP1_ATR*atr
        tp2 = last_close - TP2_ATR*atr
        tp3 = last_close - TP3_ATR*atr
        sl  = last_close + SL_ATR*atr

    # Adjust to meet RR target (use tp2 as reference TP)
    entry = last_close
    current_rr = abs(tp2 - entry) / max(1e-9, abs(entry - sl))
    scale = rr_target / max(current_rr, 1e-9)
    tp1 = entry + (tp1 - entry) * scale
    tp2 = entry + (tp2 - entry) * scale
    tp3 = entry + (tp3 - entry) * scale

    # Confidence (0..1)
    top = max(long_score, short_score)
    confidence = max(0.0, min(1.0, (top - MIN_SCORE) / (MIN_SCORE + 2.5)))

    # TP size distribution can vary with confidence
    if confidence >= 0.85:
        tp_pcts = (0.25, 0.30, 0.45)
    elif confidence >= 0.65:
        tp_pcts = (0.30, 0.30, 0.40)
    else:
        tp_pcts = (0.35, 0.35, 0.30)

    return {
        "direction": direction,
        "entry": float(entry),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "tp3": float(tp3),
        "sl": float(sl),
        "confidence": float(confidence),
        "tp_pcts": tp_pcts,
        "reasons": reasons,
    }

# ====================== RISK / TRADE ======================

def ensure_leverage(symbol, leverage=LEVERAGE, margin_mode="isolated"):
    try:
        s = ccxt_sym(symbol)
        exchange.set_margin_mode(margin_mode, s)
        exchange.set_leverage(leverage, s)
        print(f"[LEV OK] {s}: lev={leverage} mode={margin_mode}")
    except Exception as e:
        print(f"[LEV WARN] {symbol}: {e}")


def move_sl_to_be(symbol, side, entry_price):
    if not session:
        print("[BE WARN] pybit session not available")
        return False
    try:
        buffer_pct = 0.0005
        buffer = entry_price * buffer_pct
        new_sl = entry_price - buffer if side.upper() == "LONG" else entry_price + buffer
        resp = session.set_trading_stop(category="linear", symbol=bybit_v5_sym(symbol), stopLoss=str(px(symbol, new_sl)))
        print(f"[SL->BE] {symbol} -> {new_sl} | {resp}")
        return True
    except Exception as e:
        print(f"[BE ERROR] {e}")
        return False

# ====================== ORDERS / POSITIONS ======================

def cancel_stale_orders(symbol, max_age_hours=3):
    """Видаляє лімітки, які стоять довше max_age_hours"""
    try:
        orders = exchange.fetch_open_orders(ccxt_sym(symbol))
        now_ts = time.time()
        for o in orders:
            # створено у мс → сек
            ctime = o.get("timestamp", 0) / 1000
            if ctime and (now_ts - ctime) > max_age_hours * 3600:
                try:
                    exchange.cancel_order(o["id"], ccxt_sym(symbol))
                    print(f"[STALE CANCEL] {symbol} id={o['id']}")
                except Exception as e:
                    print(f"[CANCEL ERROR] {symbol} id={o['id']} {e}")
    except Exception as e:
        print(f"[ORDERS ERROR] {symbol}: {e}")


def has_open_position(symbol, side=None):
    """Перевіряє чи є відкрита позиція (опціонально — тільки LONG/SHORT)"""
    try:
        positions = exchange.fetch_positions([ccxt_sym(symbol)])
        for p in positions:
            sz = float(p.get("contracts") or 0.0)
            if sz > 0:
                pos_side = "LONG" if float(p.get("side","").lower() == "long" or p.get("positionSide","") == "Buy") else "SHORT"
                if side is None or side.upper() == pos_side:
                    return True
    except Exception as e:
        print(f"[POS ERROR] {symbol}: {e}")
    return False


def place_entry_with_tpsl(symbol, side, amount_qty, entry_price, tp1, tp2, tp3, sl, tp_pcts=TP_PCTS_DEFAULT):
    """Market entry + 3 TPs (reduceOnly) + SL via pybit session.
    Returns True/False; does not block on fills.
    """
    try:
        s_ccxt = ccxt_sym(symbol)
        s_v5   = bybit_v5_sym(symbol)
        entry_side = "buy" if side.upper() == "LONG" else "sell"
        exit_side  = "sell" if side.upper() == "LONG" else "buy"

        q_all = amt(symbol, amount_qty)
        if q_all <= 0:
            print(f"[ENTRY SIZE] q_all<=0 for {symbol}")
            return False

        if TRADE_LIVE:
            entry_order = exchange.create_order(s_ccxt, "market", entry_side, q_all, None, {})
            print(f"[ENTRY] {entry_side} {s_ccxt} q={q_all} id={entry_order.get('id')}")
        else:
            print(f"[DRYRUN ENTRY] {entry_side} {s_ccxt} q={q_all}")

        # Split amounts
        t1p, t2p, t3p = tp_pcts
        q_tp1 = amt(symbol, q_all * t1p)
        q_tp2 = amt(symbol, q_all * t2p)
        q_tp3 = amt(symbol, max(0.0, q_all - q_tp1 - q_tp2))

        tp1_p = px(symbol, tp1)
        tp2_p = px(symbol, tp2)
        tp3_p = px(symbol, tp3)
        sl_p  = px(symbol, sl)

        # SL via session (more precise)
        try:
            if TRADE_LIVE and session:
                resp = session.set_trading_stop(category="linear", symbol=s_v5, stopLoss=str(sl_p))
                print(f"[SL] set @ {sl_p} | {resp}")
            else:
                print(f"[DRYRUN SL] {exit_side} {s_ccxt} @ {sl_p} q={q_all}")
        except Exception as e:
            print(f"[SL ERROR] {e}")

        # TP orders (reduce-only limits)
        try:
            if q_tp1 > 0:
                if TRADE_LIVE:
                    o1 = exchange.create_order(s_ccxt, "limit", exit_side, q_tp1, tp1_p, {"reduceOnly": True, "timeInForce":"GTC"})
                    print(f"[TP1] {o1.get('id','N/A')} @ {tp1_p} q={q_tp1}")
                else:
                    print(f"[DRYRUN TP1] {exit_side} {s_ccxt} @ {tp1_p} q={q_tp1}")

            if q_tp2 > 0:
                if TRADE_LIVE:
                    o2 = exchange.create_order(s_ccxt, "limit", exit_side, q_tp2, tp2_p, {"reduceOnly": True, "timeInForce":"GTC"})
                    print(f"[TP2] {o2.get('id','N/A')} @ {tp2_p} q={q_tp2}")
                else:
                    print(f"[DRYRUN TP2] {exit_side} {s_ccxt} @ {tp2_p} q={q_tp2}")

            if q_tp3 > 0:
                if TRADE_LIVE:
                    o3 = exchange.create_order(s_ccxt, "limit", exit_side, q_tp3, tp3_p, {"reduceOnly": True, "timeInForce":"GTC"})
                    print(f"[TP3] {o3.get('id','N/A')} @ {tp3_p} q={q_tp3}")
                else:
                    print(f"[DRYRUN TP3] {exit_side} {s_ccxt} @ {tp3_p} q={q_tp3}")
        except Exception as e:
            print(f"[TP PLACE ERROR] {e}")

        return True

    except Exception as e:
        print(f"[ENTRY ERROR] {e}")
        traceback.print_exc()
        return False

# ====================== SIGNAL / LOOP ======================

class State:
    def __init__(self, symbols):
        # Ensure dictionaries are keyed by the ALREADY-NORMALIZED symbols
        symbols = [ccxt_sym(s) for s in symbols]
        self.last_bar_ts = {s: None for s in symbols}
        self.last_signal_time = {s: 0 for s in symbols}
        self.last_sl_time = {s: 0 for s in symbols}
        self.price_buffers = {s: deque(maxlen=ROLL_CORR_WINDOW) for s in symbols}

state = State(SYMBOLS)


def in_sessions_utc(dt_utc):
    if not FEAT_SESSIONS:
        return True
    h = dt_utc.hour
    for a, b in SESSIONS_UTC:
        if a <= h <= b:
            return True
    return False


def pairwise_corr_block(new_sym, new_side):
    new_sym = ccxt_sym(new_sym)
    for s in SYMBOLS:
        s = ccxt_sym(s)
        if s == new_sym:
            continue
        a = pd.Series(list(state.price_buffers.get(s, []))).pct_change().dropna()
        b = pd.Series(list(state.price_buffers.get(new_sym, []))).pct_change().dropna()
        L = min(len(a), len(b))
        if L >= 20:
            c = a.iloc[-L:].corr(b.iloc[-L:])
            if c is not None and c > CORR_BLOCK_THR:
                return True, (s, c)
    return False, None


def send_signal(symbol, decision):
    msg = (
        f"🔔 \\1Signal\\1 — {ccxt_sym(symbol)}\n"
        f"\\1Dir\\1: {decision['direction']}  \\1Conf\\1: {decision['confidence']:.2f}\n"
        f"\\1Entry\\1: {decision['entry']:.6f}\n"
        f"\\1TP1/TP2/TP3\\1: {decision['tp1']:.6f} / {decision['tp2']:.6f} / {decision['tp3']:.6f}\n"
        f"\\1SL\\1: {decision['sl']:.6f}\n"
        f"\\1Why\\1: " + ", ".join(decision['reasons'][:6])
    )

def process_symbol(symbol):
    symbol = ccxt_sym(symbol)  # normalize once here

    cancel_stale_orders(symbol, max_age_hours=3)

    df = get_ohlcv(symbol, timeframe=TIMEFRAME, limit=280)
    if df is None or len(df) < 80:
        return

    # Guard against missing dict keys — auto-create buffer if absent
    buf = state.price_buffers.setdefault(symbol, deque(maxlen=ROLL_CORR_WINDOW))
    buf.append(float(df["close"].iloc[-1]))

    df_closed = df.iloc[:-1].copy()
    if len(df_closed) < 60:
        return
    if not in_sessions_utc(now_utc()):
        return

    last_ts = df_closed["ts"].iloc[-1]
    prev_ts = state.last_bar_ts.get(symbol)
    if ONE_SIGNAL_PER_BAR and prev_ts == last_ts:
        return
    state.last_bar_ts[symbol] = last_ts

    decision = ai_decision(df_closed, symbol)
    if not decision:
        return

    if has_open_position(symbol, side=decision["direction"]):
        print(f"[SKIP] {symbol} вже є {decision['direction']} позиція")
        return

    # Always send signal
    send_signal(symbol, decision)

    # Correlation block
    blocked, info = pairwise_corr_block(symbol, decision["direction"])
    if blocked:
        peer, corr = info
        print(f"[CORR BLOCK] {symbol} vs {peer} corr={corr:.2f}")
        return

    # Risk sizing
    total_balance = get_total_balance("USDT")
    size_pct = SIZE_PCT_CONF if decision["confidence"] >= CONF_STRONG else SIZE_PCT_BASE
    use_usdt = max(0.0, total_balance * size_pct)

    ensure_leverage(symbol, LEVERAGE)
    amount = calc_amount_by_usdt(symbol, use_usdt, leverage=LEVERAGE)
    if amount <= 0:
        safe_send(f"⚠️ *{ccxt_sym(symbol)}* Notional too small. Bal={total_balance:.2f} USDT")
        return

    # RR sanity
    rr = abs(decision["tp2"] - decision["entry"]) / max(1e-9, abs(decision["entry"] - decision["sl"]))
    if rr < MIN_RR:
        print(f"[RR SKIP] {symbol} RR={rr:.2f} < {MIN_RR}")
        return

    # Execute trade (optional)
    if TRADE_LIVE:
        ok = place_entry_with_tpsl(
            symbol=symbol,
            side=decision["direction"],
            amount_qty=amount,
            entry_price=decision["entry"],
            tp1=decision["tp1"], tp2=decision["tp2"], tp3=decision["tp3"],
            sl=decision["sl"],
            tp_pcts=decision.get("tp_pcts", TP_PCTS_DEFAULT),
        )
        if ok:
            safe_send(f"✅ *TRADE EXECUTED* {ccxt_sym(symbol)} {decision['direction']} q={amount}")
        else:
            safe_send(f"❌ *ENTRY ERROR* {ccxt_sym(symbol)} {decision['direction']}")
    else:
        print(f"[DRYRUN] would trade {symbol} {decision['direction']} q={amount}")



# ====================== HEARTBEAT / MAIN ======================

def heartbeat():
    try:
        bal = get_total_balance("USDT")
        safe_send(f"🟢 Alive | TF: {TIMEFRAME} | Lev: {LEVERAGE}x | Live: {TRADE_LIVE}\n💰 Balance: {bal:.2f} USDT\n📈 Symbols: {', '.join([ccxt_sym(s) for s in SYMBOLS])}")
    except Exception as e:
        print("[HB ERROR]", e)


def main():
    safe_send(f"✅ Bot started at {now_utc().strftime('%Y-%m-%d %H:%M:%S UTC')}\nTF: {TIMEFRAME} | Lev: {LEVERAGE}x | Live: {TRADE_LIVE}")
    last_hb = 0
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
            traceback.print_exc()
            safe_send(f"⚠️ Loop error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    # DO NOT re-normalize SYMBOLS here — we did it up-front and built State with the same keys.
    main()

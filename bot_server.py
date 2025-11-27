# bot_server.py - production-ready example
import os
import json
import threading
import time
import sqlite3
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import requests
import pandas as pd
import yfinance as yf

# Configuration from env
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHATID = os.getenv("TG_CHATID")
MON_INTERVAL = int(os.getenv("MON_INTERVAL", "15"))
TRAILING_ATR_MULT = float(os.getenv("TRAILING_ATR_MULT", "1.5"))
DB = os.getenv("DB_PATH", "positions.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Logging
logging.basicConfig(level=LOG_LEVEL,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("gorangen-bot")

# DB helpers
def init_db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                entry REAL,
                tp1 REAL, tp2 REAL, tp3 REAL,
                sl REAL, emergency_sl REAL,
                atr REAL,
                open_time TEXT,
                status TEXT,
                highest REAL
                )""")
    conn.commit()
    conn.close()

def save_position(pos):
    conn = sqlite3.connect(DB, check_same_thread=False)
    c = conn.cursor()
    c.execute("""INSERT INTO positions (symbol,entry,tp1,tp2,tp3,sl,emergency_sl,atr,open_time,status,highest)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              (pos['symbol'], pos['entry'], pos['tp1'], pos['tp2'], pos['tp3'],
               pos['sl'], pos['emergency_sl'], pos['atr'], datetime.utcnow().isoformat(), 'OPEN', pos['entry']))
    conn.commit()
    conn.close()

def fetch_open_positions():
    conn = sqlite3.connect(DB, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT symbol,entry,tp1,tp2,tp3,sl,emergency_sl,atr,highest FROM positions WHERE status='OPEN'")
    rows = c.fetchall()
    conn.close()
    return rows

def update_position_status(symbol, status):
    conn = sqlite3.connect(DB, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE positions SET status=? WHERE symbol=? AND status='OPEN'", (status, symbol))
    conn.commit()
    conn.close()

def update_highest(symbol, highest):
    conn = sqlite3.connect(DB, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE positions SET highest=? WHERE symbol=? AND status='OPEN'", (highest, symbol))
    conn.commit()
    conn.close()

# Telegram helper
def send_telegram_text(msg):
    if not TG_TOKEN or not TG_CHATID:
        logger.warning("Telegram token/chat id not configured.")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = {"chat_id": TG_CHATID, "text": msg, "parse_mode":"Markdown"}
    try:
        r = requests.post(url, data=data, timeout=10)
        r.raise_for_status()
        logger.info("Telegram sent")
        return r.json()
    except Exception as e:
        logger.exception("Failed to send telegram: %s", e)
        return None

# Market data (example via yfinance)
def get_realtime_price(symbol):
    sym = symbol if "." in symbol else symbol + ".JK"
    try:
        t = yf.Ticker(sym)
        df = t.history(period="1d", interval="1m")
        if df.empty:
            return None
        return float(df['Close'].iloc[-1])
    except Exception as e:
        logger.exception("Price fetch error: %s", e)
        return None

def fetch_recent_ohlcv(symbol, period="7d", interval="15m"):
    sym = symbol if "." in symbol else symbol + ".JK"
    t = yf.Ticker(sym)
    df = t.history(period=period, interval=interval)
    return df

def calc_atr(df, length=14):
    if df is None or df.empty:
        return None
    high = df['High']; low = df['Low']; close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(length).mean().iloc[-1]
    return float(atr)

def place_order(symbol, side, qty):
    # stub - replace with broker integration
    logger.info("PLACE ORDER: %s %s %s", side, qty, symbol)
    return {"status":"sim", "price": get_realtime_price(symbol)}

def monitor_position(symbol, entry, tp1, tp2, tp3, sl, emergency_sl, atr):
    logger.info("Monitor started for %s", symbol)
    highest = entry
    moved_to_be = False
    while True:
        price = get_realtime_price(symbol)
        if price is None:
            time.sleep(MON_INTERVAL); continue
        if price > highest:
            highest = price
            update_highest(symbol, highest)
        # move SL to BE at TP1
        if (not moved_to_be) and price >= tp1:
            sl = entry
            moved_to_be = True
            send_telegram_text(f"🔔 *{symbol}* TP1 hit. SL moved to Break-Even ({entry})")
        # recalc atr and trailing
        df = fetch_recent_ohlcv(symbol, period="7d", interval="15m")
        atr_now = calc_atr(df) if df is not None else atr
        trailing_sl = highest - (atr_now * TRAILING_ATR_MULT) if atr_now else None
        # trailing stop
        if trailing_sl and price <= trailing_sl:
            send_telegram_text(f"📉 *{symbol}* Trailing Stop hit at {price}. Exiting position.")
            update_position_status(symbol, "CLOSED")
            place_order(symbol, "SELL", 1)
            break
        # normal SL hit
        if price <= sl:
            send_telegram_text(f"🛑 *{symbol}* SL hit at {price}. Exiting position.")
            update_position_status(symbol, "CLOSED")
            place_order(symbol, "SELL", 1)
            break
        if price <= emergency_sl:
            send_telegram_text(f"⚠️ *{symbol}* Emergency SL hit at {price}. Exiting.")
            update_position_status(symbol, "CLOSED")
            place_order(symbol, "SELL", 1)
            break
        time.sleep(MON_INTERVAL)

# Flask app
app = Flask(__name__)
init_db()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status":"ok","time":datetime.utcnow().isoformat()})

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"ok":False,"error":"no json"}),400
    try:
        sym = data.get("symbol")
        entry = float(data.get("entry"))
        tp1 = float(data.get("TP1"))
        tp2 = float(data.get("TP2"))
        tp3 = float(data.get("TP3"))
        sl = float(data.get("SL"))
        emergency_sl = float(data.get("EMER_SL") or data.get("EMER_SL") or 0)
        atr = float(data.get("ATR") or 0)
        pos = {"symbol":sym,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"emergency_sl":emergency_sl,"atr":atr}
        save_position(pos)
        send_telegram_text(f"🔥 *GORANGEN PRO ALERT* - {sym}\nEntry: {entry}\nTP1: {tp1}\nTP2: {tp2}\nSL: {sl}")
        # start monitor thread
        t = threading.Thread(target=monitor_position, args=(sym, entry, tp1, tp2, tp3, sl, emergency_sl, atr), daemon=True)
        t.start()
        return jsonify({"ok":True})
    except Exception as e:
        logger.exception("Webhook processing error: %s", e)
        return jsonify({"ok":False,"error":str(e)}),500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))

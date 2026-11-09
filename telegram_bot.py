import requests
import time
import json
import hmac
import hashlib
from datetime import datetime

# --- CONFIGURATION ---
TELEGRAM_TOKEN = '9226023268:AAHLAUbT22Tk1WakZurlPzq_rPy-djdP4zo'
COINS = ['PEPEUSDT', 'WIFUSDT', 'FLOKIUSDT', 'SHIBUSDT', 'DOGEUSDT', 'SOLUSDT']

BOT_STATE = {
    "status": "Scanning",
    "active_coin": "None",
    "usdt_balance": 100.0,
    "coin_balance": 0.0,
    "start_price": 0.0,
    "stop_loss": 0.0,
    "grids": [],
    "logs": ["Bot initialized. Waiting for signal..."],
    "last_price": 0.0
}

def log_event(msg):
    print(msg)
    BOT_STATE["logs"].insert(0, msg)
    if len(BOT_STATE["logs"]) > 10:
        BOT_STATE["logs"].pop()

def get_klines(symbol, interval, limit=20):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        data = requests.get(url, timeout=5).json()
        closes = [float(candle[4]) for candle in data]
        volumes = [float(candle[5]) for candle in data]
        return closes, volumes
    except Exception:
        return None, None

def run_bot_tick():
    if BOT_STATE["status"] == "Scanning":
        for coin in COINS:
            closes, volumes = get_klines(coin, '15m')
            if not closes or len(closes) < 20: continue
                
            sma = sum(closes) / len(closes)
            avg_vol = sum(volumes[:-1]) / len(volumes[:-1])
            current_price = closes[-1]
            current_vol = volumes[-1]
            
            if current_price > sma and current_vol > (avg_vol * 1.5):
                BOT_STATE["status"] = "Trading"
                BOT_STATE["active_coin"] = coin
                BOT_STATE["start_price"] = current_price
                BOT_STATE["last_price"] = current_price
                BOT_STATE["stop_loss"] = current_price * 0.85
                step = (current_price * 1.10 - current_price * 0.90) / 5
                BOT_STATE["grids"] = [current_price * 0.90 + (i * step) for i in range(6)]
                log_event(f"[SIGNAL MET] {coin} trending up with high volume.")
                return
                
    elif BOT_STATE["status"] == "Trading":
        coin = BOT_STATE["active_coin"]
        closes, _ = get_klines(coin, '15m', limit=1)
        if not closes: return
        current_price = closes[0]
        
        if current_price <= BOT_STATE["stop_loss"]:
            BOT_STATE["status"] = "Scanning"
            log_event(f"[STOP LOSS] {coin} dropped. Grid closed.")
            return
            
        current_zone = 0
        for i in range(len(BOT_STATE["grids"]) - 1):
            if BOT_STATE["grids"][i] <= current_price <= BOT_STATE["grids"][i+1]:
                current_zone = i; break
                
        last_zone = 0
        for i in range(len(BOT_STATE["grids"]) - 1):
            if BOT_STATE["grids"][i] <= BOT_STATE["last_price"] <= BOT_STATE["grids"][i+1]:
                last_zone = i; break
                
        if current_zone < last_zone and BOT_STATE["usdt_balance"] >= 10.0:
            BOT_STATE["usdt_balance"] -= 10.0
            BOT_STATE["coin_balance"] += (10.0 / current_price)
            log_event(f"[BUY] {coin} at {current_price:.8f}")
        elif current_zone > last_zone and BOT_STATE["coin_balance"] > 0:
            BOT_STATE["usdt_balance"] += 10.0
            BOT_STATE["coin_balance"] -= (10.0 / current_price)
            log_event(f"[SELL] {coin} at {current_price:.8f}")
                
        BOT_STATE["last_price"] = current_price
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Error: {e}")

def check_telegram_messages():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=5).json()
        if response.get("ok") and response.get("result"):
            for update in response["result"]:
                if "message" in update and "text" in update["message"]:
                    chat_id = update["message"]["chat"]["id"]
                    text = update["message"]["text"]
                    update_id = update["update_id"]
                    
                    # Tell Telegram we received this message
                    requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={update_id + 1}", timeout=5)
                    
                    if text == '/status':
                        msg = f"*Status:* {BOT_STATE['status']}\n"
                        msg += f"*USDT Balance:* ${BOT_STATE['usdt_balance']:.2f}\n"
                        msg += f"*Active Coin:* {BOT_STATE['active_coin']}\n\n"
                        msg += f"*Recent Logs:*\n"
                        for log in BOT_STATE['logs'][:5]:
                            msg += f"- {log}\n"
                        send_telegram_message(chat_id, msg)
    except Exception as e:
        pass # Ignore network timeouts on mobile

print("Starting Standalone Telegram Bot...")
print("Open your Telegram app and send '/status' to your bot.")

while True:
    run_bot_tick()
    check_telegram_messages()
    time.sleep(5) # Wait 5 seconds before checking again

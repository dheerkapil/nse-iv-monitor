import requests
import json
import os
import time
from datetime import datetime

SYMBOL = "NIFTY"
THRESHOLD = 1.0
DATA_FILE = "iv_history.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def fetch_chain():
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=headers)
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={SYMBOL}"
    resp = s.get(url, headers=headers)
    return resp.json() if resp.status_code == 200 else None

def get_ivs(data):
    spot = data['records']['underlyingValue']
    strikes = {item['strikePrice']: item for item in data['records']['data']}
    strikes_list = sorted(strikes.keys())
    
    atm = min(strikes_list, key=lambda x: abs(x - spot))
    atm_iv_call = strikes[atm].get('CE', {}).get('impliedVolatility', None)
    atm_iv_put = strikes[atm].get('PE', {}).get('impliedVolatility', None)
    
    above = [s for s in strikes_list if s > atm]
    otm_calls = above[:2] if len(above) >= 2 else above[:1]
    call_ivs = []
    for s in otm_calls:
        iv = strikes[s].get('CE', {}).get('impliedVolatility', None)
        if iv is not None:
            call_ivs.append(iv)
    otm_call_iv = sum(call_ivs)/len(call_ivs) if call_ivs else None
    
    below = [s for s in strikes_list if s < atm]
    otm_puts = below[-2:] if len(below) >= 2 else below[-1:]
    put_ivs = []
    for s in otm_puts:
        iv = strikes[s].get('PE', {}).get('impliedVolatility', None)
        if iv is not None:
            put_ivs.append(iv)
    otm_put_iv = sum(put_ivs)/len(put_ivs) if put_ivs else None
    
    return spot, atm, atm_iv_call, atm_iv_put, otm_call_iv, otm_put_iv

def load_prev():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_current(record):
    with open(DATA_FILE, 'w') as f:
        json.dump(record, f, indent=2)

def main():
    print(f"{datetime.now()} - Fetching {SYMBOL}")
    data = fetch_chain()
    if not data:
        print("API failed")
        return
    
    spot, atm, atm_call, atm_put, otm_call, otm_put = get_ivs(data)
    if None in (atm_call, atm_put, otm_call, otm_put):
        print("Missing IV data")
        return
    
    now = time.time()
    curr = {
        "timestamp": now,
        "spot": spot,
        "atm_strike": atm,
        "atm_call_iv": atm_call,
        "atm_put_iv": atm_put,
        "otm_call_iv": otm_call,
        "otm_put_iv": otm_put
    }
    
    prev = load_prev()
    if prev and (now - prev["timestamp"]) <= 350:
        atm_call_delta = atm_call - prev["atm_call_iv"]
        atm_put_delta = atm_put - prev["atm_put_iv"]
        otm_call_delta = otm_call - prev["otm_call_iv"]
        otm_put_delta = otm_put - prev["otm_put_iv"]
        
        bullish = (atm_call_delta > THRESHOLD and atm_put_delta < -0.5 and
                   otm_call_delta > THRESHOLD and otm_put_delta < -0.5)
        bearish = (atm_put_delta > THRESHOLD and atm_call_delta < -0.5 and
                   otm_put_delta > THRESHOLD and otm_call_delta < -0.5)
        
        interval = int((now - prev["timestamp"]) / 60)
        if bullish:
            msg = (f"🚀 BULLISH (confirmed)\n"
                   f"{SYMBOL} Spot: {spot:.2f}\n"
                   f"ATM Strike: {atm}\n"
                   f"ATM: Call {atm_call_delta:+.1f} | Put {atm_put_delta:+.1f}\n"
                   f"OTM: Call {otm_call_delta:+.1f} | Put {otm_put_delta:+.1f}\n"
                   f"⏱ {interval} min")
            send_telegram(msg)
            print(msg)
        elif bearish:
            msg = (f"🐻 BEARISH (confirmed)\n"
                   f"{SYMBOL} Spot: {spot:.2f}\n"
                   f"ATM Strike: {atm}\n"
                   f"ATM: Call {atm_call_delta:+.1f} | Put {atm_put_delta:+.1f}\n"
                   f"OTM: Call {otm_call_delta:+.1f} | Put {otm_put_delta:+.1f}\n"
                   f"⏱ {interval} min")
            send_telegram(msg)
            print(msg)
    
    save_current(curr)

if __name__ == "__main__":
    main()

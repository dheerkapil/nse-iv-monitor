import requests
import json
import os
import time
from datetime import datetime
import csv
import subprocess

# ---------- CONFIG ----------
SYMBOL = "NIFTY"
THRESHOLD = 0.75
DATA_FILE = "iv_history.json"
SIGNALS_FILE = "signals.csv"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# ----------------------------

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def fetch_chain():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
    s = requests.Session()
    s.headers.update(headers)
    try:
        s.get("https://www.nseindia.com", timeout=10)
    except:
        pass
    url = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={SYMBOL}"
    for attempt in range(3):
        try:
            resp = s.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except:
            pass
        time.sleep(2)
    return None

def get_ivs(data):
    spot = data['underlyingValue']
    strikes_list = []
    strikes_dict = {}
    for item in data['records']['data']:
        strike = item['strikePrice']
        strikes_list.append(strike)
        strikes_dict[strike] = item
    strikes_list.sort()
    atm = min(strikes_list, key=lambda x: abs(x - spot))
    atm_iv_call = strikes_dict[atm].get('CE', {}).get('impliedVolatility', None)
    atm_iv_put = strikes_dict[atm].get('PE', {}).get('impliedVolatility', None)
    
    above = [s for s in strikes_list if s > atm]
    otm_calls = above[:2] if len(above) >= 2 else above[:1]
    call_ivs = []
    for s in otm_calls:
        iv = strikes_dict[s].get('CE', {}).get('impliedVolatility', None)
        if iv is not None:
            call_ivs.append(iv)
    otm_call_iv = sum(call_ivs)/len(call_ivs) if call_ivs else None
    
    below = [s for s in strikes_list if s < atm]
    otm_puts = below[-2:] if len(below) >= 2 else below[-1:]
    put_ivs = []
    for s in otm_puts:
        iv = strikes_dict[s].get('PE', {}).get('impliedVolatility', None)
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

def log_signal_to_csv(signal, spot, atm, atm_call_delta, atm_put_delta, otm_call_delta, otm_put_delta, interval):
    file_exists = os.path.isfile(SIGNALS_FILE)
    with open(SIGNALS_FILE, "a", newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "symbol", "signal", "spot", "atm_strike",
                             "atm_call_delta", "atm_put_delta", "otm_call_delta", "otm_put_delta", "interval_min"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), SYMBOL, signal,
                         round(spot,2), atm,
                         round(atm_call_delta,2), round(atm_put_delta,2),
                         round(otm_call_delta,2), round(otm_put_delta,2), interval])

def git_commit_and_push():
    """Commit changes to iv_history.json and signals.csv and push to GitHub"""
    try:
        subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "user.email", "github-actions@github.com"], check=True)
        subprocess.run(["git", "add", DATA_FILE, SIGNALS_FILE], check=True)
        # Only commit if there are changes
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", f"Auto-update {DATA_FILE} and {SIGNALS_FILE}"], check=True)
            subprocess.run(["git", "push"], check=True)
        else:
            print("No changes to commit")
    except Exception as e:
        print(f"Git commit/push error: {e}")

def main():
    print(f"{datetime.now()} - Fetching {SYMBOL} using v3 endpoint")
    data = fetch_chain()
    if not data or not data.get('records'):
        print("API failed or empty (market closed?)")
        return
    try:
        spot, atm, atm_call, atm_put, otm_call, otm_put = get_ivs(data)
    except Exception as e:
        print(f"Parse error: {e}")
        return
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
            msg = (f"🚀 BULLISH\n{SYMBOL} Spot: {spot:.2f}\nATM Strike: {atm}\n"
                   f"ATM: Call {atm_call_delta:+.1f} | Put {atm_put_delta:+.1f}\n"
                   f"OTM: Call {otm_call_delta:+.1f} | Put {otm_put_delta:+.1f}\n"
                   f"⏱ {interval} min")
            send_telegram(msg)
            log_signal_to_csv("BULLISH", spot, atm, atm_call_delta, atm_put_delta,
                              otm_call_delta, otm_put_delta, interval)
            print(msg)
        elif bearish:
            msg = (f"🐻 BEARISH\n{SYMBOL} Spot: {spot:.2f}\nATM Strike: {atm}\n"
                   f"ATM: Call {atm_call_delta:+.1f} | Put {atm_put_delta:+.1f}\n"
                   f"OTM: Call {otm_call_delta:+.1f} | Put {otm_put_delta:+.1f}\n"
                   f"⏱ {interval} min")
            send_telegram(msg)
            log_signal_to_csv("BEARISH", spot, atm, atm_call_delta, atm_put_delta,
                              otm_call_delta, otm_put_delta, interval)
            print(msg)
    
    save_current(curr)
    # Commit and push after each run to persist state
    git_commit_and_push()

if __name__ == "__main__":
    main()

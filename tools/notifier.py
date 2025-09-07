#!/usr/bin/env python3
# Telegram notifier tối giản (không cần thư viện ngoài)
import os, json, hashlib, time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen, Request

TZ = os.environ.get("TZ", "Asia/Bangkok")
TG_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT  = os.environ.get("TG_CHAT_ID", "")
QUIET    = os.environ.get("TG_QUIET_HOURS", "00-07")  # ví dụ: 00-07
STATE    = "data/.noti_state.json"
MACRO    = "data/macro_bias.json"

def local_ts():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def in_quiet_hours():
    try:
        a,b = QUIET.split("-")
        h = int(datetime.now().astimezone().strftime("%H"))
        lo, hi = int(a), int(b)
        return lo <= h < hi
    except: return False

def send_tg(text, force=False):
    if not TG_TOKEN or not TG_CHAT:
        return False, "TG env missing"
    if in_quiet_hours() and (not force):
        return False, "quiet_hours"
    data = {
        "chat_id": TG_CHAT,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    req = Request(url, data=urlencode(data).encode("utf-8"))
    with urlopen(req, timeout=10) as r:
        ok = (r.getcode() == 200)
    return ok, "sent"

def load_state():
    try: return json.load(open(STATE))
    except: return {}

def save_state(s):
    os.makedirs("data", exist_ok=True)
    json.dump(s, open(STATE,"w"), indent=2, ensure_ascii=False)

def dedupe(text, window_sec=600):
    s = load_state()
    h = hashlib.sha1(text.encode()).hexdigest()
    now = int(time.time())
    if s.get("last_hash")==h and now - int(s.get("last_ts",0)) < window_sec:
        return True
    s["last_hash"], s["last_ts"] = h, now
    save_state(s)
    return False

def macro_event():
    try:
        cur = json.load(open(MACRO))
    except: 
        return
    s = load_state()
    prev = s.get("macro_prev")
    chg = []
    if prev:
        for k in ("macro_bias_3m","macro_bias_6m"):
            if cur.get(k)!=prev.get(k):
                chg.append(f"{k}: {prev.get(k,'?')} → *{cur.get(k)}*")
        if abs(float(cur.get("macro_conf",0))-float(prev.get("macro_conf",0)))>=0.10:
            chg.append(f"macro_conf: {prev.get('macro_conf',0):.2f} → *{cur.get('macro_conf',0):.2f}*")
    else:
        chg.append("Khởi tạo macro bias.")

    if chg:
        text = ("🧭 *SOUL-MACRO cập nhật*\n"
                f"ts: `{cur.get('ts')}`\n" +
                "\n".join(f"• {x}" for x in chg))
        if not dedupe(text):
            send_tg(text)
        s["macro_prev"] = cur
        save_state(s)

def boot_event():
    text = f"✅ *CrX PhaseB Loop khởi động* • ts `{local_ts()}`"
    if not dedupe(text, window_sec=60): send_tg(text, force=True)

if __name__=="__main__":
    os.makedirs("data", exist_ok=True)
    # gọi theo từng lần trong run_loop.sh
    boot = os.environ.get("CRX_BOOT_NOTI","")
    if boot: boot_event()
    macro_event()
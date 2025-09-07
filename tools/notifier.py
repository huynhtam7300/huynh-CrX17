#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notifier tối giản cho Telegram (không cần thư viện ngoài).
Tính năng:
- TG_ENABLE=1 mới gửi; mặc định 0 (tắt).
- TG_BOOT_NOTI=1 thì gửi 1 tin khi service khởi động (chống trùng bằng TTL).
- TG_QUIET_HOURS=HH-HH (vd: 00-07) để im lặng ngoài giờ; đặt "none" để tắt.
- Rate-limit/khử trùng theo key.
- Alias biến môi trường TELEGRAM_* cũng được nhận.
"""

import os, json, time, hashlib
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen, Request

# ---- Env & default ----
def env(key, default=""):
    v = os.environ.get(key)
    if v is None:
        # alias TELEGRAM_* -> TG_*
        if key.startswith("TG_"):
            v = os.environ.get("TELEGRAM_" + key[3:], default)
        else:
            v = default
    return str(v)

TG_ENABLE        = env("TG_ENABLE", "0")           # 0=tắt, 1=bật
TG_TOKEN         = env("TG_BOT_TOKEN", "")
TG_CHAT          = env("TG_CHAT_ID", "")
TG_QUIET         = env("TG_QUIET_HOURS", "none")   # "none" hoặc "00-07"
BOOT_FLAG        = env("CRX_BOOT_NOTI", "")        # do run_loop đặt tạm khi cần
RATE_LIMIT_SEC   = int(env("TG_RATE_LIMIT_SEC", "600"))
STATE_PATH       = "data/.noti_state.json"
MACRO_JSON       = "data/macro_bias.json"

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def quiet_hours():
    if TG_QUIET.lower() == "none": return False
    try:
        lo, hi = [int(x) for x in TG_QUIET.split("-")]
        h = int(datetime.now().astimezone().strftime("%H"))
        return lo <= h < hi
    except:
        return False

def load_state():
    try:
        return json.load(open(STATE_PATH, "r", encoding="utf-8"))
    except:
        return {}

def save_state(s):
    os.makedirs("data", exist_ok=True)
    json.dump(s, open(STATE_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

def dedupe(key: str, ttl: int) -> bool:
    """Trả về True nếu nên BỎ QUA (đã gửi gần đây)."""
    s = load_state()
    d = s.get("dedupe", {})
    now = int(time.time())
    last = int(d.get(key, 0))
    if now - last < ttl:
        return True
    d[key] = now
    s["dedupe"] = d
    save_state(s)
    return False

def send_tg(text: str, force=False):
    if TG_ENABLE != "1":
        return False, "disabled"
    if (not force) and quiet_hours():
        return False, "quiet"
    if not TG_TOKEN or not TG_CHAT:
        return False, "missing_token_or_chat"

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

# ---- Events ----
def boot_event():
    # Chống trùng theo key cố định "boot" với TTL 10 phút
    if dedupe("boot", 600):
        return
    text = f"✅ *CrX PhaseB Loop khởi động*\n`{now_iso()}`"
    send_tg(text, force=True)

def macro_event():
    try:
        cur = json.load(open(MACRO_JSON, "r", encoding="utf-8"))
    except:
        return
    s = load_state()
    prev = s.get("macro_prev")
    changes = []
    if prev:
        for k in ("macro_bias_3m", "macro_bias_6m"):
            if cur.get(k) != prev.get(k):
                changes.append(f"{k}: {prev.get(k, '?')} → *{cur.get(k)}*")
        try:
            if abs(float(cur.get("macro_conf", 0)) - float(prev.get("macro_conf", 0))) >= 0.10:
                changes.append(f"macro_conf: {float(prev.get('macro_conf',0)):.2f} → *{float(cur.get('macro_conf',0)):.2f}*")
        except Exception:
            pass
    else:
        changes.append("Khởi tạo macro bias.")

    if changes:
        # Khử trùng theo hash nội dung thay đổi (TTL mặc định)
        key = "macro:" + hashlib.sha1("\n".join(changes).encode()).hexdigest()
        if not dedupe(key, RATE_LIMIT_SEC):
            text = "🧭 *SOUL-MACRO cập nhật*\n" + "\n".join(f"• {x}" for x in changes) + f"\n`ts: {cur.get('ts','-')}`"
            send_tg(text)
        s["macro_prev"] = cur
        save_state(s)

if __name__ == "__main__":
    # Gửi boot nếu được yêu cầu (do run_loop bật lúc start)
    if BOOT_FLAG:
        boot_event()
    # Gửi macro nếu có thay đổi
    macro_event()
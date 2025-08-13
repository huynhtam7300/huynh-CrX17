# tools/anomaly_watcher.py
# -*- coding: utf-8 -*-
import time, json, os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Dùng notifier sẵn có của bạn
from notifier.notify_telegram import send_telegram_message

JSON_PATH = "data/decision_history.json"
INTERVAL_SEC = 60  # kiểm tra mỗi 60s
# Ngưỡng cảnh báo
THRESHOLDS = {
    "funding_abs": 0.003,   # |funding_rate| > 0.003
    "bandit_min": 0.5,      # bandit_factor < 0.5
    "conf_min":   0.2,      # confidence < 0.2
}

_last_alert_sig = None  # tránh spam khi bản ghi không đổi

def load_last_record(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path): return None
    try:
        data = json.load(open(path, "r", encoding="utf-8"))
        if isinstance(data, list) and data:
            return data[-1]
    except Exception:
        return None
    return None

def fmt_ts():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def main():
    global _last_alert_sig
    print(f"🔎 anomaly_watcher start… watching {JSON_PATH} every {INTERVAL_SEC}s")
    while True:
        rec = load_last_record(JSON_PATH)
        if rec:
            sig = rec.get("timestamp")
            triggered = []

            # funding
            fr = rec.get("funding_rate")
            if isinstance(fr, (int,float)) and abs(fr) > THRESHOLDS["funding_abs"]:
                triggered.append(f"Funding rate bất thường: {fr:.6f}")

            # bandit
            bf = rec.get("bandit_factor")
            if isinstance(bf, (int,float)) and bf < THRESHOLDS["bandit_min"]:
                triggered.append(f"Bandit factor thấp: {bf:.3f}")

            # confidence
            cf = rec.get("confidence")
            if isinstance(cf, (int,float)) and cf < THRESHOLDS["conf_min"]:
                triggered.append(f"Confidence thấp: {cf:.2f}")

            if triggered and sig != _last_alert_sig:
                msg = (
                    "🚨 *CRX ANOMALY ALERT*\n"
                    f"- time: `{sig}`\n"
                    f"- decision: `{rec.get('decision')}`\n"
                    + "\n".join([f"- {t}" for t in triggered])
                )
                try:
                    send_telegram_message(msg)
                    print(f"[{fmt_ts()}] sent alert for {sig}")
                    _last_alert_sig = sig
                except Exception as e:
                    print(f"[{fmt_ts()}] send_telegram_message error: {e}")

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
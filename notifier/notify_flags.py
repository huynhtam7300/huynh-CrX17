# -*- coding: utf-8 -*-
"""
Gửi Telegram khi cờ điều khiển thay đổi (MarkdownV2 tiếng Việt).
- Theo dõi: reload.flag, stop.flag, riskoff.flag
- Lưu trạng thái: .runner.lock/notify_state.json -> flags
"""
from __future__ import annotations
import os, json, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

from notifier.notify_telegram import send_telegram_message

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".runner.lock"; LOCK.mkdir(exist_ok=True)
STATE_FILE = LOCK / "notify_state.json"

FLAG_DIR = Path(os.getenv("CRX_FLAG_DIR", str(ROOT))).resolve()
RELOAD = FLAG_DIR / "reload.flag"
STOP   = FLAG_DIR / "stop.flag"
RISK   = FLAG_DIR / "riskoff.flag"

MDV2 = r"_*\[\]()~`>#+\-=|{}.!\\"
def esc(x: object) -> str:
    return re.sub(rf"([{MDV2}])", r"\\\1", str(x))

def _load_state() -> dict:
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}

def _save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

def _status(p: Path) -> str:
    return "BẬT" if p.exists() else "TẮT"

def main():
    st = _load_state()
    prev = st.get("flags", {})
    cur = {"reload": _status(RELOAD), "stop": _status(STOP), "riskoff": _status(RISK)}

    if cur != prev:
        msg = [
            "🔔 *Cập nhật cờ chạy*",
            f"• reload: *{esc(cur['reload'])}*",
            f"• tạm dừng: *{esc(cur['stop'])}*",
            f"• risk off: *{esc(cur['riskoff'])}*",
            "_tự động thông báo_",
        ]
        ok = send_telegram_message("\n".join(msg), parse_mode="MarkdownV2")
        if ok:
            st["flags"] = cur
            _save_state(st)
        else:
            print("[notify_flags] Gửi Telegram thất bại.")
    else:
        print("[notify_flags] Không có thay đổi flags.")

if __name__ == "__main__":
    main()
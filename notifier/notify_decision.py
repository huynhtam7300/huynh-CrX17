# -*- coding: utf-8 -*-
"""
Gửi thông báo Telegram khi có quyết định mới (MarkdownV2 tiếng Việt, escape an toàn).
- Đọc: data/decision_history.json (list hoặc NDJSON)
- Lưu mốc: .runner.lock/notify_state.json -> last_ts
ENV: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (hoặc TELEGRAM_USER_ID)
"""
from __future__ import annotations
import os, json, re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(override=True)

from notifier.notify_telegram import send_telegram_message

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA_FILE = DATA / "decision_history.json"
LOCK = ROOT / ".runner.lock"; LOCK.mkdir(exist_ok=True)
STATE_FILE = LOCK / "notify_state.json"

# Các ký tự phải escape theo MarkdownV2
MDV2 = r"_*\[\]()~`>#+\-=|{}.!\\"

def esc(x: object) -> str:
    """Escape cho MarkdownV2 đối với CHUỖI thông thường."""
    return re.sub(rf"([{MDV2}])", r"\\\1", str(x))

def fnum(x, n=2) -> str:
    """Định dạng số và ESCAPE luôn (để xử lý dấu .)."""
    try:
        s = f"{float(x):.{n}f}"
    except Exception:
        s = str(x)
    return esc(s)

def _read_decisions() -> list[dict]:
    if not DATA_FILE.exists(): return []
    raw = DATA_FILE.read_text(encoding="utf-8", errors="ignore")
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, list) else [obj]
    except Exception:
        # NDJSON fallback
        rows = []
        for line in raw.splitlines():
            line = line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except Exception: pass
        return rows

def _load_state() -> dict:
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}

def _save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

def _join_list(d: dict, key: str) -> str:
    arr = d.get(key) or []
    return esc("; ".join(map(str, arr))[:220])

def format_vn(d: dict) -> str:
    # thời gian (không escape vì đặt trong `code`)
    ts_raw = d.get("timestamp") or d.get("time") or ""
    try:
        ts_fmt = datetime.fromisoformat(ts_raw.replace("Z","+00:00")).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        ts_fmt = ts_raw

    decision    = esc(d.get("decision","N/A"))
    meta_action = esc(d.get("meta_action",""))

    conf = d.get("confidence"); er = d.get("er"); risk = d.get("risk")
    size_meta = d.get("suggested_size"); size_bandit = d.get("suggested_size_bandit"); size_funding = d.get("suggested_size_funding")
    bandit_factor = d.get("bandit_factor"); funding_rate = d.get("funding_rate")

    lines = []
    lines.append("🧠 *CrX – Quyết định mới*")
    lines.append(f"⏱ `{ts_fmt}`")  # trong code -> không escape

    if meta_action:
        lines.append(f"➡️ Hành động: *{decision}*  •  Meta: *{meta_action}*")
    else:
        lines.append(f"➡️ Hành động: *{decision}*")

    stat = []
    if conf is not None: stat.append(f"Độ tin cậy: {fnum(conf,2)}")
    if er   is not None: stat.append(f"ER: {fnum(er,2)}")
    if risk is not None: stat.append(f"Rủi ro: {fnum(risk,2)}")
    if stat: lines.append("• " + "  •  ".join(stat))

    sizes = []
    if size_meta    is not None: sizes.append(f"meta: {fnum(size_meta,3)}")
    if size_bandit  is not None: sizes.append(f"bandit: {fnum(size_bandit,3)}")
    if size_funding is not None: sizes.append(f"funding: {fnum(size_funding,3)}")
    if sizes: lines.append("• Kích thước: " + ", ".join(sizes))

    extras = []
    if bandit_factor is not None: extras.append(f"hệ số bandit: {fnum(bandit_factor,3)}")
    if funding_rate  is not None: extras.append(f"lãi suất funding: {fnum(funding_rate,6)}")
    if extras: lines.append("• Thêm: " + ", ".join(extras))

    if d.get("reasons"):        lines.append("• Lý do: "     + _join_list(d, "reasons"))
    if d.get("meta_reason"):    lines.append("• Meta: "       + _join_list(d, "meta_reason"))
    if d.get("bandit_reason"):  lines.append("• Bandit: "     + _join_list(d, "bandit_reason"))
    if d.get("funding_reason"): lines.append("• Funding: "    + _join_list(d, "funding_reason"))
    if d.get("kpi_note"):       lines.append("• KPI: "        + _join_list(d, "kpi_note"))

    lines.append("_tự động thông báo_")
    return "\n".join(lines)

def main(force: bool=False) -> int:
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_USER_ID")):
        print("[notify] Thiếu TELEGRAM_BOT_TOKEN/CHAT_ID trong .env"); return 1

    rows = _read_decisions()
    if not rows:
        print("[notify] Không có dữ liệu quyết định."); return 0

    rows.sort(key=lambda r: r.get("timestamp") or r.get("time") or "", reverse=True)
    newest = rows[0]
    ts_new = newest.get("timestamp") or newest.get("time") or ""

    st = _load_state()
    if not force and st.get("last_ts") == ts_new:
        print("[notify] Chưa có bản ghi mới để gửi."); return 0

    msg = format_vn(newest)
    ok = send_telegram_message(msg, parse_mode="MarkdownV2")
    if ok:
        print("[notify] Đã gửi Telegram.")
        st["last_ts"] = ts_new
        _save_state(st); return 0
    else:
        print("[notify] Gửi Telegram thất bại."); return 2

if __name__ == "__main__":
    import sys
    sys.exit(main(force="--force" in sys.argv))
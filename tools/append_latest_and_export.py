# tools/append_latest_and_export.py
# v1.1 – Gate theo floor + ép symbol để tránh sym=None

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Ngưỡng Phase B (đừng hạ ngưỡng – theo policy)
OPEN_FLOOR = float(os.getenv("CRX_OPEN_CONF_FLOOR", "0.65"))
CLOSE_FLOOR = float(os.getenv("CRX_CLOSE_CONF_FLOOR", "0.60"))
DEFAULT_SYMBOL = os.getenv("CRX_DEFAULT_SYMBOL", "BTCUSDT")

# Các ứng viên nguồn quyết định (thô) – ưu tiên theo thứ tự
CANDIDATE_INPUTS = [
    DATA / "left_decision_raw.json",
    DATA / "left_decision.json",
    DATA / "decision.json",
    ROOT / "decision.json",
]

LAST_DECISION = ROOT / "last_decision.json"
PREVIEW_DECISION = ROOT / "last_decision_preview.json"
EXECUTOR_STATE = ROOT / "executor_state.json"  # để lấy symbol fallback nếu có

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def read_json(path: Path):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[export] WARN: không đọc được {path}: {e}")
    return None

def write_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"[export] ✅ Đã ghi {path}")

def pick_input():
    for p in CANDIDATE_INPUTS:
        if p.exists():
            print(f"[export] Nguồn quyết định: {p}")
            return p
    print("[export] WARN: Không tìm thấy file quyết định thô. Bỏ qua.")
    return None

def ensure_symbol(dec: dict) -> str:
    # Ưu tiên trong chính quyết định
    sym = dec.get("symbol") or dec.get("pair") or dec.get("asset")
    if sym and isinstance(sym, str):
        return sym

    # Thử từ trạng thái executor (nếu đã từng giao dịch)
    st = read_json(EXECUTOR_STATE)
    if st and isinstance(st, dict):
        sym2 = st.get("symbol") or st.get("pair")
        if sym2 and isinstance(sym2, str):
            return sym2

    # Cuối cùng lấy từ ENV
    return DEFAULT_SYMBOL

def is_close_or_flip(dec: dict) -> bool:
    # Tùy hệ thống, meta_action có thể là CLOSE/FLIP; nếu không có, suy luận thô
    meta = (dec.get("meta_action") or "").upper()
    if any(k in meta for k in ("CLOSE", "FLIP")):
        return True
    # Nếu có trường 'decision' dạng CLOSE_* hoặc FLIP_*
    d = (dec.get("decision") or "").upper()
    return d.startswith("CLOSE") or d.startswith("FLIP")

def main():
    src = pick_input()
    if not src:
        return

    dec = read_json(src)
    if not isinstance(dec, dict):
        print(f"[export] WARN: {src} không phải JSON object. Bỏ qua.")
        return

    # Chuẩn hoá trường tối thiểu
    dec.setdefault("timestamp", now_utc())
    dec["symbol"] = ensure_symbol(dec)

    # Gate theo floor
    conf = float(dec.get("confidence") or 0.0)
    is_closeflip = is_close_or_flip(dec)

    allow = False
    reason = ""
    if is_closeflip:
        allow = conf >= CLOSE_FLOOR
        reason = f"close/flip floor={CLOSE_FLOOR}"
    else:
        # Mặc định coi BUY/SELL là mở/đi theo hướng, gate theo OPEN_FLOOR
        allow = conf >= OPEN_FLOOR
        reason = f"open floor={OPEN_FLOOR}"

    if allow:
        write_json(LAST_DECISION, dec)
        # Ghi thêm bản sao để tiện trace
        dec2 = dict(dec)
        dec2["export_note"] = f"exported_at={now_utc()} reason={reason}"
        write_json(PREVIEW_DECISION, dec2)
        print(f"[export] PASS gate ({reason}); confidence={conf:.2f}; symbol={dec['symbol']}")
    else:
        # Không đạt floor -> chỉ ghi bản preview (tham khảo)
        dec2 = dict(dec)
        dec2["simulate"] = True
        dec2["export_note"] = f"blocked_at={now_utc()} reason={reason}"
        write_json(PREVIEW_DECISION, dec2)
        if LAST_DECISION.exists():
            print("[export] INFO: Giữ nguyên last_decision.json hiện tại (không ghi đè).")
        print(f"[export] BLOCK gate ({reason}); confidence={conf:.2f}; symbol={dec['symbol']}")

if __name__ == "__main__":
    main()
# tools/append_latest_and_export.py
# v1.3 – Gate theo floor + ép symbol + đảm bảo .env luôn override process env

import os, json
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# ÉP dùng .env ở repo và override mọi biến có sẵn trong process
load_dotenv(dotenv_path=ROOT / ".env", override=True)

DATA = ROOT / "data"

OPEN_FLOOR  = float(os.getenv("CRX_OPEN_CONF_FLOOR", "0.65"))
CLOSE_FLOOR = float(os.getenv("CRX_CLOSE_CONF_FLOOR", "0.60"))
DEFAULT_SYMBOL = os.getenv("CRX_DEFAULT_SYMBOL", "BTCUSDT")

CANDIDATE_INPUTS = [
    DATA / "left_decision_raw.json",
    DATA / "left_decision.json",
    DATA / "decision.json",
    ROOT / "decision.json",
    ROOT / "last_decision.json",
]

LAST_DECISION = ROOT / "last_decision.json"
PREVIEW_DECISION = ROOT / "last_decision_preview.json"
EXECUTOR_STATE = ROOT / "executor_state.json"

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def read_json(p: Path):
    try:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[export] WARN: không đọc được {p}: {e}")
    return None

def write_json(p: Path, obj: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"[export] ✅ Đã ghi {p}")

def pick_input():
    for p in CANDIDATE_INPUTS:
        if p.exists():
            print(f"[export] Nguồn quyết định: {p}")
            return p
    print("[export] WARN: Không tìm thấy file quyết định thô. Bỏ qua.")
    return None

def ensure_symbol(dec: dict) -> str:
    sym = dec.get("symbol") or dec.get("pair") or dec.get("asset")
    if isinstance(sym, str) and sym.strip():
        return sym.strip()
    st = read_json(EXECUTOR_STATE) or {}
    sym2 = st.get("symbol") or st.get("pair")
    if isinstance(sym2, str) and sym2.strip():
        return sym2.strip()
    return DEFAULT_SYMBOL

def is_close_or_flip(dec: dict) -> bool:
    meta = (dec.get("meta_action") or "").upper()
    if any(k in meta for k in ("CLOSE", "FLIP")):
        return True
    d = (dec.get("decision") or "").upper()
    return d.startswith("CLOSE") or d.startswith("FLIP")

def main():
    src = pick_input()
    if not src:
        return

    dec = read_json(src)
    if not isinstance(dec, dict):
        print(f"[export] WARN: {src} không phải JSON object.")
        return

    dec.setdefault("timestamp", now_utc())
    dec["symbol"] = ensure_symbol(dec)
    conf = float(dec.get("confidence") or 0.0)
    is_cf = is_close_or_flip(dec)

    floor = CLOSE_FLOOR if is_cf else OPEN_FLOOR
    reason = f"{'close/flip' if is_cf else 'open'} floor={floor}"

    if conf >= floor:
        write_json(LAST_DECISION, dec)
        dec2 = dict(dec)
        dec2["export_note"] = f"exported_at={now_utc()} reason={reason}"
        write_json(PREVIEW_DECISION, dec2)
        print(f"[export] PASS gate ({reason}); confidence={conf:.2f}; symbol={dec['symbol']}")
    else:
        dec2 = dict(dec)
        dec2["simulate"] = True
        dec2["export_note"] = f"blocked_at={now_utc()} reason={reason}"
        write_json(PREVIEW_DECISION, dec2)
        if src.samefile(LAST_DECISION):
            try:
                LAST_DECISION.unlink(missing_ok=True)
                print("[export] BLOCK: đã xoá last_decision.json để tránh Executor đọc dưới ngưỡng.")
            except Exception as e:
                print(f"[export] WARN: không xoá được last_decision.json: {e}")
        else:
            print("[export] INFO: Giữ nguyên last_decision.json hiện tại (nếu có).")
        print(f"[export] BLOCK gate ({reason}); confidence={conf:.2f}; symbol={dec['symbol']}")

if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
# core/decision/decision_maker.py
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import pandas as pd

from core.analyzer.technical_analyzer import analyze
from core.risk.risk_intel import atr_percent
from utils.io_utils import read_json

DATA_DIR = Path("data")
HISTORY_FILE = DATA_DIR / "decision_history.json"
BTC_FILE = DATA_DIR / "btc_candles.json"   # records: [{time,open,high,low,close,volume}, ...]

# ========== Helpers ==========
def utc_now_iso():
    # ISO kèm timezone +00:00
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def load_df(path: Path) -> pd.DataFrame:
    """
    Đọc nến ở cả 2 định dạng:
      - list bản ghi: [{...}]
      - dict-cột: {"open":[...],...} (fallback)
    Trả về DataFrame gồm: time (nếu có), open, high, low, close, volume
    """
    obj = read_json(path, default={"open":[],"high":[],"low":[],"close":[],"volume":[]})
    if isinstance(obj, list):
        df = pd.DataFrame(obj)
    else:
        df = pd.DataFrame(obj)
    # chuẩn hoá kiểu số
    for c in ["open","high","low","close","volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # chuẩn hoá time (nếu có)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    keep = [c for c in ["time","open","high","low","close","volume"] if c in df.columns]
    df = df[keep].dropna().reset_index(drop=True)
    return df

def minutes_to_next_funding(now_utc: datetime) -> float:
    """
    Binance funding mỗi 8h tại mốc 00:00, 08:00, 16:00 UTC.
    Trả về số phút còn lại tới mốc funding kế tiếp.
    """
    base = now_utc.replace(minute=0, second=0, microsecond=0)
    hours = base.hour
    next_hour_block = ((hours // 8) + 1) * 8
    if next_hour_block >= 24:
        # sang ngày hôm sau
        next_ts = base.replace(hour=0) + timedelta(days=1)
    else:
        next_ts = base.replace(hour=next_hour_block)
    return (next_ts - now_utc).total_seconds() / 60.0

def atomic_write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

# ========== Core ==========
def build_decision_record(btc: pd.DataFrame) -> dict:
    """
    Tạo bản ghi quyết định đầy đủ, gồm meta/bandit/funding, sẵn sàng append vào history.
    """
    # 1) Tín hiệu cơ bản
    sig = analyze(btc)  # mong đợi có: decision, confidence, er, risk?, reasons
    risk_atr_pct = atr_percent(btc)         # % ATR
    sig["risk"] = max(float(sig.get("risk", 0.0)), risk_atr_pct / 100.0)

    # 2) Kích thước đề xuất cơ bản (tạm thời cố định 0.2 như trước)
    suggested_size = 0.2

    # 3) Funding (minh hoạ: lấy rate giả định 0.0001 & mins_left chuẩn theo mốc 8h)
    now = datetime.now(timezone.utc)
    mins_left = round(minutes_to_next_funding(now), 1)
    funding_rate = 0.0001  # nếu sau này có API funding, thay tại đây

    # 4) Bandit (hiện tại cold-start)
    bandit_factor = 1.0
    bandit_reason = ["cold_start", "no_rewards"]

    # 5) Gộp bản ghi
    rec = {
        "timestamp": utc_now_iso(),
        "decision": sig.get("decision", "WAIT"),
        "confidence": float(sig.get("confidence", 0.0)),
        "er": float(sig.get("er", 0.0)),
        "risk": float(sig.get("risk", 0.0)),
        "reasons": list(sig.get("reasons", [])),

        # Meta & size
        "meta_action": sig.get("decision", "WAIT"),
        "suggested_size": suggested_size,
        "suggested_size_bandit": round(suggested_size * bandit_factor, 3),
        "suggested_size_funding": suggested_size,  # hiện funding chưa scale size

        "meta_reason": [
            f"atr_pct={risk_atr_pct:.2f}",
            "regime=unknown",
            "kpi_factor=1.0",
        ],

        # Bandit
        "bandit_reason": bandit_reason,
        "bandit_factor": bandit_factor,

        # Funding
        "funding_reason": [f"rate={funding_rate:.6f}", f"mins_left={mins_left:.1f}"],
        "funding_rate": funding_rate,

        # KPI note (để khớp các bản ghi trước)
        "kpi_note": ["kpi_enabled"],
    }
    return rec

def append_history(rec: dict):
    try:
        hist = read_json(HISTORY_FILE, default=[])
        if not isinstance(hist, list):
            hist = []
    except Exception:
        hist = []
    hist.append(rec)
    atomic_write_json(HISTORY_FILE, hist)

def run_decision() -> dict:
    btc = load_df(BTC_FILE)
    if btc.empty or len(btc) < 50:
        return {
            "decision": "WAIT",
            "confidence": 0.0,
            "er": 0.0,
            "risk": 0.0,
            "reasons": ["insufficient_data"],
        }
    rec = build_decision_record(btc)
    append_history(rec)
    return rec

# Cho phép chạy trực tiếp: python -m core.decision.decision_maker
def main():
    rec = run_decision()
    print("[decision] record:", json.dumps(rec, ensure_ascii=False))

if __name__ == "__main__":
    main()
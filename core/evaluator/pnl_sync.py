# -*- coding: utf-8 -*-
"""
Đồng bộ PnL đã chốt (REALIZED_PNL) từ Binance Futures về file local cho dashboard.
- Đầu ra:
  data/pnl_summary.json:
    {
      "updated_at": "...",
      "range_days": 30,
      "total_trades": 12,
      "wins": 7,
      "losses": 5,
      "realized_pnl_sum": 1.2345,
      "avg_pnl_per_trade": 0.1029,
      "last_trade_time": "2025-08-12T16:31:04+00:00"
    }
ENV:
  BINANCE_API_KEY, BINANCE_API_SECRET  (bắt buộc)
  BINANCE_FAPI_BASE (mặc định testnet: https://testnet.binancefuture.com)
  CRX_PNL_SYNC_DAYS (mặc định 30)
"""

from __future__ import annotations
import os, time, json, hmac, hashlib, requests
from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]  # .../core/evaluator -> repo root
DATA = ROOT / "data"; DATA.mkdir(exist_ok=True)
OUT_FILE = DATA / "pnl_summary.json"
RAW_FILE = DATA / "pnl_income_raw.json"

API_KEY    = (os.getenv("BINANCE_API_KEY") or "").strip()
API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
BASE       = (os.getenv("BINANCE_FAPI_BASE") or "https://testnet.binancefuture.com").strip()
DAYS       = int(os.getenv("CRX_PNL_SYNC_DAYS", "30"))
RECV       = int(os.getenv("BINANCE_RECVWINDOW", "5000"))

if not API_KEY or not API_SECRET:
    print("[pnl_sync] ❌ Thiếu BINANCE_API_KEY/BINANCE_API_SECRET trong .env")
    raise SystemExit(1)

def _ts(): return int(time.time() * 1000)
def _headers(): return {"X-MBX-APIKEY": API_KEY}
def _sign(params: dict) -> str:
    q = urlencode(params, doseq=True)
    sig = hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    return f"{q}&signature={sig}"

def _get_signed(path: str, params: dict):
    params = dict(params or {})
    params.update({"timestamp": _ts(), "recvWindow": RECV})
    url = f"{BASE}{path}?{_sign(params)}"
    r = requests.get(url, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()

def iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc).isoformat()

def fetch_income_realized_pnl(days: int) -> list[dict]:
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    end_ms   = _ts()
    out = []
    cursor = start_ms
    limit = 1000
    while True:
        data = _get_signed("/fapi/v1/income", {
            "incomeType": "REALIZED_PNL",
            "startTime": cursor,
            "endTime": end_ms,
            "limit": limit
        })
        if not data:
            break
        out.extend(data)
        # tăng con trỏ để tránh trùng
        cursor = max(int(d["time"]) for d in data) + 1
        if len(data) < limit:
            break
        time.sleep(0.2)
    return out

def summarize(incomes: list[dict]) -> dict:
    total = 0.0
    wins = 0
    losses = 0
    last_ms = None
    for it in incomes:
        try:
            val = float(it.get("income", 0) or 0)
        except Exception:
            continue
        total += val
        if val > 0:
            wins += 1
        elif val < 0:
            losses += 1
        t = int(it.get("time", 0) or 0)
        if not last_ms or t > last_ms:
            last_ms = t

    trades = wins + losses
    avg = (total / trades) if trades else 0.0
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "range_days": DAYS,
        "total_trades": trades,
        "wins": wins,
        "losses": losses,
        "realized_pnl_sum": round(total, 6),
        "avg_pnl_per_trade": round(avg, 6),
        "last_trade_time": iso_utc(last_ms) if last_ms else None,
    }

def main():
    print(f"[pnl_sync] Base={BASE} | days={DAYS}")
    incomes = fetch_income_realized_pnl(DAYS)
    RAW_FILE.write_text(json.dumps(incomes, ensure_ascii=False, indent=2), encoding="utf-8")
    sm = summarize(incomes)
    OUT_FILE.write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[pnl_sync] ✅ Đã cập nhật {OUT_FILE.name}: {sm}")

if __name__ == "__main__":
    main()
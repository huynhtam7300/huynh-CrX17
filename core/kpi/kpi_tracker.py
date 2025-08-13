# core/kpi/kpi_tracker.py
from pathlib import Path
from typing import Dict, Tuple, List
from datetime import datetime, timezone, timedelta
import json
from configs.config import KPI_POLICY
from utils.io_utils import read_json

TRADE_PATH = Path("data/trade_history.json")

def _load_trades() -> List[Dict]:
    return read_json(TRADE_PATH, [])

def _week_range_utc(dt: datetime) -> Tuple[datetime, datetime]:
    # tuần ISO: bắt đầu thứ Hai 00:00 UTC
    start = (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return start, end

def _pnl_usd_estimate(trades: List[Dict]) -> float:
    """
    Ước tính PnL bằng cách ghép cặp 2 lệnh liên tiếp ngược hướng cùng symbol:
    long -> sell / short -> buy. Không dùng phí/funding (Phase A).
    """
    pnl = 0.0
    last_pos = {}  # symbol -> (side, price, qty)
    for t in trades:
        if t.get("status") != "FILLED": 
            continue
        sym = t.get("symbol")
        side = t.get("side")
        qty = float(t.get("cumQty", "0") or 0)
        price = float(t.get("avgPrice", "0") or 0)
        if qty <= 0 or price <= 0: 
            continue

        if sym in last_pos:
            ps, pp, pq = last_pos[sym]
            # Nếu đảo chiều hoặc đóng vị thế
            if (ps == "BUY" and side == "SELL") or (ps == "SELL" and side == "BUY"):
                # PnL = (exit - entry) * qty (BUY) ; (entry - exit) * qty (SELL)
                if ps == "BUY":
                    pnl += (price - pp) * min(pq, qty)
                else:
                    pnl += (pp - price) * min(pq, qty)
                last_pos.pop(sym, None)  # đóng vị thế
            else:
                # cùng hướng → gộp (đơn giản)
                new_qty = pq + qty
                new_price = (pp * pq + price * qty) / new_qty
                last_pos[sym] = (ps, new_price, new_qty)
        else:
            last_pos[sym] = (side, price, qty)
    return float(pnl)

def weekly_status() -> Dict:
    trades = _load_trades()
    if not trades:
        return {"achieved": False, "pnl_usd": 0.0, "target": KPI_POLICY.get("weekly", {}).get("min_target_usd", 50)}

    now = datetime.now(timezone.utc)
    ws, we = _week_range_utc(now)
    # lọc trade tuần này
    week_trades = []
    for t in trades:
        ts = t.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if ws <= dt.replace(tzinfo=timezone.utc) < we:
            week_trades.append(t)

    pnl = _pnl_usd_estimate(week_trades)
    target = float(KPI_POLICY.get("weekly", {}).get("min_target_usd", 50))
    return {"achieved": pnl >= target, "pnl_usd": round(pnl, 2), "target": target}

def risk_factor() -> float:
    """Đạt KPI tuần → hạ risk về 0.5 theo Phase A."""
    st = weekly_status()
    return 0.5 if st.get("achieved") else 1.0
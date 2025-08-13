# tools/trade_report.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json, sys
from datetime import datetime, timezone

DATA_DIR = Path("data")
TRADES_FILE = DATA_DIR / "trade_history.json"
CANDLES_FILE = DATA_DIR / "btc_candles.json"
SYMBOL = "BTCUSDT"

def _to_float(x, default=0.0):
    try:
        if x in (None, "", "0", "0.00"): return default
        return float(x)
    except Exception:
        return default

def _parse_ts(x):
    if x is None: return None
    if isinstance(x, (int, float)):
        if x > 1e12: x = x / 1000.0
        return datetime.fromtimestamp(float(x), tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except Exception:
        return None

def _extract_array_from_dict(obj: dict):
    # Nếu trade_history là dict, thử tìm list dài nhất các dict
    candidates = []
    for v in obj.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            candidates.append(v)
    return max(candidates, key=len) if candidates else []

def load_trades(path: Path):
    if not path.exists(): return []
    try:
        obj = json.load(open(path, "r", encoding="utf-8"))
    except Exception as e:
        print(f"Không đọc được {path}: {e}")
        return []
    if isinstance(obj, dict):
        arr = _extract_array_from_dict(obj)
    elif isinstance(obj, list):
        arr = obj
    else:
        arr = []

    out = []
    for r in arr:
        if not isinstance(r, dict): continue

        status = (r.get("status") or "").upper()
        if status and status != "FILLED":
            # bỏ record NEW/REJECTED… chỉ lấy filled
            continue

        sym = r.get("symbol") or r.get("pair") or SYMBOL
        side = (r.get("side") or r.get("action") or "").upper()

        # qty: hỗ trợ cả camelCase/snake_case
        qty = (
            r.get("cumQty") or r.get("executedQty") or r.get("executed_qty")
            or r.get("qty") or r.get("quantity") or r.get("size")
        )
        # price:
        price = (
            r.get("avgPrice") or r.get("avg_price") or r.get("fill_price")
            or r.get("executed_price") or r.get("price")
        )
        ts = r.get("timestamp") or r.get("ts") or r.get("time") or r.get("created_at")

        q = _to_float(qty)
        p = _to_float(price)
        if side not in {"BUY", "SELL"} or q <= 0 or p <= 0:
            continue

        out.append({
            "symbol": sym,
            "side": side,
            "qty": q,
            "price": p,
            "ts": _parse_ts(ts)
        })

    out.sort(key=lambda x: x["ts"] or datetime.min.replace(tzinfo=timezone.utc))
    return out

def last_price_from_candles(path: Path) -> float:
    if not path.exists(): return 0.0
    try:
        obj = json.load(open(path, "r", encoding="utf-8"))
        if isinstance(obj, list) and obj:
            return _to_float(obj[-1].get("close"), 0.0)
        if isinstance(obj, dict):
            closes = obj.get("close") or obj.get("closes")
            if isinstance(closes, list) and closes:
                return _to_float(closes[-1], 0.0)
    except Exception:
        pass
    return 0.0

class PnLTracker:
    def __init__(self):
        self.lots = []   # {"qty":..., "price":..., "side": "LONG"/"SHORT", "ts": ...}
        self.realized = 0.0
        self.closed = []

    def _open(self, side, qty, price, ts):
        self.lots.append({"qty": qty, "price": price, "side": side, "ts": ts})

    def _close_against(self, side, qty, price, ts):
        target = "LONG" if side == "SELL" else "SHORT"
        remain = qty
        while remain > 1e-15 and self.lots and self.lots[0]["side"] == target:
            lot = self.lots[0]
            take = min(lot["qty"], remain)
            if lot["side"] == "LONG":
                pnl = (price - lot["price"]) * take
                entry_side, exit_side = "BUY", "SELL"
            else:
                pnl = (lot["price"] - price) * take
                entry_side, exit_side = "SELL", "BUY"
            self.realized += pnl
            self.closed.append({
                "qty": take, "entry_price": lot["price"], "exit_price": price,
                "pnl": pnl, "entry_ts": lot["ts"], "exit_ts": ts,
                "side": lot["side"], "entry_side": entry_side, "exit_side": exit_side
            })
            lot["qty"] -= take
            remain -= take
            if lot["qty"] <= 1e-15: self.lots.pop(0)
        return remain

    def on_trade(self, side, qty, price, ts):
        if side == "BUY":
            remain = self._close_against(side, qty, price, ts)
            if remain > 1e-15: self._open("LONG", remain, price, ts)
        else:
            remain = self._close_against(side, qty, price, ts)
            if remain > 1e-15: self._open("SHORT", remain, price, ts)

    def position(self):
        if not self.lots: return 0.0, 0.0
        qsum = sum(l["qty"] for l in self.lots)
        if qsum <= 1e-15: return 0.0, 0.0
        avg = sum(l["qty"]*l["price"] for l in self.lots) / qsum
        # net pos: LONG dương, SHORT âm
        net = sum(l["qty"] if l["side"]=="LONG" else -l["qty"] for l in self.lots)
        return net, avg

def main():
    trades = load_trades(TRADES_FILE)
    if not trades:
        print("📭 Không tìm thấy giao dịch FILLED trong data/trade_history.json.")
        print("→ Bật CRX_ENABLE_ORDER_EXECUTOR=1 để phát sinh lệnh mới, hoặc kiểm tra format trade_history.")
        return 0

    last_px = last_price_from_candles(CANDLES_FILE)
    tracker = PnLTracker()
    for t in trades:
        tracker.on_trade(t["side"], t["qty"], t["price"], t["ts"])

    pos, avg = tracker.position()
    unreal = 0.0
    if abs(pos) > 1e-12 and last_px > 0:
        unreal = (last_px - avg) * pos if pos > 0 else (avg - last_px) * (-pos)

    print(f"===== TRADE REPORT ({SYMBOL}) =====")
    print(f"Trades (FILLED): {len(trades)} | Closed deals: {len(tracker.closed)}")
    print(f"Realized PnL: {tracker.realized:.4f} USDT")
    if abs(pos) > 0:
        print(f"Open Position: {pos:.6f} BTC @ {avg:.2f} | Last: {last_px:.2f} | Unrealized: {unreal:.4f} USDT")
    else:
        print("Open Position: 0")

    if tracker.closed:
        print("\n-- Last 10 closed deals --")
        for d in tracker.closed[-10:]:
            et = d["entry_ts"].isoformat(timespec="seconds") if d["entry_ts"] else "?"
            xt = d["exit_ts"].isoformat(timespec="seconds") if d["exit_ts"] else "?"
            print(f"{d['side']:5s} qty={d['qty']:.6f}  {d['entry_price']:.2f} -> {d['exit_price']:.2f}  "
                  f"PNL={d['pnl']:.4f}  ({et} -> {xt})")

    if abs(pos) > 0:
        print("\n-- Open lots --")
        for l in tracker.lots:
            ts = l["ts"].isoformat(timespec="seconds") if l["ts"] else "?"
            print(f"{l['side']:5s} qty={l['qty']:.6f}  price={l['price']:.2f}  opened={ts}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
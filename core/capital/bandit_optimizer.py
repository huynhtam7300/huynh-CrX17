# core/capital/bandit_optimizer.py
from pathlib import Path
from typing import Dict, List, Tuple
from utils.io_utils import read_json

TRADE_PATH = Path("data/trade_history.json")

def _load_trades() -> List[Dict]:
    return read_json(TRADE_PATH, [])

def _recent_rewards(symbol: str, lookback: int = 30) -> List[float]:
    """
    Tạo danh sách PnL USD gần đây bằng cách 'đóng cặp' BUY->SELL hoặc SELL->BUY cùng symbol.
    Đơn giản, không tính phí/funding. Nếu dữ liệu thiếu -> bỏ qua.
    """
    trades = [t for t in _load_trades() if t.get("status") == "FILLED" and t.get("symbol") == symbol]
    if not trades:
        return []
    rewards = []
    # last_pos: (side, price, qty)
    last_pos: Tuple[str, float, float] = None
    for t in trades:
        side = t.get("side")
        qty = float(t.get("cumQty", "0") or 0)
        price = float(t.get("avgPrice", "0") or 0)
        if qty <= 0 or price <= 0:
            continue
        if last_pos is None:
            last_pos = (side, price, qty)
            continue
        ps, pp, pq = last_pos
        if (ps == "BUY" and side == "SELL") or (ps == "SELL" and side == "BUY"):
            # đóng vị thế → tính PnL
            q = min(pq, qty)
            pnl = (price - pp) * q if ps == "BUY" else (pp - price) * q
            rewards.append(float(pnl))
            last_pos = None  # đóng hoàn toàn (đơn giản)
        else:
            # cùng hướng → gộp trung bình giá
            new_qty = pq + qty
            if new_qty > 0:
                new_price = (pp * pq + price * qty) / new_qty
                last_pos = (ps, new_price, new_qty)
    # lấy đuôi lookback
    return rewards[-lookback:]

def adjust_size_by_bandit(symbol: str, action: str, base_size: float) -> Dict:
    """
    Bandit 'lite' theo winrate:
      - Tính winrate từ danh sách rewards (pnl>0).
      - factor ∈ [0.6, 1.4], mặc định 1.0 (khi thiếu dữ liệu).
      - Nếu thua liên tiếp >=3, force factor=0.6 (losing_streak).
    Trả: {size, factor, reason}
    """
    rewards = _recent_rewards(symbol, lookback=30)
    if not rewards:
        return {"size": base_size, "factor": 1.0, "reason": ["cold_start", "no_rewards"]}

    wins = sum(1 for r in rewards if r > 0)
    total = len(rewards)
    winrate = wins / total if total else 0.0

    # losing streak check (3 phần tử cuối ≤ 0)
    losing_streak = len(rewards) >= 3 and all(r <= 0 for r in rewards[-3:])

    # map winrate -> factor (tuyến tính, clamp [0.6,1.4])
    # 0.0 -> 0.6 ; 0.5 -> 1.0 ; 1.0 -> 1.4
    factor = 0.6 + 0.8 * max(0.0, min(1.0, winrate))
    if losing_streak:
        factor = 0.6

    size = max(0.0, base_size * factor)
    reasons = [f"winrate={winrate:.2f}", f"n={total}", f"losing_streak={int(losing_streak)}"]

    return {"size": round(size, 6), "factor": round(factor, 4), "reason": reasons}
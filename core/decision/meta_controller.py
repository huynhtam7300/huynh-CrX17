# core/decision/meta_controller.py
from typing import Dict, Optional

def _priority(sig: Dict, context_weight: float = 1.0) -> float:
    # Priority = (confidence * er) / max(risk, 1e-6) * context_weight
    risk = max(sig.get("risk", 0.000001), 0.000001)
    return (sig.get("confidence", 0.0) * sig.get("er", 0.0)) / risk * context_weight

def meta_decide(
    left_sig: Dict,
    *,
    right_sig: Optional[Dict] = None,         # Phase A: chưa dùng
    market_regime: str = "unknown",           # Phase A: placeholder
    atr_pct: float = 5.0,                     # từ risk_intel.atr_percent(...)
    base_size_pct: float = 0.5,               # từ config.default_order.size_pct
    kpi_risk_factor: float = 1.0              # từ KPI tracker (đạt KPI → 0.5)
) -> Dict:
    """
    Trọng tài đơn giản theo Priority Score:
      - Nếu Left WAIT → quyết định WAIT.
      - Nếu Left BUY/SELL → hành động theo Left.
      - suggested_size = base_size_pct * kpi_risk_factor * size_regime
    """
    # context weight: vol cao → giảm trọng số (giảm size)
    if atr_pct >= 3.0:      size_regime = 0.8
    if atr_pct >= 5.0:      size_regime = 0.6
    if atr_pct >= 8.0:      size_regime = 0.4
    else:                   size_regime = 1.0

    # Quyết định dựa trên Left (Phase A)
    if left_sig.get("decision") == "WAIT":
        return {
            **left_sig,
            "action": "WAIT",
            "suggested_size": 0.0,
            "meta_reason": ["left_wait"]
        }

    # Ưu tiên hướng của Left
    ctx_w = 1.0 if atr_pct < 5.0 else 0.7
    score_left = _priority(left_sig, ctx_w)

    action = left_sig["decision"] if score_left > 0 else "WAIT"
    suggested = max(0.0, base_size_pct * kpi_risk_factor * size_regime)

    out = {
        "action": action,
        "suggested_size": float(round(suggested, 4)),
        "priority_left": score_left,
        "meta_reason": [f"atr_pct={atr_pct:.2f}", f"regime={market_regime}", f"kpi_factor={kpi_risk_factor}"],
    }
    # ghép lại để log đầy đủ
    out.update({k: left_sig.get(k) for k in ("decision","confidence","er","risk","reasons")})
    return out
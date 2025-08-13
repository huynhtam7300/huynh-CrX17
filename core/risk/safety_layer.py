from typing import Dict

def validate_order_basic(signal: Dict, risk_limits: Dict) -> (bool, str):
    # signal: {side, size_pct, leverage}
    size_ok = signal.get("size_pct", 0) <= risk_limits.get("per_trade", {}).get("max_risk_pct", 1.0)
    lev_ok = signal.get("leverage", 1) <= risk_limits.get("per_trade", {}).get("max_leverage", 5)
    if not size_ok: return False, "Size vượt giới hạn"
    if not lev_ok:  return False, "Leverage vượt giới hạn"
    return True, "OK"
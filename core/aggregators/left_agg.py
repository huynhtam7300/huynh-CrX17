# core/aggregators/left_agg.py
from typing import Dict
import pandas as pd
from core.analyzer.left_strategies.ema_trend import signal_ema_trend
from core.analyzer.left_strategies.atr_breakout import signal_atr_breakout

def _merge_same_dir(a: Dict, b: Dict) -> Dict:
    # Nếu cùng hướng BUY/SELL → tăng confidence + er
    out = a.copy()
    out["confidence"] = min(0.95, (a["confidence"] + b["confidence"]) / 2 + 0.1)
    out["er"] = (a["er"] + b["er"]) / 2
    out["reasons"] = list({*a.get("reasons", []), *b.get("reasons", [])})
    return out

def aggregate(df: pd.DataFrame) -> Dict:
    """
    Gộp 2 chiến lược kỹ thuật hiện có → 1 tín hiệu chuẩn:
    {decision, confidence, er, risk, reasons}
    """
    s1 = signal_ema_trend(df)
    s2 = signal_atr_breakout(df)

    # Nếu một trong hai WAIT → lấy cái còn lại
    if s1["decision"] == "WAIT" and s2["decision"] != "WAIT":
        return s2
    if s2["decision"] == "WAIT" and s1["decision"] != "WAIT":
        return s1

    # Cùng hướng → tăng confidence
    if s1["decision"] in ("BUY", "SELL") and s1["decision"] == s2["decision"]:
        return _merge_same_dir(s1, s2)

    # Xung đột → WAIT để Meta xử lý cẩn trọng
    return {"decision": "WAIT", "confidence": 0.0, "er": 0.0, "risk": 0.0, "reasons": ["left_conflict"]}
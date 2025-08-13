import pandas as pd
from .left_strategies.ema_trend import signal_ema_trend
from .left_strategies.atr_breakout import signal_atr_breakout

def analyze(df: pd.DataFrame):
    # Trả về format chuẩn Phase CORE
    s1 = signal_ema_trend(df)
    s2 = signal_atr_breakout(df)
    # gộp cực đơn giản: ưu tiên s1, nếu WAIT thì lấy s2
    out = s1 if s1["decision"] != "WAIT" else s2
    return out
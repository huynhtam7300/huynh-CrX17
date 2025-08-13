import pandas as pd

def atr_percent(df: pd.DataFrame, period: int = 14) -> float:
    # ATR% tối giản cho CORE (naive)
    if len(df) < period+1: return 0.0
    tr = (df["high"] - df["low"]).rolling(period).mean().iloc[-1]
    close = df["close"].iloc[-1]
    return float(tr / close * 100) if close else 0.0
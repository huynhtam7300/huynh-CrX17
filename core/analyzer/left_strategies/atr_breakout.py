import pandas as pd

def signal_atr_breakout(df: pd.DataFrame):
    if len(df) < 20:
        return {"decision":"WAIT","confidence":0.0,"er":0.0,"risk":0.0,"reasons":["not_enough_data"]}
    high = df["high"].iloc[-20:].max()
    low  = df["low"].iloc[-20:].min()
    last = df["close"].iloc[-1]
    if last > high:
        return {"decision":"BUY","confidence":0.5,"er":0.15,"risk":0.1,"reasons":["breakout_high_20"]}
    if last < low:
        return {"decision":"SELL","confidence":0.5,"er":0.15,"risk":0.1,"reasons":["breakdown_low_20"]}
    return {"decision":"WAIT","confidence":0.0,"er":0.0,"risk":0.0,"reasons":["in_range"]}
import pandas as pd

def ema(series, n):
    return series.rolling(n).mean()

def signal_ema_trend(df: pd.DataFrame):
    if len(df) < 50:
        return {"decision":"WAIT","confidence":0.0,"er":0.0,"risk":0.0,"reasons":["not_enough_data"]}
    close = df["close"]
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    if ema20.iloc[-1] > ema50.iloc[-1]:
        return {"decision":"BUY","confidence":0.55,"er":0.2,"risk":0.1,"reasons":["ema20>ema50"]}
    if ema20.iloc[-1] < ema50.iloc[-1]:
        return {"decision":"SELL","confidence":0.55,"er":0.2,"risk":0.1,"reasons":["ema20<ema50"]}
    return {"decision":"WAIT","confidence":0.0,"er":0.0,"risk":0.0,"reasons":["flat"]}
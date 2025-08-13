# core/collector/market_collector.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import List
import time
import requests
import pandas as pd

from utils.io_utils import write_json
from configs.config import CONFIG

# ====== Cấu hình nguồn ======
# Binance Futures Testnet (không cần API key cho klines)
BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"
KLINES_ENDPOINT = "/fapi/v1/klines"

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DATA_BTC = DATA_DIR / "btc_candles.json"
DATA_ETH = DATA_DIR / "eth_candles.json"

# Map timeframe hợp lệ của Binance
_VALID_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"
}

def _timeframe() -> str:
    tf = str(CONFIG.get("timeframe", "15m"))
    return tf if tf in _VALID_INTERVALS else "15m"

def _symbols() -> List[str]:
    syms = CONFIG.get("symbols", ["BTCUSDT", "ETHUSDT"])
    return [s.strip().upper() for s in syms if isinstance(s, str)]

def fetch_klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    """
    Lấy nến từ Binance Futures Testnet.
    Trả về DataFrame cột: time (UTC ISO), open, high, low, close, volume
    """
    url = BINANCE_FUTURES_TESTNET + KLINES_ENDPOINT
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    cols = [
        "openTime","open","high","low","close","volume",
        "closeTime","qVol","trades","tbBase","tbQuote","ignore"
    ]
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            raw = r.json()
            df = pd.DataFrame(raw, columns=cols)

            # Ép kiểu số
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            # Tạo cột time (UTC ISO, dạng 2025-08-12T03:00:00+00:00) từ closeTime (ms)
            t = pd.to_datetime(df["closeTime"], unit="ms", utc=True)
            # chuyển %z (±HHMM) -> ±HH:MM cho đồng nhất
            iso = t.dt.strftime("%Y-%m-%dT%H:%M:%S%z").str.replace(
                r"(\+|\-)(\d{2})(\d{2})$", r"\1\2:\3", regex=True
            )
            df["time"] = iso

            df = df[["time", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
            return df
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(0.8)
    return pd.DataFrame()

def save_candles(symbol: str, df: pd.DataFrame):
    path = DATA_BTC if symbol.upper() == "BTCUSDT" else DATA_ETH
    # Lưu tối đa 100 nến gần nhất, dạng records
    records = df.tail(100).to_dict(orient="records")
    write_json(path, records)
    print(f"[collector] Saved {symbol} candles -> {path} (n={len(records)})")

def run():
    interval = _timeframe()
    symbols = _symbols()
    for sym in symbols:
        df = fetch_klines(sym, interval=interval, limit=200)
        if df.empty:
            print(f"[collector] WARN: không lấy được nến {sym} ({interval}).")
            continue
        save_candles(sym, df)
    print("[collector] Đã lưu nến (records) từ Binance Futures Testnet.")

if __name__ == "__main__":
    run()
# core/capital/funding_optimizer.py
from typing import Tuple, Dict
import time
import requests
from configs.config import CONFIG
from notifier.notify_telegram import send_telegram_message

BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"

def get_funding_info(symbol: str) -> Tuple[float, int]:
    """
    Trả về (lastFundingRate, nextFundingTime_ms)
    lastFundingRate dạng float (vd 0.0001 = 0.01%)
    """
    url = BINANCE_FUTURES_TESTNET + "/fapi/v1/premiumIndex"
    try:
        r = requests.get(url, params={"symbol": symbol}, timeout=10)
        r.raise_for_status()
        j = r.json()
        rate = float(j.get("lastFundingRate", 0.0) or 0.0)
        nxt  = int(j.get("nextFundingTime", 0) or 0)
        return rate, nxt
    except Exception as e:
        # lỗi mạng → coi như 0
        send_telegram_message(f"[funding] warn: {e}")
        return 0.0, 0

def adjust_size_by_funding(symbol: str, side: str, base_size: float) -> Dict:
    """
    Điều chỉnh size theo funding 'lite':
    - Long (BUY) trả khi rate > 0
    - Short (SELL) trả khi rate < 0
    """
    fcfg = CONFIG.get("funding", {})
    if not fcfg or not fcfg.get("enable", True):
        return {"size": base_size, "rate": 0.0, "next_ms": 0, "factor": 1.0, "reason": ["funding_disabled"]}

    thr      = float(fcfg.get("threshold_abs", 0.0001))
    near_min = int(fcfg.get("near_window_minutes", 10))
    pen      = float(fcfg.get("penalty_factor", 0.5))
    bonus    = float(fcfg.get("bonus_factor", 1.1))
    max_f    = float(fcfg.get("max_factor", 1.0))
    min_f    = float(fcfg.get("min_factor", 0.2))

    rate, next_ms = get_funding_info(symbol)
    now_ms = int(time.time() * 1000)
    mins_left = (next_ms - now_ms) / 60000 if next_ms else 9999

    # Mặc định giữ nguyên
    factor = 1.0
    rsn = [f"rate={rate:.6f}", f"mins_left={mins_left:.1f}"]

    # Bất lợi: Long trả khi rate>0, Short trả khi rate<0
    disadvantage = (side == "BUY" and rate > +thr) or (side == "SELL" and rate < -thr)
    advantage    = (side == "BUY" and rate < -thr) or (side == "SELL" and rate > +thr)

    if disadvantage:
        factor *= pen
        rsn.append("disadvantage")
    elif advantage:
        factor *= bonus
        rsn.append("advantage")

    # Cẩn trọng gần kỳ funding
    if mins_left <= near_min:
        factor *= pen
        rsn.append("near_window")

    # Chặn biên
    if factor > max_f: factor = max_f
    if factor < min_f: factor = min_f

    return {
        "size": round(base_size * factor, 6),
        "rate": rate,
        "next_ms": next_ms,
        "factor": round(factor, 4),
        "reason": rsn
    }
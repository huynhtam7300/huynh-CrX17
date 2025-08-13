# core/execution/order_monitor.py
import os
import time
import hmac
import hashlib
from urllib.parse import urlencode
from typing import Optional, Dict, Any
import requests

BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"
API_KEY    = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})

def _sign(params: Dict[str, Any]) -> str:
    query = urlencode(params, doseq=True)
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def _get(path: str, params: Dict[str, Any] = None, signed: bool = False, timeout: int = 10):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BINANCE_FUTURES_TESTNET + path
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def get_order(symbol: str, order_id: Optional[int] = None, client_order_id: Optional[str] = None):
    if not API_KEY or not API_SECRET:
        return {"status": "SIMULATED"}
    params = {"symbol": symbol}
    if order_id is not None:
        params["orderId"] = order_id
    elif client_order_id is not None:
        params["origClientOrderId"] = client_order_id
    else:
        raise ValueError("Cần order_id hoặc client_order_id")

    return _get("/fapi/v1/order", params=params, signed=True)

def poll_until_final(symbol: str, order_id: Optional[int], client_order_id: Optional[str],
                     timeout_sec: int = 20, interval_sec: float = 1.0):
    """
    Chờ tới khi trạng thái là FILLED/CANCELED/REJECTED/EXPIRED hoặc hết timeout.
    """
    end = time.time() + timeout_sec
    last = {}
    while time.time() < end:
        try:
            last = get_order(symbol, order_id=order_id, client_order_id=client_order_id)
            st = last.get("status", "")
            if st in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"):
                return last
        except Exception as e:
            # bỏ qua lỗi tạm thời và thử lại
            last = {"error": str(e)}
        time.sleep(interval_sec)
    return last or {"status": "UNKNOWN"}
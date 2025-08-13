# core/execution/order_executor.py
import os
import time
import hmac
import hashlib
from typing import Dict, Any, Tuple
from urllib.parse import urlencode

import requests

from notifier.notify_telegram import send_telegram_message
from utils.uid import new_order_uid
from configs.config import CONFIG

BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"

API_KEY    = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})


# ---------- ký & gọi API ----------
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

def _post(path: str, params: Dict[str, Any] = None, signed: bool = True, timeout: int = 10):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BINANCE_FUTURES_TESTNET + path
    r = SESSION.post(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------- thông tin sàn & tính QTY ----------
def _get_exchange_info(symbol: str) -> Dict[str, Any]:
    data = _get("/fapi/v1/exchangeInfo", signed=False)
    syms = {s["symbol"]: s for s in data.get("symbols", [])}
    if symbol not in syms:
        raise ValueError(f"{symbol} không có trên Binance Futures Testnet")
    return syms[symbol]

def _get_price(symbol: str) -> float:
    data = _get("/fapi/v1/ticker/price", params={"symbol": symbol}, signed=False)
    return float(data["price"])

def _round_step(value: float, step: float) -> float:
    return (int(value / step)) * step

def _qty_filters(info: Dict[str, Any]) -> Tuple[float, float]:
    step, min_qty = 0.001, 0.001
    for f in info.get("filters", []):
        if f.get("filterType") in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            step = float(f.get("stepSize", step))
            min_qty = float(f.get("minQty", min_qty))
    return step, min_qty

def _ensure_leverage(symbol: str, leverage: int) -> None:
    try:
        _post("/fapi/v1/leverage", params={"symbol": symbol, "leverage": leverage}, signed=True)
    except Exception as e:
        print("[executor] leverage set warn:", e)

def _compute_qty(symbol: str, notional_usdt: float) -> float:
    price = _get_price(symbol)
    rough = notional_usdt / price if price > 0 else 0.0
    info = _get_exchange_info(symbol)
    step, min_qty = _qty_filters(info)
    qty = _round_step(rough, step)
    if qty < min_qty:
        qty = min_qty
    return float(qty)


# ---------- đặt lệnh MARKET ----------
def place_order(symbol: str, side: str, size_pct: float, leverage: int = 1, notional_usdt: float = None):
    """
    Đặt MARKET trên Binance Futures Testnet.
    Nếu thiếu API key/secret -> chạy mô phỏng (SIMULATED).
    """
    if not API_KEY or not API_SECRET:
        uid = new_order_uid()
        msg = f"🟢 EXECUTE {side} {symbol} (SIM) size={size_pct:.2f}% lev={leverage} uid={uid}"
        print(msg); send_telegram_message(msg)
        return {"order_uid": uid, "status": "SIMULATED", "client_order_id": uid}

    if notional_usdt is None:
        notional_usdt = float(CONFIG.get("default_order", {}).get("notional_usdt", 50))

    _ensure_leverage(symbol, leverage)
    qty = _compute_qty(symbol, notional_usdt)

    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": f"{qty:.8f}"}
    resp = _post("/fapi/v1/order", params=params, signed=True)

    uid_client = resp.get("clientOrderId") or new_order_uid()
    order_id = resp.get("orderId")
    msg = f"🟢 EXECUTE {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid_client}"
    print(msg); send_telegram_message(msg)

    return {
        "order_uid": uid_client,
        "client_order_id": uid_client,
        "order_id": order_id,
        "status": resp.get("status", "NEW"),
        "cumQty": resp.get("executedQty", "0"),
        "avgPrice": resp.get("avgPrice", "0")
    }
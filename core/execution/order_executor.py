# core/execution/order_executor.py
from __future__ import annotations

import os
import time
import hmac
import hashlib
from typing import Dict, Any, Tuple
from urllib.parse import urlencode

import requests

from notifier.notify_telegram import send_telegram_message
from utils.uid import new_order_uid

# -----------------------------------------------------------------------------
# Nạp CONFIG bền vững:
# - Ưu tiên import dạng package: from config.config import CONFIG
# - Nếu môi trường che khuất package 'config', fallback import theo file path
# -----------------------------------------------------------------------------
import sys
import pathlib
import importlib.util

root = pathlib.Path(__file__).resolve().parents[2]  # .../CrX17
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

try:
    # Ưu tiên import như package (service đã có PYTHONPATH trỏ về repo root)
    from config.config import CONFIG  # type: ignore
except Exception:
    # Fallback: ép load theo đường dẫn file để tránh xung đột module 'config' bên ngoài
    cfg_path = (root / "config" / "config.py").resolve()
    spec = importlib.util.spec_from_file_location("crx_config", str(cfg_path))
    _crx_cfg = importlib.util.module_from_spec(spec)
    if not spec or not spec.loader:
        raise RuntimeError("Không thể tạo spec cho config/config.py")
    spec.loader.exec_module(_crx_cfg)  # type: ignore
    CONFIG = _crx_cfg.CONFIG  # type: ignore
# -----------------------------------------------------------------------------


BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})


# ---------- ký & gọi API ----------
def _sign(params: Dict[str, Any]) -> str:
    query = urlencode(params, doseq=True)
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


def _get(path: str, params: Dict[str, Any] | None = None, signed: bool = False, timeout: int = 10):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BINANCE_FUTURES_TESTNET + path
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(path: str, params: Dict[str, Any] | None = None, signed: bool = True, timeout: int = 10):
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
    if step <= 0:
        return float(value)
    return float(int(value / step) * step)


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
def place_order(
    symbol: str,
    side: str,
    size_pct: float,
    leverage: int = 1,
    notional_usdt: float | None = None
):
    """
    Đặt MARKET trên Binance Futures Testnet.
    Nếu thiếu API key/secret -> chạy mô phỏng (SIMULATED).
    - symbol: ví dụ 'BTCUSDT'
    - side: 'BUY' hoặc 'SELL'
    - size_pct: % sizing do hệ thống quyết định (hiện dùng cho log)
    - leverage: đòn bẩy mong muốn
    - notional_usdt: giá trị danh nghĩa; nếu None sẽ lấy từ CONFIG hoặc default=50
    """
    # Không có API -> mô phỏng
    if not API_KEY or not API_SECRET:
        uid = new_order_uid()
        msg = f"🟢 EXECUTE {side} {symbol} (SIM) size={size_pct:.2f}% lev={leverage} uid={uid}"
        print(msg)
        try:
            send_telegram_message(msg)
        except Exception as _:
            pass
        return {"order_uid": uid, "status": "SIMULATED", "client_order_id": uid}

    # Lấy notional mặc định từ CONFIG nếu không truyền vào
    if notional_usdt is None:
        # ưu tiên executor.order_policy.default_order.notional_usdt nếu có
        try:
            notional_usdt = float(
                CONFIG["executor"]["order_policy"].get("default_order", {}).get("notional_usdt", 50)
            )
        except Exception:
            notional_usdt = float(CONFIG.get("default_order", {}).get("notional_usdt", 50))

    # Cố gắng set leverage (nếu API cho phép)
    _ensure_leverage(symbol, leverage)

    # Tính qty từ notional & filter
    qty = _compute_qty(symbol, float(notional_usdt))

    # Gửi lệnh MARKET
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": f"{qty:.8f}"}
    try:
        resp = _post("/fapi/v1/order", params=params, signed=True)
    except Exception as e:
        uid = new_order_uid()
        msg = f"🔴 EXECUTE FAIL {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid} err={e}"
        print(msg)
        try:
            send_telegram_message(msg)
        except Exception:
            pass
        return {"order_uid": uid, "status": "ERROR", "error": str(e)}

    uid_client = resp.get("clientOrderId") or new_order_uid()
    order_id = resp.get("orderId")
    msg = f"🟢 EXECUTE {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid_client}"
    print(msg)
    try:
        send_telegram_message(msg)
    except Exception:
        pass

    return {
        "order_uid": uid_client,
        "client_order_id": uid_client,
        "order_id": order_id,
        "status": resp.get("status", "NEW"),
        "cumQty": resp.get("executedQty", "0"),
        "avgPrice": resp.get("avgPrice", "0"),
    }
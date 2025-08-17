# core/execution/order_executor.py
from __future__ import annotations

import os
import time
import hmac
import json
import hashlib
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlencode

import requests

from notifier.notify_telegram import send_telegram_message
from utils.uid import new_order_uid

# -----------------------------------------------------------------------------
# Nạp CONFIG bền vững (package-first, path fallback)
# -----------------------------------------------------------------------------
import sys
import pathlib
import importlib.util

root = pathlib.Path(__file__).resolve().parents[2]  # .../CrX17
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

try:
    from config.config import CONFIG  # type: ignore
except Exception:
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
    from urllib.parse import urlencode
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
    params = dict(params or {}
    )
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
    """
    if not API_KEY or not API_SECRET:
        uid = new_order_uid()
        msg = f"🟢 EXECUTE {side} {symbol} (SIM) size={size_pct:.2f}% lev={leverage} uid={uid}"
        print(msg)
        try:
            send_telegram_message(msg)
        except Exception:
            pass
        return {"order_uid": uid, "status": "SIMULATED", "client_order_id": uid}

    if notional_usdt is None:
        try:
            notional_usdt = float(
                CONFIG["executor"]["order_policy"].get("default_order", {}).get("notional_usdt", 50)
            )
        except Exception:
            notional_usdt = float(CONFIG.get("default_order", {}).get("notional_usdt", 50))

    _ensure_leverage(symbol, leverage)
    qty = _compute_qty(symbol, float(notional_usdt))

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

# ================== ENTRYPOINT cho runner ==================
_STATE_FILE = root / "executor_state.json"

def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_state(st: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _read_last_decision_file() -> Optional[Dict[str, Any]]:
    candidates = [
        root / "last_decision.json",
        root / "data" / "last_decision.json",
        root / "data" / "decision_latest.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None

def _read_last_decision_from_log() -> Optional[Dict[str, Any]]:
    """Fallback: parse dòng '[decision] record: {...}' gần nhất trong logs/runner.log"""
    log_path = root / "logs" / "runner.log"
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-600:]  # đọc ~600 dòng cuối
        for line in reversed(lines):
            key = "[decision] record:"
            pos = line.find(key)
            if pos != -1:
                jstart = line.find("{", pos)
                if jstart != -1:
                    js = line[jstart:].strip()
                    try:
                        return json.loads(js)
                    except Exception:
                        continue
    except Exception:
        pass
    return None

def _read_last_decision() -> Optional[Dict[str, Any]]:
    dec = _read_last_decision_file()
    if dec:
        return dec
    dec = _read_last_decision_from_log()
    if dec:
        print("[executor] picked decision from log")
    return dec

def _guess_symbol() -> str:
    try:
        cen = CONFIG.get("central", {})  # type: ignore
        syms = cen.get("symbols") or cen.get("universe") or []
        if isinstance(syms, list) and syms:
            return str(syms[0])
    except Exception:
        pass
    return "BTCUSDT"

def run() -> None:
    # Bật/tắt qua env
    if str(os.getenv("CRX_ENABLE_ORDER_EXECUTOR", "")).lower() not in ("1", "true", "yes"):
        print("[executor] disabled by env CRX_ENABLE_ORDER_EXECUTOR")
        return

    dec = _read_last_decision()
    if not dec:
        print("[executor] no decision file found")
        return

    side = (dec.get("meta_action") or dec.get("decision") or "").upper()
    if side not in ("BUY", "SELL"):
        print("[executor] no actionable side in decision")
        return

    ts = dec.get("timestamp") or dec.get("ts")
    st = _load_state()
    if ts and st.get("last_ts") == ts:
        print("[executor] skip duplicate decision ts=", ts)
        return

    try:
        conf = float(dec.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    try:
        min_conf = float(CONFIG.get("central", {}).get("min_confidence", 0.5))  # type: ignore
    except Exception:
        min_conf = 0.5
    if conf < min_conf:
        print(f"[executor] skip: confidence {conf} < min {min_conf}")
        return

    symbol = dec.get("symbol") or _guess_symbol()
    size_pct = float(dec.get("suggested_size", 0.2))
    try:
        notional = float(
            CONFIG["executor"]["order_policy"].get("default_order", {}).get("notional_usdt", 50)
        )
    except Exception:
        notional = 50.0

    res = place_order(symbol=symbol, side=side, size_pct=size_pct, leverage=1, notional_usdt=notional)

    st["last_ts"] = ts
    st["last_order"] = {"symbol": symbol, "side": side, "result": res}
    _save_state(st)

if __name__ == "__main__":
    run()
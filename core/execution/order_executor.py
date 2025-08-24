# core/execution/order_executor.py
from __future__ import annotations

import os, time, hmac, json, hashlib, pathlib, sys, importlib.util
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlencode

import requests

from notifier.notify_telegram import send_telegram_message
from utils.uid import new_order_uid

# ---------- Paths & CONFIG ----------
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

# ---------- ENV / Constants ----------
BINANCE_FUTURES_TESTNET = "https://testnet.binancefuture.com"

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

OPEN_CONF_FLOOR  = float(os.getenv("CRX_OPEN_CONF_FLOOR",  "0.65"))  # mở mới
CLOSE_CONF_FLOOR = float(os.getenv("CRX_CLOSE_CONF_FLOOR", "0.60"))  # đóng đảo chiều

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})

# ---------- Helpers ----------
def _sign(params: Dict[str, Any]) -> str:
    q = urlencode(params, doseq=True)
    return hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()

def _get(path: str, params: Dict[str, Any] | None = None, signed: bool = False, timeout: int = 12):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BINANCE_FUTURES_TESTNET + path
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _post(path: str, params: Dict[str, Any] | None = None, signed: bool = True, timeout: int = 12):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BINANCE_FUTURES_TESTNET + path
    r = SESSION.post(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _get_price(symbol: str) -> float:
    data = _get("/fapi/v1/ticker/price", params={"symbol": symbol}, signed=False)
    return float(data["price"])

def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    return float(int(value / step) * step)

def _get_exchange_info(symbol: str) -> Dict[str, Any]:
    data = _get("/fapi/v1/exchangeInfo", signed=False)
    syms = {s["symbol"]: s for s in data.get("symbols", [])}
    if symbol not in syms:
        raise ValueError(f"{symbol} không có trên Binance Futures Testnet")
    return syms[symbol]

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

def _guess_symbol() -> str:
    try:
        cen = CONFIG.get("central", {})  # type: ignore
        syms = cen.get("symbols") or cen.get("universe") or []
        if isinstance(syms, list) and syms:
            return str(syms[0])
    except Exception:
        pass
    return "BTCUSDT"

# ---------- Position & Close ----------
def get_position(symbol: str) -> Tuple[float, float]:
    """Return (positionAmt, entryPrice). 0 if flat or missing key."""
    if not API_KEY or not API_SECRET:
        return 0.0, 0.0
    try:
        js = _get("/fapi/v2/positionRisk", params={"symbol": symbol}, signed=True)
        row = js[0] if isinstance(js, list) and js else js
        amt = float(row.get("positionAmt", 0.0))
        entry = float(row.get("entryPrice", 0.0))
        return amt, entry
    except Exception as e:
        print("[executor] get_position error:", e)
        return 0.0, 0.0

def close_position(symbol: str) -> Dict[str, Any]:
    """Reduce-only MARKET to flat the current position."""
    # Sim mode
    if not API_KEY or not API_SECRET:
        uid = new_order_uid()
        msg = f"🟠 CLOSE {symbol} (SIM reduceOnly) uid={uid}"
        print(msg)
        try: send_telegram_message(msg)
        except Exception: pass
        return {"status": "SIMULATED", "order_uid": uid}

    qty, _ = get_position(symbol)
    if abs(qty) <= 0.0:
        print("[executor] close_position: no position")
        return {"status": "NO_POSITION"}

    side = "BUY" if qty < 0 else "SELL"
    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": f"{abs(qty):.8f}",
        "reduceOnly": "true",
    }
    try:
        resp = _post("/fapi/v1/order", params=params, signed=True)
    except Exception as e:
        print("[executor] close_position error:", e)
        return {"status": "ERROR", "error": str(e)}

    msg = f"🔻 CLOSE {symbol} reduceOnly side={side} qty={abs(qty):.8f}"
    print(msg)
    try: send_telegram_message(msg)
    except Exception: pass
    return {"status": resp.get("status", "NEW"), "resp": resp}

# ---------- Place order ----------
def place_order(
    symbol: str,
    side: str,
    size_pct: float,
    leverage: int = 1,
    notional_usdt: float | None = None
):
    """Place MARKET on Binance Futures Testnet, or SIM if no keys."""
    # SIM mode
    if not API_KEY or not API_SECRET:
        uid = new_order_uid()
        msg = f"🟢 EXECUTE {side} {symbol} (SIM) size={size_pct:.2f}% lev={leverage} uid={uid}"
        print(msg)
        try: send_telegram_message(msg)
        except Exception: pass
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
        try: send_telegram_message(msg)
        except Exception: pass
        return {"order_uid": uid, "status": "ERROR", "error": str(e)}

    uid_client = resp.get("clientOrderId") or new_order_uid()
    order_id = resp.get("orderId")
    msg = f"🟢 EXECUTE {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid_client}"
    print(msg)
    try: send_telegram_message(msg)
    except Exception: pass

    return {
        "order_uid": uid_client,
        "client_order_id": uid_client,
        "order_id": order_id,
        "status": resp.get("status", "NEW"),
        "cumQty": resp.get("executedQty", "0"),
        "avgPrice": resp.get("avgPrice", "0"),
    }

# ---------- Decision readers ----------
def _load_json(path: pathlib.Path) -> Optional[Dict[str, Any]]:
    if not path.exists(): return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def _read_last_decision_file() -> Optional[Dict[str, Any]]:
    cands = [
        root / "last_decision.json",
        root / "data" / "last_decision.json",
        root / "data" / "decision_latest.json",
    ]
    for p in cands:
        j = _load_json(p)
        if isinstance(j, dict) and j:
            return j
    # fallback JSONL
    jl = root / "data" / "decision_history.jsonl"
    if jl.exists():
        try:
            lines = [ln for ln in jl.read_text(encoding="utf-8").splitlines() if ln.strip()]
            return json.loads(lines[-1])
        except Exception:
            pass
    return None

def _read_last_decision_from_log() -> Optional[Dict[str, Any]]:
    """Parse closest '[decision] record: {...}' in logs/runner.log"""
    log_path = root / "logs" / "runner.log"
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-800:]
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
        print(f"[executor] decision source=file ts={dec.get('timestamp')} conf={dec.get('confidence')} sym={dec.get('symbol')}")
        return dec
    dec = _read_last_decision_from_log()
    if dec:
        print(f"[executor] decision source=log conf={dec.get('confidence')} sym={dec.get('symbol')}")
    return dec

# ---------- Route state ----------
def _current_route() -> str:
    p = root / "data" / "meta_state.json"
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
        return j.get("current_route", "LEFT")
    except Exception:
        return "LEFT"

# ---------- Executor state ----------
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

# ---------- Main run ----------
def run() -> None:
    # Gate by ENV
    if str(os.getenv("CRX_ENABLE_ORDER_EXECUTOR", "")).lower() not in ("1", "true", "yes"):
        print("[executor] disabled by env CRX_ENABLE_ORDER_EXECUTOR")
        return

    # Route gate
    route = _current_route()
    if route != "LEFT":
        print(f"[executor] skip: route={route} (Phase B chỉ thực thi khi route=LEFT)")
        return

    dec = _read_last_decision()
    if not dec:
        print("[executor] no decision available")
        return

    # Duplicate ts guard
    ts = dec.get("timestamp") or dec.get("ts")
    st = _load_state()
    if ts and st.get("last_ts") == ts:
        print("[executor] skip duplicate decision ts=", ts)
        return

    side = (dec.get("meta_action") or dec.get("decision") or "").upper()
    if side not in ("BUY", "SELL"):
        print("[executor] no actionable side in decision")
        return

    try:
        conf = float(dec.get("confidence", 0.0))
    except Exception:
        conf = 0.0

    symbol = dec.get("symbol") or _guess_symbol()
    size_pct = float(dec.get("suggested_size", 0.2))
    try:
        notional = float(
            CONFIG["executor"]["order_policy"].get("default_order", {}).get("notional_usdt", 50)
        )
    except Exception:
        notional = 50.0

    # 1) Close-on-reversal FIRST
    pos_amt, _ = get_position(symbol)
    pos_side = "LONG" if pos_amt > 0 else "SHORT" if pos_amt < 0 else "FLAT"
    reversed_signal = (
        (pos_side == "LONG" and side == "SELL") or
        (pos_side == "SHORT" and side == "BUY")
    )
    if reversed_signal and conf >= CLOSE_CONF_FLOOR:
        close_position(symbol)
        # mark this decision consumed (không mở mới trong cùng tick)
        st["last_ts"] = ts
        st["last_action"] = {"symbol": symbol, "action": "CLOSE", "conf": conf, "ts": ts}
        _save_state(st)
        return

    # 2) Open-new gate
    if conf < OPEN_CONF_FLOOR:
        src = "env"
        print(f"[executor] skip: confidence {conf:.2f} < floor {OPEN_CONF_FLOOR:.2f} (src={src})")
        return

    # 3) Only open if flat (tránh chồng vị thế)
    if pos_side != "FLAT":
        print(f"[executor] skip: already in position ({pos_side})")
        return

    # 4) Place order
    res = place_order(symbol=symbol, side=side, size_pct=size_pct, leverage=1, notional_usdt=notional)
    st["last_ts"] = ts
    st["last_order"] = {"symbol": symbol, "side": side, "result": res}
    _save_state(st)

if __name__ == "__main__":
    run()
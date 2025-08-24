# core/execution/order_executor.py
from __future__ import annotations

import os, time, hmac, json, hashlib, pathlib, importlib.util, sys
from typing import Dict, Any, Optional, Tuple, List
from urllib.parse import urlencode

import requests

# -----------------------------------------------------------------------------
# Load CONFIG (package-first, path fallback)
# -----------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../CrX17
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from config.config import CONFIG  # type: ignore
except Exception:
    cfg_path = (ROOT / "config" / "config.py").resolve()
    spec = importlib.util.spec_from_file_location("crx_config", str(cfg_path))
    _crx_cfg = importlib.util.module_from_spec(spec)
    if not spec or not spec.loader:
        raise RuntimeError("Không thể tạo spec cho config/config.py")
    spec.loader.exec_module(_crx_cfg)  # type: ignore
    CONFIG = _crx_cfg.CONFIG  # type: ignore

# -----------------------------------------------------------------------------
# ENV & const
# -----------------------------------------------------------------------------
BASE_URL = os.getenv("BINANCE_BASE_URL", "https://testnet.binancefuture.com")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})

def _sign(params: Dict[str, Any]) -> str:
    q = urlencode(params, doseq=True)
    return hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()

def _get(path: str, params: Dict[str, Any] | None = None, signed: bool = False, timeout: int = 10):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BASE_URL + path
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _post(path: str, params: Dict[str, Any] | None = None, signed: bool = True, timeout: int = 10):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BASE_URL + path
    r = SESSION.post(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

# -----------------------------------------------------------------------------
# Helpers – route, decision, qty
# -----------------------------------------------------------------------------
def _current_route() -> str:
    """Đọc route từ data/meta_state.json (Phase B chỉ thực thi khi LEFT)."""
    p = ROOT / "data" / "meta_state.json"
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
        return (st.get("current_route") or "WAIT").upper()
    except Exception:
        return "WAIT"

def _parse_decision(s: str) -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(s)
        # kiểm tra trường tối thiểu
        if "decision" in d and "confidence" in d:
            return d
    except Exception:
        pass
    return None

def _read_decision_from_files() -> Optional[Dict[str, Any]]:
    """Ưu tiên tuyệt đối các file; chọn bản có timestamp mới nhất nếu có nhiều."""
    cands: List[pathlib.Path] = [
        ROOT / "last_decision.json",
        ROOT / "data" / "last_decision.json",
        ROOT / "data" / "decision_latest.json",
    ]
    picked: Optional[Tuple[str, Dict[str, Any]]] = None
    for p in cands:
        if not p.exists():
            continue
        try:
            d = _parse_decision(p.read_text(encoding="utf-8"))
            if not d:
                continue
            ts = str(d.get("timestamp") or "")
            if picked is None or ts > picked[0]:
                picked = (ts, d)
        except Exception:
            continue
    if picked:
        d = picked[1]
        print(f"[executor] decision source=file ts={picked[0]} conf={d.get('confidence')} sym={d.get('symbol')}")
        return d
    return None

def _read_decision_from_log() -> Optional[Dict[str, Any]]:
    """Fallback cuối: parse '[decision] record:' từ logs/runner.log."""
    log_path = ROOT / "logs" / "runner.log"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-800:]
        key = "[decision] record:"
        for line in reversed(lines):
            pos = line.find(key)
            if pos != -1:
                jstart = line.find("{", pos)
                if jstart != -1:
                    js = line[jstart:].strip()
                    d = _parse_decision(js)
                    if d:
                        print(f"[executor] decision source=log conf={d.get('confidence')} sym={d.get('symbol')}")
                        return d
    except Exception:
        pass
    return None

def _read_last_decision() -> Optional[Dict[str, Any]]:
    d = _read_decision_from_files()
    if d:
        return d
    return _read_decision_from_log()

def _get_exchange_info(symbol: str) -> Dict[str, Any]:
    data = _get("/fapi/v1/exchangeInfo", signed=False)
    syms = {s["symbol"]: s for s in data.get("symbols", [])}
    if symbol not in syms:
        raise ValueError(f"{symbol} không có trên Binance Futures (base={BASE_URL})")
    return syms[symbol]

def _get_price(symbol: str) -> float:
    data = _get("/fapi/v1/ticker/price", {"symbol": symbol}, signed=False)
    return float(data["price"])

def _round_step(v: float, step: float) -> float:
    if step <= 0: return float(v)
    return float(int(v / step) * step)

def _qty_filters(info: Dict[str, Any]) -> Tuple[float, float]:
    step, min_qty = 0.001, 0.001
    for f in info.get("filters", []):
        if f.get("filterType") in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            step = float(f.get("stepSize", step))
            min_qty = float(f.get("minQty", min_qty))
    return step, min_qty

def _ensure_leverage(symbol: str, leverage: int) -> None:
    try:
        _post("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True)
    except Exception as e:
        print("[executor] leverage warn:", e)

def _compute_qty(symbol: str, notional_usdt: float) -> float:
    px = _get_price(symbol)
    rough = notional_usdt / px if px > 0 else 0.0
    info = _get_exchange_info(symbol)
    step, min_qty = _qty_filters(info)
    qty = _round_step(rough, step)
    if qty < min_qty:
        qty = min_qty
    return float(qty)

# -----------------------------------------------------------------------------
# Place order (SIM nếu thiếu API)
# -----------------------------------------------------------------------------
def place_order(symbol: str, side: str, size_pct: float, leverage: int = 1, notional_usdt: Optional[float] = None):
    if notional_usdt is None:
        try:
            notional_usdt = float(
                CONFIG["executor"]["order_policy"].get("default_order", {}).get("notional_usdt", 50)
            )
        except Exception:
            notional_usdt = 50.0

    if not API_KEY or not API_SECRET:
        uid = f"SIM-{int(time.time())}"
        msg = f"🟢 EXECUTE {side} {symbol} (SIM) size={size_pct:.2f}% lev={leverage} uid={uid}"
        print(msg)
        try:
            from notifier.notify_telegram import send_telegram_message
            send_telegram_message(msg)
        except Exception:
            pass
        return {"order_uid": uid, "status": "SIMULATED", "client_order_id": uid}

    _ensure_leverage(symbol, leverage)
    qty = _compute_qty(symbol, float(notional_usdt))
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": f"{qty:.8f}"}
    try:
        resp = _post("/fapi/v1/order", params=params, signed=True)
    except Exception as e:
        uid = f"ERR-{int(time.time())}"
        msg = f"🔴 EXECUTE FAIL {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid} err={e}"
        print(msg)
        try:
            from notifier.notify_telegram import send_telegram_message
            send_telegram_message(msg)
        except Exception:
            pass
        return {"order_uid": uid, "status": "ERROR", "error": str(e)}

    uid_client = resp.get("clientOrderId") or f"CID-{int(time.time())}"
    msg = f"🟢 EXECUTE {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid_client}"
    print(msg)
    try:
        from notifier.notify_telegram import send_telegram_message
        send_telegram_message(msg)
    except Exception:
        pass
    return {"order_uid": uid_client, "client_order_id": uid_client, "order_id": resp.get("orderId"), "status": resp.get("status", "NEW")}

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
_STATE_FILE = ROOT / "executor_state.json"

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

def _guess_symbol() -> str:
    try:
        cen = CONFIG.get("central", {})  # type: ignore
        syms = cen.get("symbols") or cen.get("universe") or []
        if isinstance(syms, list) and syms:
            return str(syms[0])
    except Exception:
        pass
    return "BTCUSDT"

def _confidence_floor() -> Tuple[float, str]:
    # Ưu tiên ENV → CONFIG → 0.5
    envv = os.getenv("CRX_OPEN_CONF_FLOOR")
    if envv:
        try: return float(envv), "env"
        except: pass
    try:
        v = float(CONFIG.get("central", {}).get("min_confidence", 0.5))  # type: ignore
        return v, "config"
    except Exception:
        return 0.5, "default"

def run() -> None:
    if str(os.getenv("CRX_ENABLE_ORDER_EXECUTOR", "")).lower() not in ("1", "true", "yes"):
        print("[executor] disabled by env CRX_ENABLE_ORDER_EXECUTOR")
        return

    if _current_route() != "LEFT":
        print("[executor] skip: route!=LEFT (Phase B)")
        return

    dec = _read_last_decision()
    if not dec:
        print("[executor] no decision found (file/log)")
        return

    # dedupe theo timestamp
    st = _load_state()
    ts = dec.get("timestamp") or dec.get("ts")
    if ts and st.get("last_ts") == ts:
        print(f"[executor] skip duplicate decision ts={ts}")
        return

    conf = float(dec.get("confidence", 0.0) or 0.0)
    floor, src = _confidence_floor()
    if conf < floor:
        print(f"[executor] skip: confidence {conf:.2f} < floor {floor:.2f} (src={src})")
        return

    meta_action = (dec.get("meta_action") or dec.get("decision") or "WAIT").upper()
    if meta_action not in ("BUY", "SELL"):
        print("[executor] no actionable side:", meta_action)
        return

    symbol = dec.get("symbol") or _guess_symbol()
    size_pct = float(dec.get("suggested_size", 0.2))
    try:
        notional = float(CONFIG["executor"]["order_policy"].get("default_order", {}).get("notional_usdt", 50))
    except Exception:
        notional = 50.0

    res = place_order(symbol=symbol, side=meta_action, size_pct=size_pct, leverage=1, notional_usdt=notional)

    st["last_ts"] = ts
    st["last_order"] = {"symbol": symbol, "side": meta_action, "result": res}
    _save_state(st)

if __name__ == "__main__":
    run()
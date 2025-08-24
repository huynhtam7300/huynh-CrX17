# -*- coding: utf-8 -*-
# core/execution/order_executor.py
from __future__ import annotations

import os
import time
import hmac
import json
import hashlib
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlencode
from pathlib import Path

import requests

# ===== PATHS =====
ROOT = Path(__file__).resolve().parents[2]  # .../CrX17
DATA_DIR = ROOT / "data"
CONF_DIR = ROOT / "config"
LOGS_DIR = ROOT / "logs"

# ===== ENV / API =====
BINANCE_FUTURES_BASE = os.getenv("BINANCE_BASE_URL", "https://testnet.binancefuture.com")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})

# ===== Optional notifier =====
def _notify(msg: str) -> None:
    print(msg)
    try:
        from notifier.notify_telegram import send_telegram_message  # type: ignore
        send_telegram_message(msg)
    except Exception:
        pass

# ===== HTTP helpers =====
def _sign(params: Dict[str, Any]) -> str:
    query = urlencode(params, doseq=True)
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()

def _get(path: str, params: Dict[str, Any] | None = None, signed: bool = False, timeout: int = 10):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BINANCE_FUTURES_BASE + path
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _post(path: str, params: Dict[str, Any] | None = None, signed: bool = True, timeout: int = 10):
    params = dict(params or {})
    if signed:
        params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
        params["signature"] = _sign(params)
    url = BINANCE_FUTURES_BASE + path
    r = SESSION.post(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

# ===== Exchange info / qty =====
def _get_exchange_info(symbol: str) -> Dict[str, Any]:
    data = _get("/fapi/v1/exchangeInfo", signed=False)
    syms = {s["symbol"]: s for s in data.get("symbols", [])}
    if symbol not in syms:
        raise ValueError(f"{symbol} không có trên Binance Futures")
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

# ===== JSON/YAML utils =====
def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _read_last_decision() -> Optional[Dict[str, Any]]:
    """
    Ưu tiên đọc data/decision_history.json (mảng hoặc mỗi dòng một JSON).
    Fallback: data/last_decision.json, last_decision.json, data/decision_latest.json.
    Cuối cùng: parse logs/runner.log dòng '[decision] record: {...}'.
    """
    # history
    hist_path = DATA_DIR / "decision_history.json"
    if hist_path.exists():
        try:
            txt = hist_path.read_text(encoding="utf-8").strip()
            if txt:
                if txt.lstrip().startswith("["):
                    arr = json.loads(txt)
                    if isinstance(arr, list) and arr:
                        return arr[-1]
                else:
                    lines = [ln for ln in txt.splitlines() if ln.strip()]
                    if lines:
                        return json.loads(lines[-1])
        except Exception:
            pass
    # fallbacks
    for p in [DATA_DIR / "last_decision.json", ROOT / "last_decision.json", DATA_DIR / "decision_latest.json"]:
        obj = _read_json(p, default=None)
        if isinstance(obj, dict) and obj:
            return obj
    # parse log
    log_path = LOGS_DIR / "runner.log"
    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-800:]
        for line in reversed(lines):
            key = "[decision] record:"
            pos = line.find(key)
            if pos != -1:
                jstart = line.find("{", pos)
                if jstart != -1:
                    try:
                        return json.loads(line[jstart:].strip())
                    except Exception:
                        continue
    except Exception:
        pass
    return None

def _read_meta_route() -> str:
    st = _read_json(DATA_DIR / "meta_state.json", default={}) or {}
    return str(st.get("current_route") or "LEFT").upper()

def _left_conf_floor() -> float:
    try:
        import yaml
        cfg = yaml.safe_load((CONF_DIR / "left.yaml").read_text(encoding="utf-8")) or {}
        return float(cfg.get("signal_confidence_floor")
                     or (cfg.get("left_policy") or {}).get("signal_confidence_floor")
                     or 0.65)
    except Exception:
        return 0.65

def _get_notional_default() -> float:
    try:
        import yaml
        ex = yaml.safe_load((CONF_DIR / "executor.yaml").read_text(encoding="utf-8")) or {}
        return float((ex.get("order_policy") or {}).get("default_order", {}).get("notional_usdt", 50))
    except Exception:
        return 50.0

def _get_brackets_cfg() -> Tuple[float, float, str]:
    """
    Đọc sl/tp từ config/executor.yaml (nếu có).
    Trả về: (sl_pct, tp_pct, working_type)
    """
    try:
        import yaml
        ex = yaml.safe_load((CONF_DIR / "executor.yaml").read_text(encoding="utf-8")) or {}
        pol = (ex.get("order_policy") or {})
        slp = float(pol.get("sl_pct", 0) or 0)
        tpp = float(pol.get("tp_pct", 0) or 0)
        wkt = str(pol.get("working_type", "MARK_PRICE")).upper()
        if wkt not in ("MARK_PRICE", "CONTRACT_PRICE", "LAST_PRICE"):
            wkt = "MARK_PRICE"
        return slp, tpp, wkt
    except Exception:
        return 0.0, 0.0, "MARK_PRICE"

# ===== Position helpers =====
def _get_position(symbol: str) -> Tuple[float, float]:
    """
    Trả về (positionAmt, entryPrice).
    Dương = long, âm = short; 0 = không có vị thế.
    """
    try:
        arr = _get("/fapi/v2/positionRisk", params={"symbol": symbol}, signed=True)
        items = arr if isinstance(arr, list) else [arr]
        for it in items:
            if str(it.get("symbol")) == symbol:
                amt = float(it.get("positionAmt", 0) or 0)
                entry = float(it.get("entryPrice", 0) or 0)
                return amt, entry
    except Exception:
        pass
    return 0.0, 0.0

def close_position(symbol: str) -> Dict[str, Any]:
    """
    Đóng toàn bộ vị thế hiện tại bằng lệnh MARKET reduceOnly.
    """
    pos_amt, _ = _get_position(symbol)
    if abs(pos_amt) < 1e-12:
        print("[executor] close_position: no position")
        return {"status": "NO_POSITION"}

    side = "SELL" if pos_amt > 0 else "BUY"
    qty = abs(pos_amt)
    try:
        resp = _post("/fapi/v1/order",
                     params={"symbol": symbol, "side": side, "type": "MARKET",
                             "quantity": f"{qty:.8f}", "reduceOnly": "true"},
                     signed=True)
        _notify(f"🧹 CLOSE {symbol} qty={qty:.8f} side={side} (reduceOnly)")
        return {"status": "OK", "resp": resp}
    except Exception as e:
        print("[executor] close_position error:", e)
        _notify(f"🔴 CLOSE FAIL {symbol} qty={qty:.8f} side={side} err={e}")
        return {"status": "ERROR", "error": str(e)}

def _set_brackets(symbol: str, sl_pct: float, tp_pct: float, working_type: str = "MARK_PRICE") -> Optional[Dict[str, Any]]:
    """
    Đặt TP/SL trên sàn bằng STOP_MARKET/TAKE_PROFIT_MARKET closePosition=true.
    Cần có vị thế (đã khớp) để lấy entryPrice.
    """
    if sl_pct <= 0 and tp_pct <= 0:
        return None

    pos_amt, entry = _get_position(symbol)
    if abs(pos_amt) < 1e-12 or entry <= 0:
        return None

    long = pos_amt > 0
    sl = entry * (1 - sl_pct) if long else entry * (1 + sl_pct)
    tp = entry * (1 + tp_pct) if long else entry * (1 - tp_pct)

    out = {}
    try:
        # SL
        if sl_pct > 0:
            out["sl"] = _post("/fapi/v1/order",
                              params={"symbol": symbol, "side": "SELL" if long else "BUY",
                                      "type": "STOP_MARKET", "stopPrice": f"{sl:.2f}",
                                      "closePosition": "true", "workingType": working_type},
                              signed=True)
        # TP
        if tp_pct > 0:
            out["tp"] = _post("/fapi/v1/order",
                              params={"symbol": symbol, "side": "SELL" if long else "BUY",
                                      "type": "TAKE_PROFIT_MARKET", "stopPrice": f"{tp:.2f}",
                                      "closePosition": "true", "workingType": working_type},
                              signed=True)
        _notify(f"🧷 Brackets set {symbol}: SL@{sl:.2f} TP@{tp:.2f} (mode={working_type})")
    except Exception as e:
        _notify(f"🔴 Brackets fail {symbol}: {e}")
    return out

# ===== Place order =====
def place_order(symbol: str, side: str, size_pct: float, leverage: int = 1, notional_usdt: float | None = None):
    """
    Đặt MARKET trên Binance Futures.
    Nếu thiếu API key/secret -> chạy mô phỏng (SIMULATED).
    """
    # SIM mode
    if not API_KEY or not API_SECRET:
        uid = f"SIM-{int(time.time())}"
        _notify(f"🟢 EXECUTE {side} {symbol} (SIM) size={size_pct:.2f}% lev={leverage} uid={uid}")
        return {"order_uid": uid, "status": "SIMULATED", "client_order_id": uid}

    if notional_usdt is None:
        notional_usdt = _get_notional_default()

    _ensure_leverage(symbol, leverage)
    qty = _compute_qty(symbol, float(notional_usdt))

    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": f"{qty:.8f}"}
    try:
        resp = _post("/fapi/v1/order", params=params, signed=True)
    except Exception as e:
        uid = f"ERR-{int(time.time())}"
        _notify(f"🔴 EXECUTE FAIL {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid} err={e}")
        return {"order_uid": uid, "status": "ERROR", "error": str(e)}

    uid_client = resp.get("clientOrderId") or f"CID-{int(time.time())}"
    _notify(f"🟢 EXECUTE {side} {symbol} QTY={qty} (~{notional_usdt} USDT) lev={leverage} uid={uid_client}")
    return {
        "order_uid": uid_client,
        "client_order_id": uid_client,
        "order_id": resp.get("orderId"),
        "status": resp.get("status", "NEW"),
        "cumQty": resp.get("executedQty", "0"),
        "avgPrice": resp.get("avgPrice", "0"),
    }

# ===== ENTRYPOINT =====
_STATE_FILE = DATA_DIR / "executor_state.json"

def _load_state() -> Dict[str, Any]:
    return _read_json(_STATE_FILE, default={}) or {}

def _save_state(st: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _guess_symbol() -> str:
    # Ưu tiên central.yaml
    try:
        import yaml
        cen = yaml.safe_load((CONF_DIR / "central.yaml").read_text(encoding="utf-8")) or {}
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

    # Gate theo Meta-Controller (Phase B chỉ cho LEFT hoạt động)
    route = _read_meta_route()
    if route != "LEFT":
        print(f"[executor] skip: route={route} (Phase B chỉ thực thi khi route=LEFT)")
        return

    dec = _read_last_decision()
    if not dec:
        print("[executor] no decision found")
        return

    # Hỗ trợ meta_action=CLOSE để chốt vị thế
    base_decision = (dec.get("decision") or "").upper()
    meta_action = (dec.get("meta_action") or base_decision).upper()

    if meta_action == "CLOSE":
        symbol = dec.get("symbol") or _guess_symbol()
        close_position(symbol)
        st = _load_state()
        st["last_ts"] = dec.get("timestamp") or dec.get("ts") or time.time()
        st["last_order"] = {"symbol": symbol, "side": "CLOSE", "result": {"status": "OK"}}
        _save_state(st)
        return

    if meta_action not in ("BUY", "SELL"):
        print("[executor] no actionable side in decision (need BUY/SELL/CLOSE)")
        return

    # tránh trùng theo timestamp
    ts_value = dec.get("timestamp") or dec.get("ts")
    st = _load_state()
    if ts_value and st.get("last_ts") == ts_value:
        print("[executor] skip duplicate decision ts=", ts_value)
        return

    # ngưỡng tin cậy
    try:
        conf = float(dec.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    floor = _left_conf_floor()
    if conf < floor:
        print(f"[executor] skip: confidence {conf:.2f} < floor {floor:.2f}")
        return

    symbol = dec.get("symbol") or _guess_symbol()
    size_pct = float(dec.get("suggested_size", 0.2))
    notional = _get_notional_default()

    # Đặt lệnh
    res = place_order(symbol=symbol, side=meta_action, size_pct=size_pct, leverage=1, notional_usdt=notional)

    # Đặt brackets nếu có trong config
    sl_pct, tp_pct, wtype = _get_brackets_cfg()
    if (sl_pct > 0) or (tp_pct > 0):
        try:
            _set_brackets(symbol, sl_pct=sl_pct, working_type=wtype, tp_pct=tp_pct)
        except Exception as e:
            print("[executor] bracket warn:", e)

    # Lưu trạng thái
    st["last_ts"] = ts_value or time.time()
    st["last_order"] = {"symbol": symbol, "side": meta_action, "result": res}
    _save_state(st)

if __name__ == "__main__":
    run()
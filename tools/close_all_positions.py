# tools/close_all_positions.py
# Đóng tất cả vị thế USDT-M Futures (Testnet/Prod) bằng lệnh MARKET reduceOnly và CHỜ FILLED
from __future__ import annotations
import os, time, hmac, hashlib, requests, argparse
from urllib.parse import urlencode
from decimal import Decimal, getcontext

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

getcontext().prec = 18

API_KEY    = (os.getenv("BINANCE_API_KEY") or "").strip()
API_SECRET = (os.getenv("BINANCE_API_SECRET") or "").strip()
BASE       = (os.getenv("BINANCE_FAPI_BASE") or "https://testnet.binancefuture.com").strip()
RECV       = int(os.getenv("BINANCE_RECVWINDOW", "5000"))
SYMBOLS_ENV = os.getenv("CRX_SYMBOLS", "BTCUSDT,ETHUSDT")

def _mask(s: str) -> str: return f"{s[:4]}...{s[-4:]}" if s and len(s) > 8 else s
def _ts(): return int(time.time() * 1000)
def _headers(): return {"X-MBX-APIKEY": API_KEY}
def _sign(params: dict) -> str:
    q = urlencode(params, doseq=True)
    sig = hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    return f"{q}&signature={sig}"

def _get(path: str, params: dict = None):
    params = params or {}
    url = f"{BASE}{path}?{urlencode(params)}" if params else f"{BASE}{path}"
    r = requests.get(url, headers=_headers(), timeout=10); r.raise_for_status(); return r.json()

def _get_signed(path: str, params: dict):
    params = dict(params or {}); params.update({"timestamp": _ts(), "recvWindow": RECV})
    url = f"{BASE}{path}?{_sign(params)}"
    r = requests.get(url, headers=_headers(), timeout=10); r.raise_for_status(); return r.json()

def _post_signed(path: str, params: dict):
    params = dict(params or {}); params.update({"timestamp": _ts(), "recvWindow": RECV})
    body = _sign(params); url  = f"{BASE}{path}"
    r = requests.post(url, headers=_headers(), data=body, timeout=10)
    ok = r.status_code == 200
    try: js = r.json()
    except Exception: js = r.text
    print(f"[order] {path} status={r.status_code} ok={ok} resp={str(js)[:240]}")
    r.raise_for_status(); return js

def query_order(symbol: str, order_id: int):
    return _get_signed("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

def _step_size_map():
    info = _get("/fapi/v1/exchangeInfo"); out = {}
    for s in info.get("symbols", []):
        sym = s["symbol"]; step = None
        for f in s.get("filters", []):
            if f.get("filterType") == "LOT_SIZE": step = f.get("stepSize"); break
        if step: out[sym] = Decimal(step)
    return out

def _round_qty(q: Decimal, step: Decimal) -> Decimal:
    return (q // step) * step if step != 0 else q

def get_open_positions():
    pos = _get_signed("/fapi/v2/positionRisk", {}); out = {}
    for p in pos:
        amt = Decimal(p.get("positionAmt", "0"))
        if amt != 0: out[p["symbol"]] = amt
    return out

def close_symbol(sym: str, amt: Decimal, step_map: dict, dry: bool, wait_sec: float):
    side = "SELL" if amt > 0 else "BUY"
    qty  = abs(amt); step = step_map.get(sym, Decimal("0.001"))
    qty_rounded = _round_qty(qty, step)
    if qty_rounded <= 0:
        print(f"[skip] {sym} qty quá nhỏ: {qty} (step={step})"); return

    print(f"[close] {sym} side={side} qty={qty_rounded} reduceOnly=True dry={dry}")
    if dry: return

    # Đặt MARKET reduceOnly, yêu cầu trả về RESULT để có thêm thông tin
    res = _post_signed("/fapi/v1/order", {
        "symbol": sym, "side": side, "type": "MARKET",
        "quantity": str(qty_rounded),
        "reduceOnly": "true",
        "newClientOrderId": f"crx-close-{int(time.time())}",
        "newOrderRespType": "RESULT",
    })
    order_id = int(res.get("orderId"))

    # Chờ đến khi FILLED/CANCELED/REJECTED/EXPIRED hoặc hết thời gian
    if wait_sec > 0:
        deadline = time.time() + wait_sec
        last_status = res.get("status")
        while time.time() < deadline:
            od = query_order(sym, order_id)
            st = od.get("status")
            if st != last_status:
                print(f"[order] {sym} order {order_id} status={st} exec={od.get('executedQty')}")
                last_status = st
            if st in ("FILLED", "CANCELED", "REJECTED", "EXPIRED"): break
            time.sleep(0.25)

def ping_keys():
    try:
        _get_signed("/fapi/v2/balance", {}); return True
    except requests.HTTPError as e:
        print(f"[auth] HTTPError: {e.response.status_code} {e.response.text[:160]}"); return False
    except Exception as e:
        print(f"[auth] Lỗi: {e}"); return False

def main():
    ap = argparse.ArgumentParser(description="Đóng tất cả vị thế USDT-M Futures (reduceOnly)")
    ap.add_argument("--symbols", default=SYMBOLS_ENV, help="VD: BTCUSDT,ETHUSDT")
    ap.add_argument("--dryrun", action="store_true", help="Chỉ in thao tác, KHÔNG gửi lệnh")
    ap.add_argument("--wait", type=float, default=5, help="Số giây chờ order về FILLED (mặc định 5)")
    args = ap.parse_args()

    print(f"🐍 Close All | base={BASE}")
    print(f"[env] KEY={_mask(API_KEY)} SECRET={_mask(API_SECRET)}")
    if not API_KEY or not API_SECRET:
        print("❌ Thiếu BINANCE_API_KEY/BINANCE_API_SECRET trong .env"); return
    if not ping_keys():
        print("❌ Không xác thực được API key/secret. Kiểm tra đúng Testnet/Prod và đã bật Futures."); return

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    step_map = _step_size_map()
    open_pos = get_open_positions()
    if not open_pos:
        print("✅ Không có vị thế mở."); return

    print(f"[open] {open_pos}")
    for sym in symbols:
        if sym in open_pos:
            close_symbol(sym, Decimal(open_pos[sym]), step_map, args.dryrun, args.wait)
        else:
            print(f"[info] Không có vị thế ở {sym}.")

    # Kiểm tra lại
    time.sleep(0.5)
    remain = get_open_positions()
    print(f"[remain] {remain if remain else '0 vị thế còn lại'}")
    print("🎯 Hoàn tất.")

if __name__ == "__main__":
    main()
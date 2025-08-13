# tools/health_check.py
# CrX 1.7 – Health Check (24h readiness)
from __future__ import annotations
import os, hmac, hashlib, time, json, argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOGS = ROOT / "logs"
DATA.mkdir(exist_ok=True); LOGS.mkdir(exist_ok=True)

API_KEY    = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BASE       = os.getenv("BINANCE_BASE_URL", "https://testnet.binancefuture.com").rstrip("/")

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def ms() -> int:
    return int(time.time() * 1000)

def sign_params(params: dict) -> str:
    # Build query string sorted
    qs = "&".join([f"{k}={params[k]}" for k in sorted(params.keys())])
    sig = hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return qs + "&signature=" + sig

def get_public(path: str, params=None):
    url = f"{BASE}{path}"
    r = requests.get(url, params=params or {}, timeout=10)
    r.raise_for_status()
    return r.json()

def get_signed(path: str, params: dict):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Thiếu BINANCE_API_KEY/SECRET trong .env")
    # add timestamp
    params = dict(params or {})
    params["timestamp"] = ms()
    params.setdefault("recvWindow", 5000)
    qs = sign_params(params)
    url = f"{BASE}{path}?{qs}"
    headers = {"X-MBX-APIKEY": API_KEY}
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def file_age_minutes(p: Path) -> float:
    if not p.exists(): return 1e9
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()/60.0
    return age

def check_ping():
    try:
        get_public("/fapi/v1/ping")
        return True, "Ping OK"
    except Exception as e:
        return False, f"Ping fail: {e}"

def check_income(hours: int = 24):
    try:
        start = int((time.time() - hours*3600)*1000)
        data = get_signed("/fapi/v1/income", {
            "incomeType": "REALIZED_PNL",
            "startTime": start,
            "limit": 1000
        })
        # Sum last 24h
        incomes = [float(x.get("income", 0)) for x in data if x.get("incomeType")=="REALIZED_PNL"]
        last_t   = max([int(x["time"]) for x in data], default=None)
        last_iso = datetime.utcfromtimestamp(last_t/1000).isoformat()+"Z" if last_t else "-"
        return True, f"Income records={len(incomes)}, sum24h={sum(incomes):.4f}, last={last_iso}"
    except Exception as e:
        return False, f"Income fail: {e}"

def check_positions():
    try:
        pos = get_signed("/fapi/v2/positionRisk", {})
        opn = []
        for x in pos:
            amt = float(x.get("positionAmt", 0) or 0)
            if abs(amt) > 1e-12:
                opn.append((x.get("symbol",""), amt))
        if opn:
            return False, f"Đang có vị thế mở: {opn}"
        return True, "Không có vị thế mở"
    except Exception as e:
        return False, f"positionRisk fail: {e}"

def check_files_fresh():
    p_sum  = DATA / "pnl_summary.json"
    p_raw  = DATA / "pnl_income_raw.json"
    p_dec  = DATA / "decision_history.json"
    a_sum = file_age_minutes(p_sum)
    a_raw = file_age_minutes(p_raw)
    a_dec = file_age_minutes(p_dec)
    ok = (a_sum <= 30) and (a_raw <= 30) and (a_dec <= 180)  # dec không nhất thiết 15' 1 lần
    msg = (f"pnl_summary age={a_sum:.1f}m, pnl_income_raw age={a_raw:.1f}m, "
           f"decision_history age={a_dec:.1f}m")
    return ok, msg

def analyze_decisions(hours: int=24):
    p_dec = DATA / "decision_history.json"
    obj = read_json(p_dec) or []
    if not isinstance(obj, list): return False, "decision_history.json không phải list."
    # lọc 24h
    cutoff = now_utc() - timedelta(hours=hours)
    ts_list=[]
    for r in obj:
        ts = r.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts.replace("Z","+00:00")) if ts else None
        except Exception:
            dt = None
        if dt and dt >= cutoff:
            ts_list.append(dt)
    ts_list.sort()
    if len(ts_list) < 3:
        return False, f"Quyết định 24h={len(ts_list)} (<3)."
    gaps = [(t2 - t1).total_seconds()/60.0 for t1,t2 in zip(ts_list, ts_list[1:])]
    gaps.sort()
    med = gaps[len(gaps)//2]
    msg = f"Decisions24h={len(ts_list)}, median_gap≈{med:.1f} phút (kỳ vọng ≈ CRX_LOOP_MINUTES/ cooldown)."
    # Kiểm tra cooldown/tick quá dày? nếu min_gap < 1 phút coi là spam
    spam = min(gaps) < 1.0
    return (not spam), (msg + (f" | ⚠️ min_gap={min(gaps):.2f}m" if spam else ""))

def scan_log_errors():
    log = LOGS / "runner.log"
    if not log.exists():
        return True, "Không thấy logs/runner.log (bỏ qua)."
    try:
        text = log.read_text(encoding="utf-8", errors="ignore")[-200000:]  # tail ~200KB
        bad = 0
        for key in ["❌","Traceback","ERROR"]:
            bad += text.count(key)
        if bad==0:
            return True, "Log tail OK (0 lỗi)."
        else:
            return False, f"Log tail có {bad} lỗi (❌/ERROR/Traceback)."
    except Exception as e:
        return False, f"Đọc log lỗi: {e}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24, help="Khoảng thời gian để kiểm tra")
    args = ap.parse_args()

    print(f"CrX Health Check | base={BASE} | window={args.hours}h")
    results = []

    # 1) ENV
    env_ok = bool(API_KEY and API_SECRET)
    results.append(("ENV", env_ok, "Có API KEY/SECRET" if env_ok else "Thiếu BINANCE_API_KEY/SECRET"))

    # 2) Ping
    results.append(("PING", *check_ping()))

    # 3) Income (signed)
    results.append(("INCOME", *check_income(args.hours)))

    # 4) Positions
    results.append(("POSITIONS", *check_positions()))

    # 5) Files freshness
    results.append(("FILES", *check_files_fresh()))

    # 6) Decisions cadence
    results.append(("DECISIONS", *analyze_decisions(args.hours)))

    # 7) Logs
    results.append(("LOGS", *scan_log_errors()))

    # Print
    ok_all = True
    print("\n== KẾT QUẢ ==")
    for name, ok, msg in results:
        mark = "✅" if ok else "❌"
        print(f"[{mark}] {name}: {msg}")
        ok_all = ok_all and ok

    print("\n== KẾT LUẬN ==")
    if ok_all:
        print("✅ READY: Có thể vận hành dài hạn và chuyển lên VPS.")
    else:
        print("⚠️ NOT READY: Vui lòng xử lý các mục ❌ trước khi triển khai.")

if __name__ == "__main__":
    main()
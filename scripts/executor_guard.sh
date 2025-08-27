#!/usr/bin/env bash
# scripts/executor_guard.sh
set -euo pipefail

cd /home/crx/CrX17
source .venv/bin/activate

# 1) Áp dụng gate/ép symbol (nếu có nguồn)
python tools/append_latest_and_export.py || true

# 2) Chỉ cho Executor chạy khi decision mới & đạt floor
python - "$@" <<'PY'
import os, json, sys, time
from datetime import datetime, timezone

ROOT = "/home/crx/CrX17"
fn = os.path.join(ROOT, "last_decision.json")

open_floor  = float(os.getenv("CRX_OPEN_CONF_FLOOR", "0.65"))
close_floor = float(os.getenv("CRX_CLOSE_CONF_FLOOR", "0.60"))
fresh_sec   = int(os.getenv("CRX_DECISION_FRESH_SEC", "900"))  # 15 phút

def parse_ts(s):
    try:
        if s.endswith("Z"): s = s.replace("Z","+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None

if not os.path.exists(fn):
    print("[guard] no last_decision.json -> skip")
    sys.exit(2)

dec = json.load(open(fn, encoding="utf-8"))
conf = float(dec.get("confidence") or 0.0)
sym  = dec.get("symbol") or "N/A"
is_close = any(k in str(dec.get("meta_action","")).upper() for k in ("CLOSE","FLIP")) \
           or str(dec.get("decision","")).upper().startswith(("CLOSE","FLIP"))
floor = close_floor if is_close else open_floor

ts = parse_ts(dec.get("timestamp",""))
age = None if ts is None else (time.time() - ts.timestamp())
fresh = (age is not None) and (age <= fresh_sec)

if conf < floor:
    print(f"[guard] skip: confidence {conf:.2f} < floor {floor:.2f}")
    sys.exit(3)
if not fresh:
    print(f"[guard] skip: stale decision age={int(age or 1e9)}s > {fresh_sec}s")
    sys.exit(4)

print(f"[guard] pass: conf={conf:.2f} floor={floor:.2f} sym={sym}")
sys.exit(0)
PY

case $? in
  0)  python -m core.execution.order_executor ;;
  *)  exit 0 ;;
esac
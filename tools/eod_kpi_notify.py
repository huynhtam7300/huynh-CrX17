cat > tools/eod_kpi_notify.py <<'PY'
from __future__ import annotations
import sys, pathlib, json, datetime as dt
# cho phép import notifier/**
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
UTC = getattr(dt, "UTC", dt.timezone.utc)

from notifier.notify_telegram import send_telegram_message

root    = pathlib.Path(__file__).resolve().parents[1]
p_pnl   = root / "data" / "pnl_summary.json"
p_hist  = root / "data" / "decision_history.jsonl"
p_state = root / "data" / "meta_state.json"
LOCK    = root / "data" / ".eod_kpi_lock"

def load_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def count_today(hist_path: pathlib.Path) -> int:
    if not hist_path.exists():
        return 0
    today = dt.datetime.now(UTC).date().isoformat()
    n = 0
    for ln in hist_path.read_text(encoding="utf-8").splitlines():
        try:
            o = json.loads(ln)
            if str(o.get("timestamp","")).startswith(today) and o.get("decision") in ("BUY","SELL"):
                n += 1
        except Exception:
            pass
    return n

def _can_send_today() -> bool:
    today = dt.datetime.now(UTC).date().isoformat()
    try:
        last = LOCK.read_text(encoding="utf-8").strip()
        if last == today:
            return False
    except Exception:
        pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(today, encoding="utf-8")
    return True

def main():
    if not _can_send_today():
        print("[eod_kpi] already sent today")
        return

    pnl  = load_json(p_pnl)
    st   = load_json(p_state)

    trades   = pnl.get("total_trades","?")
    wins     = pnl.get("wins","?")
    losses   = pnl.get("losses","?")
    realized = pnl.get("realized_pnl_sum","?")
    tday     = count_today(p_hist)
    route    = st.get("current_route","?")

    msg = (f"📊 EOD KPI\n"
           f"- Route: {route}\n"
           f"- Trades(30d): {trades} | W/L: {wins}/{losses} | Realized PnL: {realized}\n"
           f"- Decisions today: {tday}")

    try:
        send_telegram_message(msg)
        print("[eod_kpi] sent")
    except Exception as e:
        print("[eod_kpi] fail:", e)

if __name__ == "__main__":
    main()
PY
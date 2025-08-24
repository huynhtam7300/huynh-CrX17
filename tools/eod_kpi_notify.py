#!/usr/bin/env python3
from __future__ import annotations
import sys, pathlib, json, datetime as dt

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from notifier.notify_telegram import send_telegram_message  # noqa: E402

UTC = getattr(dt, "UTC", dt.timezone.utc)

P_PNL   = ROOT / "data" / "pnl_summary.json"
P_HIST  = ROOT / "data" / "decision_history.jsonl"
P_STATE = ROOT / "data" / "meta_state.json"
P_LOCK  = ROOT / "data" / ".eod_kpi_lock"

def _load_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _count_today(hist_path: pathlib.Path) -> int:
    if not hist_path.exists():
        return 0
    today = dt.datetime.now(UTC).date().isoformat()
    n = 0
    for ln in hist_path.read_text(encoding="utf-8").splitlines():
        try:
            o = json.loads(ln)
            ts = str(o.get("timestamp", ""))
            if ts.startswith(today) and o.get("decision") in ("BUY", "SELL"):
                n += 1
        except Exception:
            continue
    return n

def _can_send_today() -> bool:
    today = dt.datetime.now(UTC).date().isoformat()
    try:
        if P_LOCK.exists() and P_LOCK.read_text(encoding="utf-8").strip() == today:
            return False
    except Exception:
        pass
    P_LOCK.parent.mkdir(parents=True, exist_ok=True)
    P_LOCK.write_text(today, encoding="utf-8")
    return True

def main():
    if not _can_send_today():
        print("[eod_kpi] already sent today")
        return

    pnl = _load_json(P_PNL)
    st  = _load_json(P_STATE)
    trades   = pnl.get("total_trades", "?")
    wins     = pnl.get("wins", "?")
    losses   = pnl.get("losses", "?")
    realized = pnl.get("realized_pnl_sum", "?")
    tday     = _count_today(P_HIST)
    route    = st.get("current_route", "?")

    msg = (
        "📊 EOD KPI\n"
        f"- Route: {route}\n"
        f"- Trades(30d): {trades} | W/L: {wins}/{losses} | Realized PnL: {realized}\n"
        f"- Decisions today: {tday}"
    )

    try:
        send_telegram_message(msg)
        print("[eod_kpi] sent")
    except Exception as e:
        print("[eod_kpi] fail:", e)

if __name__ == "__main__":
    main()
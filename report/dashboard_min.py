# -*- coding: utf-8 -*-
"""
CrX 1.7 – Dashboard (Minimal, nâng cấp)
- KPI từ data/pnl_summary.json (REALIZED_PNL).
- Biểu đồ Equity/PnL & Bảng lệnh đã đóng từ data/pnl_income_raw.json.
- Lọc symbol + khoảng ngày, tải CSV.
- Equity có offset từ .env: CRX_PNL_INIT (tuỳ chọn).
- Hiển thị quyết định gần nhất từ data/decision_history.json.
- Điều khiển runner qua cờ: reload / stop / riskoff / resume / closeall.
"""
from __future__ import annotations
import os, json
from pathlib import Path
from datetime import datetime, timedelta, timezone, date
import pandas as pd
import streamlit as st

# ========= ENV & PATH =========
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

ROOT     = Path(__file__).resolve().parents[1]   # .../CrX17
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
FLAG_DIR = Path(os.getenv("CRX_FLAG_DIR", str(ROOT))).resolve()
DATA_DIR.mkdir(exist_ok=True); LOGS_DIR.mkdir(exist_ok=True)

DECISION_FILE     = DATA_DIR / "decision_history.json"
PNL_SUMMARY_FILE  = DATA_DIR / "pnl_summary.json"
PNL_INCOME_RAW    = DATA_DIR / "pnl_income_raw.json"

PNL_INIT = float(os.getenv("CRX_PNL_INIT", "0") or 0.0)  # vốn khởi điểm (tuỳ chọn)

# ========= TIỆN ÍCH =========
def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def read_decisions() -> list[dict]:
    if not DECISION_FILE.exists(): return []
    txt = DECISION_FILE.read_text(encoding="utf-8", errors="ignore")
    try:
        obj = json.loads(txt);  return obj if isinstance(obj, list) else [obj]
    except Exception:
        rows=[]
        for line in txt.splitlines():
            line=line.strip()
            if not line: continue
            try: rows.append(json.loads(line))
            except Exception: pass
        return rows

def to_dt(s: str):
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception: return None

def fmt0(x, n=4):
    try: return f"{float(x):.{n}f}"
    except Exception: return str(x)

def filter_by_minutes(rows: list[dict], minutes: int) -> list[dict]:
    if minutes <= 0: return rows
    now = datetime.now(timezone.utc); start = now - timedelta(minutes=minutes)
    out=[]
    for r in rows:
        d = to_dt(r.get("timestamp") or r.get("time") or "")
        if d and d >= start: out.append(r)
    return out

def create_flag(name: str, note: str = ""):
    p = FLAG_DIR / name
    try:
        with p.open("w", encoding="utf-8") as f:
            if note: f.write(f"[{datetime.now().isoformat(timespec='seconds')}]\n{note}\n")
        return True, f"Đã tạo {name}."
    except Exception as e:
        return False, f"Lỗi tạo {name}: {e}"

def remove_flag(name: str):
    p = FLAG_DIR / name
    try:
        if p.exists(): p.unlink()
        return True, f"Đã xoá {name}."
    except Exception as e:
        return False, f"Lỗi xoá {name}: {e}"

# ========= SIDEBAR =========
st.set_page_config(page_title="CrX 1.7 – Dashboard (Minimal)", page_icon="📊", layout="wide")

with st.sidebar:
    st.header("Cấu hình xem")
    auto = st.toggle("Tự động refresh", value=False)
    interval = st.number_input("Khoảng refresh (giây)", 5, 600, 60, 5)
    n_rows = st.number_input("Số dòng hiển thị (bảng quyết định)", 10, 500, 50, 10)
    lookback_min = st.number_input("Nhìn lại (phút) để lọc quyết định", 0, 10080, 240, 60)

    st.markdown("---")
    st.subheader("Bộ lọc PnL")
    _raw = read_json(PNL_INCOME_RAW) or []
    _df0 = pd.DataFrame(_raw) if isinstance(_raw, list) and _raw else pd.DataFrame()
    if not _df0.empty:
        _df0 = _df0[_df0.get("incomeType","") == "REALIZED_PNL"].copy()
        if not _df0.empty:
            _df0["time"] = pd.to_datetime(_df0["time"], unit="ms", utc=True)
            _symbols = sorted([s for s in _df0.get("symbol","").dropna().unique().tolist() if s])
            selected_symbols = st.multiselect("Symbol", _symbols, default=_symbols)
            min_d = _df0["time"].min().date()
            max_d = _df0["time"].max().date()
        else:
            selected_symbols = []
            min_d = date.today() - timedelta(days=30)
            max_d = date.today()
    else:
        selected_symbols = []
        min_d = date.today() - timedelta(days=30)
        max_d = date.today()

    default_start = max_d - timedelta(days=30)
    dr = st.date_input("Khoảng ngày", (default_start, max_d))
    if isinstance(dr, tuple) and len(dr) == 2:
        start_d, end_d = dr
    else:
        start_d, end_d = default_start, max_d

    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh  # type: ignore
            st_autorefresh(interval=interval*1000, key="crx_auto")
        except Exception:
            pass

st.title("📊 CrX 1.7 – Dashboard (Minimal)")
st.caption("Dashboard Minimal (chế độ xem). Không can thiệp pipeline. © 2025")

# ========= KPI & PnL =========
st.subheader("📈 KPI & PnL")
pnl = read_json(PNL_SUMMARY_FILE) or {}
total_trades = int(pnl.get("total_trades", 0) or 0)
wins = int(pnl.get("wins", 0) or 0)
losses = int(pnl.get("losses", 0) or 0)
pnl_sum = float(pnl.get("realized_pnl_sum", 0) or 0.0)
avg_pnl = float(pnl.get("avg_pnl_per_trade", 0) or 0.0)
winrate = (wins/total_trades*100.0) if total_trades else 0.0
last_trade = pnl.get("last_trade_time") or "-"

c1,c2,c3,c4,c5 = st.columns([1.2,1,1,1,1])
c1.metric("Tổng số lệnh (đã đóng)", f"{total_trades}")
c2.metric("Winrate (%)", fmt0(winrate,1))
c3.metric("PnL lũy kế", fmt0(pnl_sum,4))
c4.metric("PnL TB/đơn", fmt0(avg_pnl,4))
c5.metric("Giao dịch gần nhất", last_trade)
st.caption(f"Nguồn KPI: {PNL_SUMMARY_FILE} {'✅' if PNL_SUMMARY_FILE.exists() else '—'} "
           f"(REALIZED_PNL từ sàn). Equity offset=CRX_PNL_INIT={fmt0(PNL_INIT,2)}")

# ========= BIỂU ĐỒ EQUITY / PnL =========
st.subheader("📈 Equity / PnL theo thời gian")
if not PNL_INCOME_RAW.exists():
    st.info("Chưa có dữ liệu `pnl_income_raw.json`. Hãy đợi runner chạy `pnl_sync` hoặc chạy tay: `python -m core.evaluator.pnl_sync`.")
else:
    raw = read_json(PNL_INCOME_RAW) or []
    if not isinstance(raw, list) or not raw:
        st.info("`pnl_income_raw.json` chưa có dữ liệu phù hợp.")
    else:
        df = pd.DataFrame(raw)
        df = df[(df.get("incomeType","") == "REALIZED_PNL")].copy()
        if df.empty:
            st.info("Không có khoản PnL REALIZED_PNL.")
        else:
            df["income"] = pd.to_numeric(df["income"], errors="coerce").fillna(0.0)
            df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
            df["symbol"] = df.get("symbol", "").astype(str)

            # Áp bộ lọc symbol + khoảng ngày
            if selected_symbols:
                df = df[df["symbol"].isin(selected_symbols)]
            start_ts = pd.Timestamp(start_d, tz="UTC")
            end_ts   = pd.Timestamp(end_d + timedelta(days=1), tz="UTC") - pd.Timedelta(microseconds=1)
            df = df[(df["time"] >= start_ts) & (df["time"] <= end_ts)].copy()

            if df.empty:
                st.info("Không có khoản PnL sau khi áp bộ lọc.")
            else:
                df.sort_values("time", inplace=True)
                df["equity"] = PNL_INIT + df["income"].cumsum()
                st.line_chart(df.set_index("time")[["equity","income"]], use_container_width=True)
                st.caption(
                    f"Nguồn PnL: {PNL_INCOME_RAW} ✅ | Symbol={', '.join(selected_symbols) if selected_symbols else 'ALL'} | "
                    f"Khoảng: {start_d.isoformat()} → {end_d.isoformat()} | Offset={fmt0(PNL_INIT,2)}"
                )

                # ----- Bảng lệnh đã đóng (đÃ FIX) -----
                st.markdown("### 🔒 Lệnh đã đóng (REALIZED_PNL)")
                try:
                    view = df.rename(columns={"time":"closed_at","income":"realized_pnl"})
                    desired = ["closed_at","symbol","realized_pnl","asset","info","tranId","tradeId"]
                    # chọn cột dựa trên view.columns (sau rename)
                    view_cols = [c for c in desired if c in view.columns]
                    view = view[view_cols].sort_values("closed_at", ascending=False)
                    if "realized_pnl" in view.columns:
                        view["realized_pnl"] = view["realized_pnl"].map(lambda x: float(x))
                    st.dataframe(view, use_container_width=True, hide_index=True)
                    csv = view.to_csv(index=False).encode("utf-8")
                    st.download_button("⬇️ Tải CSV (bản đã lọc)", data=csv,
                                       file_name="closed_trades_filtered.csv", mime="text/csv")
                except Exception as e:
                    st.warning(f"Không thể hiển thị bảng lệnh đã đóng: {e}")

# ========= QUYẾT ĐỊNH GẦN NHẤT =========
st.subheader("🧠 Quyết định gần nhất")
rows = read_decisions()
rows_f = filter_by_minutes(rows, int(lookback_min))
if not rows_f:
    st.info("Chưa có dữ liệu quyết định phù hợp khoảng thời gian lọc.")
else:
    rows_f.sort(key=lambda r: r.get("timestamp") or r.get("time") or "", reverse=True)
    df_rows = pd.DataFrame(rows_f)
    cols = [c for c in [
        "timestamp","decision","meta_action","confidence",
        "bandit_factor","funding_rate",
        "suggested_size","suggested_size_bandit","suggested_size_funding",
        "reasons"
    ] if c in df_rows.columns]
    st.dataframe(df_rows[cols].head(int(n_rows)), use_container_width=True, hide_index=True)

# ========= ĐIỀU KHIỂN CRX (FLAGS) =========
st.subheader("🧰 Điều khiển CrX (tạo/xoá cờ cho auto_runner)")
note_text = st.text_input("Ghi chú khi tạo cờ (tuỳ chọn)", placeholder="Ví dụ: test reload sau khi cập nhật config.py")

c1,c2,c3,c4,c5 = st.columns(5)
with c1:
    if st.button("🔄 Reload", help="Tạo reload.flag để runner nạp lại .env & cấu hình"):
        ok, msg = create_flag("reload.flag", note_text); st.success(msg) if ok else st.error(msg)
with c2:
    if st.button("⏸️ Stop (tạm dừng)", help="Tạo stop.flag để runner tạm dừng ở vòng ngủ"):
        ok, msg = create_flag("stop.flag", note_text); st.success(msg) if ok else st.error(msg)
with c3:
    if st.button("🛡️ Risk-off", help="Tạo riskoff.flag để bỏ qua decision & đặt lệnh"):
        ok, msg = create_flag("riskoff.flag", note_text); st.success(msg) if ok else st.error(msg)
with c4:
    if st.button("▶️ Resume (gỡ STOP/Risk-off)", help="Xoá stop.flag & riskoff.flag để chạy bình thường"):
        ok1, _ = remove_flag("stop.flag"); ok2, _ = remove_flag("riskoff.flag")
        st.success("Đã gỡ STOP/Risk-off.") if (ok1 or ok2) else st.info("Không có cờ để gỡ.")
with c5:
    if st.button("🧹 Close all", help="Tạo closeall.flag để runner đóng toàn bộ vị thế (reduceOnly)"):
        ok, msg = create_flag("closeall.flag", note_text); st.success(msg) if ok else st.error(msg)

st.markdown("### Trạng thái cờ hiện tại")
flag_reload  = (FLAG_DIR / "reload.flag").exists()
flag_stop    = (FLAG_DIR / "stop.flag").exists()
flag_riskoff = (FLAG_DIR / "riskoff.flag").exists()
flag_close   = (FLAG_DIR / "closeall.flag").exists()
st.markdown(
    f"- reload.flag: {'✅' if flag_reload else '—'}\n"
    f"- stop.flag: {'✅' if flag_stop else '—'}\n"
    f"- riskoff.flag: {'✅' if flag_riskoff else '—'}\n"
    f"- closeall.flag: {'✅' if flag_close else '—'}"
)

# Footer
st.caption(f"FLAG_DIR: {FLAG_DIR}")
st.caption(f"DATA_DIR: {DATA_DIR}")
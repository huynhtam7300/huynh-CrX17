# tools/decision_history_analyzer.py
# -*- coding: utf-8 -*-
import json, argparse, os, statistics as stats
from datetime import datetime
from collections import Counter, defaultdict

try:
    import matplotlib.pyplot as plt  # chỉ dùng nếu --plot
except Exception:
    plt = None

def iso(s):
    if not isinstance(s, str): return None
    if s.endswith("Z"): s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def safe_mean(arr):
    arr = [x for x in arr if isinstance(x, (int,float))]
    return round(stats.mean(arr), 6) if arr else None

def main():
    ap = argparse.ArgumentParser(description="Phân tích nhanh decision_history.json")
    ap.add_argument("path", help="data/decision_history.json")
    ap.add_argument("--outdir", default="report", help="Thư mục xuất kết quả (csv/png)")
    ap.add_argument("--plot", action="store_true", help="Vẽ biểu đồ PNG (cần matplotlib)")
    args = ap.parse_args()

    with open(args.path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("File không phải list JSON.")

    os.makedirs(args.outdir, exist_ok=True)

    # Thống kê cơ bản
    kinds = [r.get("decision") for r in data]
    cnt = Counter(kinds)

    confs = [r.get("confidence") for r in data]
    bfs   = [r.get("bandit_factor") for r in data if "bandit_factor" in r]
    frs   = [r.get("funding_rate") for r in data if "funding_rate" in r]

    meta_sizes   = [r.get("suggested_size") for r in data if "suggested_size" in r]
    bandit_sizes = [r.get("suggested_size_bandit") for r in data if "suggested_size_bandit" in r]
    fund_sizes   = [r.get("suggested_size_funding") for r in data if "suggested_size_funding" in r]

    print("===== TỔNG QUAN LỊCH SỬ QUYẾT ĐỊNH =====")
    print(f"- Số bản ghi: {len(data)}")
    print(f"- BUY/SELL/HOLD: {cnt.get('BUY',0)} / {cnt.get('SELL',0)} / {cnt.get('HOLD',0)}")
    print(f"- confidence_mean: {safe_mean(confs)}")
    print(f"- bandit_factor_mean: {safe_mean(bfs)} (n={len(bfs)})")
    print(f"- funding_rate_mean:  {safe_mean(frs)} (n={len(frs)})")
    print(f"- size_mean: meta={safe_mean(meta_sizes)}, bandit={safe_mean(bandit_sizes)}, funding={safe_mean(fund_sizes)}")

    # Xuất CSV nhanh
    csv_path = os.path.join(args.outdir, "decision_history_summary.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("metric,value\n")
        f.write(f"records,{len(data)}\n")
        f.write(f"buy,{cnt.get('BUY',0)}\n")
        f.write(f"sell,{cnt.get('SELL',0)}\n")
        f.write(f"hold,{cnt.get('HOLD',0)}\n")
        f.write(f"confidence_mean,{safe_mean(confs)}\n")
        f.write(f"bandit_factor_mean,{safe_mean(bfs)}\n")
        f.write(f"funding_rate_mean,{safe_mean(frs)}\n")
        f.write(f"suggested_size_mean,{safe_mean(meta_sizes)}\n")
        f.write(f"suggested_size_bandit_mean,{safe_mean(bandit_sizes)}\n")
        f.write(f"suggested_size_funding_mean,{safe_mean(fund_sizes)}\n")
    print(f"✅ Đã xuất {csv_path}")

    if args.plot and plt:
        # Chuỗi thời gian funding_rate & bandit_factor
        ts_f, y_f = [], []
        ts_b, y_b = [], []
        for r in data:
            t = iso(r.get("timestamp"))
            if t and "funding_rate" in r: 
                ts_f.append(t); y_f.append(r["funding_rate"])
            if t and "bandit_factor" in r:
                ts_b.append(t); y_b.append(r["bandit_factor"])

        if ts_f:
            plt.figure()
            plt.plot(ts_f, y_f)
            plt.title("Funding rate theo thời gian")
            plt.xlabel("time"); plt.ylabel("funding_rate")
            p = os.path.join(args.outdir, "funding_rate.png")
            plt.tight_layout(); plt.savefig(p, dpi=150); plt.close()
            print(f"🖼  {p}")

        if ts_b:
            plt.figure()
            plt.plot(ts_b, y_b)
            plt.title("Bandit factor theo thời gian")
            plt.xlabel("time"); plt.ylabel("bandit_factor")
            p = os.path.join(args.outdir, "bandit_factor.png")
            plt.tight_layout(); plt.savefig(p, dpi=150); plt.close()
            print(f"🖼  {p}")
    elif args.plot and not plt:
        print("⚠️ Không có matplotlib, bỏ qua vẽ biểu đồ.")

if __name__ == "__main__":
    main()
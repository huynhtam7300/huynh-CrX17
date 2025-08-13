# tools/validate_history.py
# -*- coding: utf-8 -*-
"""
Trình soát lỗi decision_history.json cho CrX.
- Mặc định: chỉ kiểm tra & báo cáo (không sửa).
- Tùy chọn --fix: điền mặc định an toàn khi có thể.
"""

import json
import argparse
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional
import math
import re
import sys
from copy import deepcopy

DECISIONS = {"BUY", "SELL", "HOLD"}

def parse_ts(s: str) -> Optional[datetime]:
    try:
        # Hỗ trợ "...Z"
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None

def parse_rate_from_reason(reasons: List[str]) -> Optional[float]:
    # Tìm "rate=0.000100" trong funding_reason
    for r in reasons:
        m = re.search(r"rate\s*=\s*([+-]?\d*\.?\d+)", r)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return None

def is_float(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def within(val: float, lo: float, hi: float) -> bool:
    return (val >= lo) and (val <= hi)

def add_issue(issues: Dict[str, List[str]], level: str, msg: str):
    issues.setdefault(level, []).append(msg)

def validate_entry(
    e: Dict[str, Any],
    idx: int,
    prev_ts: Optional[datetime],
    do_fix: bool
) -> Tuple[Dict[str, Any], Dict[str, List[str]], Optional[datetime]]:
    issues: Dict[str, List[str]] = {}
    entry = deepcopy(e)

    # 1) Kiểm tra tối thiểu
    # timestamp
    ts_raw = entry.get("timestamp")
    if not isinstance(ts_raw, str):
        add_issue(issues, "error", f"[{idx}] thiếu/không phải chuỗi: timestamp")
        ts = None
    else:
        ts = parse_ts(ts_raw)
        if ts is None:
            add_issue(issues, "error", f"[{idx}] timestamp không đúng ISO: {ts_raw}")

    # Thứ tự thời gian (nếu có prev_ts)
    if ts and prev_ts and ts < prev_ts:
        add_issue(issues, "warn", f"[{idx}] timestamp nhỏ hơn bản ghi trước (không theo thứ tự thời gian).")

    # decision
    d = entry.get("decision")
    if d not in DECISIONS:
        add_issue(issues, "error", f"[{idx}] decision không hợp lệ: {d}")

    # confidence / er / risk
    for field in ("confidence", "er", "risk"):
        v = entry.get(field)
        if not is_float(v):
            add_issue(issues, "error", f"[{idx}] {field} thiếu hoặc không phải số.")
        else:
            if not within(float(v), 0.0, 1.0):
                add_issue(issues, "warn", f"[{idx}] {field} ngoài khoảng [0,1]: {v}")

    # reasons
    reasons = entry.get("reasons")
    if not isinstance(reasons, list) or not all(isinstance(x, str) for x in reasons):
        add_issue(issues, "error", f"[{idx}] reasons phải là list[str].")

    # 2) Meta block (nếu có)
    if "meta_action" in entry:
        ma = entry.get("meta_action")
        if ma not in DECISIONS:
            add_issue(issues, "error", f"[{idx}] meta_action không hợp lệ: {ma}")

        if not is_float(entry.get("suggested_size")):
            add_issue(issues, "error", f"[{idx}] thiếu/không phải số: suggested_size")
        else:
            sz = float(entry["suggested_size"])
            if not within(sz, 0.0, 1.0):
                add_issue(issues, "warn", f"[{idx}] suggested_size ngoài [0,1]: {sz}")

        meta_reason = entry.get("meta_reason")
        if not isinstance(meta_reason, list) or not all(isinstance(x, str) for x in meta_reason):
            add_issue(issues, "error", f"[{idx}] meta_reason phải là list[str].")

    # 3) Funding block (khi có funding_reason/ funding_rate / suggested_size_funding)
    has_funding = any(k in entry for k in ("funding_reason", "funding_rate", "suggested_size_funding"))
    if has_funding:
        fr = entry.get("funding_reason")
        if not isinstance(fr, list) or not all(isinstance(x, str) for x in fr):
            add_issue(issues, "error", f"[{idx}] funding_reason phải là list[str].")
        # funding_rate
        fr_val = entry.get("funding_rate")
        if not is_float(fr_val):
            # thử tự điền từ reason nếu --fix
            if do_fix and isinstance(fr, list):
                parsed = parse_rate_from_reason(fr)
                if parsed is not None:
                    entry["funding_rate"] = float(parsed)
                    fr_val = entry["funding_rate"]
                    add_issue(issues, "fix", f"[{idx}] funding_rate được điền từ funding_reason: {fr_val}")
                else:
                    add_issue(issues, "error", f"[{idx}] thiếu funding_rate và không parse được từ funding_reason.")
            else:
                add_issue(issues, "error", f"[{idx}] thiếu/không phải số: funding_rate")
        if is_float(fr_val):
            if not within(float(fr_val), -0.01, 0.01):
                add_issue(issues, "warn", f"[{idx}] funding_rate bất thường (|rate|>1%/8h?): {fr_val}")

            # Nếu reason có "rate=..." thì đối chiếu
            if isinstance(fr, list):
                p = parse_rate_from_reason(fr)
                if p is not None:
                    if not math.isclose(float(fr_val), p, rel_tol=0, abs_tol=1e-6):
                        add_issue(issues, "warn", f"[{idx}] funding_rate != rate trong funding_reason ({fr_val} != {p})")

        # suggested_size_funding
        if not is_float(entry.get("suggested_size_funding")):
            if do_fix and is_float(entry.get("suggested_size")):
                entry["suggested_size_funding"] = float(entry["suggested_size"])
                add_issue(issues, "fix", f"[{idx}] điền suggested_size_funding = suggested_size ({entry['suggested_size_funding']}).")
            else:
                add_issue(issues, "error", f"[{idx}] thiếu/không phải số: suggested_size_funding")
        else:
            sszf = float(entry["suggested_size_funding"])
            if not within(sszf, 0.0, 1.0):
                add_issue(issues, "warn", f"[{idx}] suggested_size_funding ngoài [0,1]: {sszf}")

    # 4) Bandit block (khi có bandit_reason / factor / suggested_size_bandit)
    has_bandit = any(k in entry for k in ("bandit_reason", "bandit_factor", "suggested_size_bandit"))
    if has_bandit:
        br = entry.get("bandit_reason")
        if not isinstance(br, list) or not all(isinstance(x, str) for x in br):
            add_issue(issues, "error", f"[{idx}] bandit_reason phải là list[str].")

        bf = entry.get("bandit_factor")
        if not is_float(bf):
            # Nếu có cold_start/no_rewards thì cho phép fix = 1.0
            if do_fix and isinstance(br, list) and ("cold_start" in br or "no_rewards" in br):
                entry["bandit_factor"] = 1.0
                bf = 1.0
                add_issue(issues, "fix", f"[{idx}] điền bandit_factor=1.0 (cold_start/no_rewards).")
            else:
                add_issue(issues, "error", f"[{idx}] thiếu/không phải số: bandit_factor")
        if is_float(bf) and not within(float(bf), 0.0, 5.0):
            add_issue(issues, "warn", f"[{idx}] bandit_factor bất thường (ngoài (0..5]): {bf}")

        if not is_float(entry.get("suggested_size_bandit")):
            if do_fix and is_float(entry.get("suggested_size")):
                entry["suggested_size_bandit"] = float(entry["suggested_size"])
                add_issue(issues, "fix", f"[{idx}] điền suggested_size_bandit = suggested_size ({entry['suggested_size_bandit']}).")
            else:
                add_issue(issues, "error", f"[{idx}] thiếu/không phải số: suggested_size_bandit")
        else:
            sszb = float(entry["suggested_size_bandit"])
            if not within(sszb, 0.0, 1.0):
                add_issue(issues, "warn", f"[{idx}] suggested_size_bandit ngoài [0,1]: {sszb}")

    return entry, issues, ts

def main():
    ap = argparse.ArgumentParser(description="Validate decision_history.json cho CrX.")
    ap.add_argument("path", help="Đường dẫn tới decision_history.json")
    ap.add_argument("--fix", action="store_true", help="Tự điền mặc định an toàn khi có thể.")
    ap.add_argument("--out", default=None, help="Ghi file JSON đã fix ra đường dẫn này (chỉ khi dùng --fix).")
    args = ap.parse_args()

    # Đọc file
    try:
        with open(args.path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as ex:
        print(f"❌ Không đọc được file: {ex}")
        sys.exit(1)

    if not isinstance(data, list):
        print("❌ JSON gốc không phải list các bản ghi.")
        sys.exit(1)

    all_issues: List[Tuple[int, Dict[str, List[str]]]] = []
    fixed_data = []
    prev_ts = None
    error_count = 0
    warn_count = 0
    fix_count = 0

    for idx, e in enumerate(data):
        if not isinstance(e, dict):
            all_issues.append((idx, {"error": [f"[{idx}] phần tử không phải object JSON."]}))
            error_count += 1
            fixed_data.append(e)
            continue

        new_e, issues, prev_ts = validate_entry(e, idx, prev_ts, args.fix)
        fixed_data.append(new_e)

        if issues:
            all_issues.append((idx, issues))
            error_count += len(issues.get("error", []))
            warn_count  += len(issues.get("warn", []))
            fix_count   += len(issues.get("fix", []))

    # In báo cáo
    print("===== KẾT QUẢ KIỂM TRA decision_history =====")
    print(f"- Tổng số bản ghi: {len(data)}")
    print(f"- Lỗi (error): {error_count}")
    print(f"- Cảnh báo (warn): {warn_count}")
    if args.fix:
        print(f"- Tự sửa (fix): {fix_count}")

    if all_issues:
        print("\n--- Chi tiết ---")
        for idx, issues in all_issues:
            for level in ("error", "warn", "fix"):
                for msg in issues.get(level, []):
                    tag = {"error": "❌", "warn": "⚠️", "fix": "🛠️"}[level]
                    print(f"{tag} {msg}")

    # Ghi file đã fix nếu có --fix + --out
    if args.fix and args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(fixed_data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ Đã ghi file sau khi fix: {args.out}")
        except Exception as ex:
            print(f"❌ Không ghi được file out: {ex}")
            sys.exit(1)

    # Exit code khác 0 nếu có lỗi
    if error_count > 0:
        sys.exit(2)

if __name__ == "__main__":
    main()
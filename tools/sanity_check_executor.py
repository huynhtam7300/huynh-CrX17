#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/sanity_check_executor.py (verbose)
- In traceback khi import từng module executor
- Fallback import theo đường dẫn file nếu import package fail
- Dry-run hoặc gọi thử hàm đặt lệnh
"""

from __future__ import annotations
import os, sys, json, argparse, importlib, importlib.util, time, traceback
from pathlib import Path

TOOLS_OUT = Path("tools_output"); TOOLS_OUT.mkdir(exist_ok=True, parents=True)

CANDIDATE_MODULES = [
    "core.execution.order_executor",
    "core.order_executor",
    "order_executor",
]

CANDIDATE_FUNCS = [
    ("place_order", True),
    ("execute_market", True),
    ("place_market_order", True),
    ("create_order", True),
]

def load_bundle(config_dir: str):
    try:
        sys.path.insert(0, str(Path.cwd() / "config"))
        from config_loader import load_bundle as _load
    except Exception:
        from config.config_loader import load_bundle as _load  # type: ignore
    return _load(config_dir)

def try_import_verbose():
    """Thử import lần lượt và thu thập traceback."""
    attempts = []
    for mod in CANDIDATE_MODULES:
        try:
            m = importlib.import_module(mod)
            attempts.append({"module": mod, "status": "OK"})
            return m, mod, attempts
        except Exception:
            attempts.append({"module": mod, "status": "ERR", "traceback": traceback.format_exc()})
    return None, None, attempts

def import_from_path(py_path: Path):
    """Fallback: import trực tiếp từ đường dẫn file .py."""
    if not py_path.exists():
        return None, "NOT_FOUND"
    spec = importlib.util.spec_from_file_location("crx_exec_fallback", str(py_path))
    if not spec or not spec.loader:
        return None, "SPEC_FAIL"
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)  # type: ignore
        return m, "OK"
    except Exception:
        return None, traceback.format_exc()

def find_callable(mod):
    for fname, _ in CANDIDATE_FUNCS:
        fn = getattr(mod, fname, None)
        if callable(fn):
            return fn, fname
    for name in dir(mod):  # fallback: bất kỳ hàm có chữ 'order'
        if "order" in name.lower():
            fn = getattr(mod, name)
            if callable(fn):
                return fn, name
    return None, None

def call_with_variants(func, symbol, side, qty):
    variants = [
        ((), {"symbol":symbol, "side":side, "qty":qty, "order_type":"MARKET"}),
        ((symbol, side, qty, "MARKET"), {}),
        ((symbol, side, qty), {}),
        ((symbol, side), {"qty":qty, "order_type":"MARKET"}),
        ((), {"symbol":symbol, "side":side, "quantity":qty, "type":"MARKET"}),
    ]
    last_exc = None
    for args, kwargs in variants:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
    raise last_exc if last_exc else RuntimeError("Không gọi được hàm đặt lệnh.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.getenv("CRX_CONFIG_DIR","./config"))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--side", default="BUY", choices=["BUY","SELL","LONG","SHORT","buy","sell","long","short"])
    ap.add_argument("--qty", type=float, default=0.001)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    out = {"ts": int(time.time()), "ok": False, "steps": [], "error": None, "result": None, "import_attempts": []}
    def step(m): out["steps"].append(m)

    # 1) bundle
    step(f"Đọc cấu hình từ: {args.config}")
    b = load_bundle(args.config)

    # 2) env & exchange
    step(f"ENV CRX_ENABLE_ORDER_EXECUTOR={os.getenv('CRX_ENABLE_ORDER_EXECUTOR')}")
    ex = b.executor.exchange
    step(f"Exchange name={ex.name} dry_run={ex.dry_run} retries={ex.max_retries} backoff={ex.retry_backoff_seconds}s")

    # 3) import theo package
    mod, modname, attempts = try_import_verbose()
    out["import_attempts"] = attempts

    # 4) fallback theo path nếu package fail
    if not mod:
        p = Path("core/execution/order_executor.py")
        mod, status = import_from_path(p)
        step(f"Fallback import {p}: {status}")
        if not mod:
            out["error"] = "Không import được Executor (package & fallback). Xem import_attempts/traceback để biết chi tiết."
            with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, indent=2)
            print(json.dumps(out, ensure_ascii=False, indent=2)); return
        modname = f"[fallback]{p}"

    step(f"Đã import module: {modname}")
    fn, fnname = find_callable(mod)
    if not fn:
        out["error"] = "Không tìm thấy hàm đặt lệnh (place_order/execute_market/...)."
        with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, indent=2)
        print(json.dumps(out, ensure_ascii=False, indent=2)); return
    step(f"Dùng hàm: {fnname}")

    if args.dry_run:
        out["ok"] = True
        out["result"] = {"would_call": {"symbol": args.symbol, "side": args.side, "qty": args.qty}, "function": fnname}
        with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, indent=2)
        print(json.dumps(out, ensure_ascii=False, indent=2)); return

    try:
        res = call_with_variants(fn, args.symbol, args.side, args.qty)
        out["ok"] = True; out["result"] = f"{res!r}"
    except Exception as e:
        out["error"] = f"Lỗi khi gọi {fnname}: {e}\n{traceback.format_exc()}"
    with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    # Đảm bảo repo root có trong PYTHONPATH
    sys.path.insert(0, str(Path.cwd()))
    main()
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/sanity_check_executor.py
Mục tiêu: kiểm tra nhanh kênh thực thi lệnh (Executor) có hoạt động không.
- Đọc cấu hình SSOT qua config_loader.py
- Kiểm tra ENV & tham số executor
- Thử import các module Executor phổ biến trong repo và gọi đặt 1 lệnh MARKET nhỏ
- Ghi kết quả ra JSON: tools_output/sanity_result.json

Cách dùng (Windows PowerShell / Linux):
  python tools/sanity_check_executor.py --config ./config --symbol BTCUSDT --side BUY --qty 0.001
  # Dry-run (không gửi lệnh thật, chỉ thử import & in gợi ý):
  python tools/sanity_check_executor.py --config ./config --dry-run

Yêu cầu: pydantic, pyyaml (đã cài khi chạy config_loader)
"""
from __future__ import annotations
import os, sys, json, argparse, importlib, time, traceback
from pathlib import Path

TOOLS_OUT = Path("tools_output")
TOOLS_OUT.mkdir(exist_ok=True, parents=True)

def load_bundle(config_dir: str):
    # ưu tiên cấu trúc repo chuẩn /config
    try:
        sys.path.insert(0, str(Path.cwd() / "config"))
        from config_loader import load_bundle as _load
    except Exception:
        # fallback: nếu người dùng đặt cạnh file này
        try:
            from config.config_loader import load_bundle as _load
        except Exception as e:
            raise RuntimeError(f"Không import được config_loader.py: {e}")
    return _load(config_dir)

CANDIDATE_MODULES = [
    "core.execution.order_executor",
    "core.order_executor",
    "order_executor",
]

CANDIDATE_FUNCS = [
    # (name, kwargs_supported)
    ("place_order", True),
    ("execute_market", True),
    ("place_market_order", True),
    ("create_order", True),
]

def try_import_executor():
    last_err = None
    for mod in CANDIDATE_MODULES:
        try:
            m = importlib.import_module(mod)
            return m, mod, None
        except Exception as e:
            last_err = f"{mod}: {e}"
    return None, None, last_err

def try_find_callable(mod):
    for fname, _ in CANDIDATE_FUNCS:
        fn = getattr(mod, fname, None)
        if callable(fn):
            return fn, fname
    # fallback: tìm hàm nào có chữ "order" trong tên
    for name in dir(mod):
        if "order" in name.lower():
            fn = getattr(mod, name)
            if callable(fn):
                return fn, name
    return None, None

def call_with_variants(func, symbol, side, qty):
    # Thử nhiều chữ ký hàm khác nhau để tương thích tối đa
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
            continue
    raise last_exc if last_exc else RuntimeError("Không gọi được hàm đặt lệnh với mọi biến thể.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.getenv("CRX_CONFIG_DIR","./config"))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--side", default="BUY", choices=["BUY","SELL","LONG","SHORT","buy","sell","long","short"])
    ap.add_argument("--qty", type=float, default=0.001)
    ap.add_argument("--dry-run", action="store_true", help="Chỉ kiểm tra import & cấu hình, không gửi lệnh.")
    args = ap.parse_args()

    out = {
        "ts": int(time.time()),
        "ok": False,
        "steps": [],
        "error": None,
        "result": None,
    }
    def step(msg): out["steps"].append(msg)

    step(f"Đọc cấu hình từ: {args.config}")
    b = load_bundle(args.config)

    # Kiểm tra ENV cần thiết
    enable_exe = os.getenv("CRX_ENABLE_ORDER_EXECUTOR")
    step(f"ENV CRX_ENABLE_ORDER_EXECUTOR={enable_exe}")
    ex_cfg = b.executor.exchange
    step(f"Exchange name={ex_cfg.name} dry_run={ex_cfg.dry_run} retries={ex_cfg.max_retries} backoff={ex_cfg.retry_backoff_seconds}s")

    if ex_cfg.dry_run and not args.dry_run:
        step("⚠️ executor.exchange.dry_run=true → sẽ không gửi lệnh thật. Gợi ý: set false trong config khi test thực.")

    # Import module executor
    mod, modname, err = try_import_executor()
    if not mod:
        out["error"] = f"Không import được module Executor. Tried: {err}"
        step(out["error"])
        # Gợi ý vị trí phổ biến
        step("Hãy kiểm tra file: core/execution/order_executor.py hoặc core/order_executor.py")
        path1 = Path("core/execution/order_executor.py")
        path2 = Path("core/order_executor.py")
        out["result"] = {"exists": {"core/execution/order_executor.py": path1.exists(),
                                    "core/order_executor.py": path2.exists()}}
        with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    step(f"Đã import module: {modname}")
    fn, fnname = try_find_callable(mod)
    if not fn:
        out["error"] = "Không tìm thấy hàm đặt lệnh trong module (place_order/execute_market/...)."
        step(out["error"])
        with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    step(f"Dùng hàm: {fnname}")

    if args.dry_run:
        out["ok"] = True
        out["result"] = {"would_call": {"symbol": args.symbol, "side": args.side, "qty": args.qty}, "function": fnname}
        with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # Gửi lệnh
    try:
        res = call_with_variants(fn, args.symbol, args.side, args.qty)
        out["ok"] = True
        out["result"] = f"{res!r}"
    except Exception as e:
        out["error"] = f"Lỗi khi gọi {fnname}: {e}\n{traceback.format_exc()}"
    finally:
        with open(TOOLS_OUT / "sanity_result.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

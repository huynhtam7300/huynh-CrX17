#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/decision_probe.py
Mục tiêu: Soi "các cổng có thể đang chặn lệnh" chỉ dựa trên cấu hình & trạng thái file cờ.
- Không cần dữ liệu thị trường. Chỉ ra nguyên nhân phổ biến khiến Phase A không ra lệnh.
- Xuất JSON report: tools_output/decision_probe.json

Cách dùng:
  python tools/decision_probe.py --config ./config
"""
from __future__ import annotations
import os, sys, json, argparse, time
from pathlib import Path

TOOLS_OUT = Path("tools_output")
TOOLS_OUT.mkdir(exist_ok=True, parents=True)

def load_bundle(config_dir: str):
    try:
        sys.path.insert(0, str(Path.cwd() / "config"))
        from config_loader import load_bundle as _load
    except Exception:
        try:
            from config.config_loader import load_bundle as _load
        except Exception as e:
            raise RuntimeError(f"Không import được config_loader.py: {e}")
    return _load(config_dir)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.getenv("CRX_CONFIG_DIR","./config"))
    args = ap.parse_args()

    b = load_bundle(args.config)

    gates = []
    advice = []

    # 1) So sánh ngưỡng confidence
    left_floor = b.left.output.signal_confidence_floor
    central_min = b.central.decision.min_confidence
    if central_min > left_floor:
        gates.append(f"central.min_confidence({central_min}) > left.signal_confidence_floor({left_floor}) → có thể không đủ điều kiện mở lệnh.")
        advice.append("Giảm central.decision.min_confidence bằng hoặc thấp hơn left.output.signal_confidence_floor.")

    # 2) Controller
    if "LEFT" not in b.controller.routing.allowed_routes and "RIGHT" not in b.controller.routing.allowed_routes:
        gates.append("controller.allowed_routes KHÔNG có LEFT/RIGHT → chỉ có WAIT.")
        advice.append("Thêm LEFT/RIGHT vào controller.routing.allowed_routes.")
    if b.controller.routing.default_route == "WAIT":
        advice.append("default_route=WAIT là an toàn; cần đảm bảo điều kiện flip route đủ thoáng khi có tín hiệu.")
    if b.controller.constraints.max_parallel_orders == 0:
        gates.append("controller.constraints.max_parallel_orders=0 → chặn đặt lệnh.")
        advice.append("Tăng max_parallel_orders >= 1.")

    # 3) Right Safe Mode
    if b.controller.routing.inherit_safe_mode_from_right and b.right.safe_mode.enabled and b.right.safe_mode.block_new_positions:
        gates.append("inherit_safe_mode=true + RIGHT.safe_mode.block_new_positions=true → CHẶN mở lệnh mới.")
        advice.append("Tắt tạm block_new_positions trong right.safe_mode khi test, hoặc bỏ inherit trong controller.")

    # 4) BODY pause flag
    pause_flag = b.body.modes.pause_flag_file
    if pause_flag:
        if Path(pause_flag).exists():
            gates.append(f"Phát hiện file cờ '{pause_flag}' đang tồn tại → hệ thống đang PAUSE.")
            advice.append(f"Xóa file '{pause_flag}' để bỏ PAUSE (nếu đó không phải cờ reload).")

    # 5) Circuit-breakers (cảnh báo cấu hình)
    if b.body.circuit_breakers.max_drawdown_day_pct <= 0:
        gates.append("Circuit-breaker max_drawdown_day_pct <= 0 → sẽ luôn kích hoạt.")
        advice.append("Đặt max_drawdown_day_pct > 0.")
    if b.body.circuit_breakers.max_latency_ms < 500:
        advice.append("max_latency_ms quá thấp có thể gây nhiều false-positive → cân nhắc >= 1500ms.")

    # 6) Executor policy cấu hình nhỏ
    if "MARKET" not in b.executor.order_policy.allowed_types:
        gates.append("Executor không cho phép lệnh MARKET.")
        advice.append("Thêm MARKET vào executor.order_policy.allowed_types.")
    if b.executor.risk_hooks.per_symbol_max_position_usd < 10:
        advice.append("per_symbol_max_position_usd quá thấp có thể không vượt min notional sàn testnet.")

    out = {
        "ts": int(time.time()),
        "config_dir": args.config,
        "gates": gates,
        "advice": advice,
        "status": "OK" if not gates else "POTENTIAL_BLOCKERS",
        "key_values": {
            "left.signal_confidence_floor": left_floor,
            "central.min_confidence": central_min,
            "controller.allowed_routes": b.controller.routing.allowed_routes,
            "controller.default_route": b.controller.routing.default_route,
            "inherit_from_right": b.controller.routing.inherit_safe_mode_from_right,
            "right.safe_mode": {
                "enabled": b.right.safe_mode.enabled,
                "block_new_positions": b.right.safe_mode.block_new_positions
            },
            "pause_flag_file": pause_flag,
            "executor.allowed_types": b.executor.order_policy.allowed_types,
            "executor.per_symbol_max_position_usd": b.executor.risk_hooks.per_symbol_max_position_usd
        }
    }
    with open(TOOLS_OUT / "decision_probe.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

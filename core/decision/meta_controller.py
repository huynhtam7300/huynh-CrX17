# -*- coding: utf-8 -*-
# core/decision/meta_controller.py
"""
Meta-Controller cho Phase B:
- BOTH tắt; chỉ quản trị tuyến {LEFT, RIGHT, WAIT} (mặc định LEFT).
- Siết đổi tuyến: cooldown theo controller.yaml, đếm flips/giờ.
- Ghi/đọc trạng thái tại data/meta_state.json để các module khác (executor)
  có thể gate theo route hiện hành.
- Thông báo Telegram (nếu bật trong controller.yaml và đã cấu hình bot trong .env).

Yêu cầu tối thiểu:
- PyYAML (yaml)
- Tồn tại thư mục dự án: /home/.../CrX17 với: config/controller.yaml, data/
"""

from __future__ import annotations

import os
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import yaml
except Exception:  # fallback thô nếu thiếu PyYAML
    yaml = None  # type: ignore

# Optional: Telegram notifier
def _notify(msg: str) -> None:
    try:
        from notifier.notify_telegram import send_telegram_message
        send_telegram_message(msg)
    except Exception:
        pass

# ---------- Đường dẫn gốc dự án ----------
ROOT = Path(__file__).resolve().parents[2]  # .../CrX17
CFG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"

STATE_FILE = DATA_DIR / "meta_state.json"          # nơi lưu trạng thái Meta
DECISION_FILE = DATA_DIR / "decision_history.json" # nơi các quyết định LEFT ghi vào

# ---------- Đọc YAML / JSON ----------
def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def _read_last_left_decision() -> Dict[str, Any]:
    """
    Lấy bản ghi quyết định LEFT gần nhất:
    - ưu tiên dòng cuối của data/decision_history.json (mỗi lần append một record JSON)
    - nếu không có -> trả WAIT.
    """
    try:
        if DECISION_FILE.exists():
            # file có thể là mảng JSON hoặc mỗi dòng một JSON; xử lý cả 2
            txt = DECISION_FILE.read_text(encoding="utf-8").strip()
            if not txt:
                raise ValueError("empty decision_history.json")
            if txt.lstrip().startswith("["):
                arr = json.loads(txt)
                if isinstance(arr, list) and arr:
                    return arr[-1]
            else:
                # lấy dòng cuối không rỗng
                *_, last = [ln for ln in txt.splitlines() if ln.strip()]
                return json.loads(last)
    except Exception:
        pass
    return {"decision": "WAIT", "confidence": 0.0, "er": 0.0, "risk": 0.0, "reasons": ["no_decision"]}

def _utc_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# ---------- Tải cấu hình controller ----------
def _load_controller_cfg() -> Dict[str, Any]:
    cfg = _read_yaml(CFG_DIR / "controller.yaml")

    # Mặc định an toàn nếu thiếu khóa
    routing = (cfg.get("routing") or {}) if isinstance(cfg, dict) else {}
    notif   = (cfg.get("notifications") or {}) if isinstance(cfg, dict) else {}
    constraints = (cfg.get("constraints") or {}) if isinstance(cfg, dict) else {}

    allowed = routing.get("allowed_routes") or ["LEFT", "RIGHT", "WAIT"]
    default = routing.get("default_route") or "LEFT"
    cooldown = int(routing.get("cooldown_switch_seconds") or 120)
    flips = int(routing.get("max_route_flips_per_hour") or 6)

    tg = (((notif.get("telegram") or {})) if isinstance(notif, dict) else {})
    tg_enabled = bool(tg.get("enabled", True))
    tg_dedupe = int(tg.get("dedupe_minutes", 30))

    max_parallel = int(constraints.get("max_parallel_orders", 1))
    max_daily    = int(constraints.get("max_daily_new_positions", 6))

    return {
        "allowed_routes": [str(x).upper() for x in allowed],
        "default_route": str(default).upper(),
        "cooldown_sec": cooldown,
        "max_flips_per_hour": flips,
        "telegram": {"enabled": tg_enabled, "dedupe_minutes": tg_dedupe},
        "limits": {"max_parallel_orders": max_parallel, "max_daily_new_positions": max_daily},
    }

# ---------- Lưu/đọc STATE ----------
def _load_state(default_route: str) -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "current_route": default_route,
            "last_switch_ts": 0.0,
            "flip_window": [],  # list[float] các mốc đổi tuyến trong 1h
            "last_notify_sw_ts": 0.0,
        }
    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # vá thiếu khóa
        st.setdefault("current_route", default_route)
        st.setdefault("last_switch_ts", 0.0)
        st.setdefault("flip_window", [])
        st.setdefault("last_notify_sw_ts", 0.0)
        return st
    except Exception:
        return {
            "current_route": default_route,
            "last_switch_ts": 0.0,
            "flip_window": [],
            "last_notify_sw_ts": 0.0,
        }

def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- Quyết định tuyến (Phase B giữ LEFT, có WAIT khi cần) ----------
def _decide_target_route(cfg: Dict[str, Any], last_left: Dict[str, Any]) -> str:
    """
    Luật đơn giản cho Phase B:
    - Nếu tín hiệu LEFT là WAIT -> chọn WAIT (giảm khớp khi thị trường nhiễu).
    - Ngược lại: giữ LEFT (BOTH tắt; RIGHT chỉ dùng Phase C).
    """
    dec = (last_left.get("decision") or "WAIT").upper()
    if dec == "WAIT":
        return "WAIT"
    return "LEFT"

# ---------- Kiểm tra điều kiện đổi tuyến ----------
def _can_switch(now_ts: float, state: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    # cooldown
    if now_ts - float(state.get("last_switch_ts", 0.0)) < cfg["cooldown_sec"]:
        return False
    # flips per hour
    window = [t for t in state.get("flip_window", []) if now_ts - t <= 3600.0]
    if len(window) >= cfg["max_flips_per_hour"]:
        state["flip_window"] = window  # dọn cũ
        return False
    state["flip_window"] = window
    return True

def _switch_route(state: Dict[str, Any], new_route: str) -> None:
    now_ts = _utc_ts()
    state["current_route"] = new_route
    state["last_switch_ts"] = now_ts
    window = state.get("flip_window", [])
    window.append(now_ts)
    state["flip_window"] = [t for t in window if now_ts - t <= 3600.0]

# ---------- Thông báo (Telegram) với khử trùng lặp ----------
def _maybe_notify_switch(cfg: Dict[str, Any], state: Dict[str, Any], from_route: str, to_route: str, reason: str) -> None:
    if not cfg["telegram"]["enabled"]:
        return
    # khử spam theo dedupe_minutes
    dedup = int(cfg["telegram"]["dedupe_minutes"] or 30)
    now_ts = _utc_ts()
    last_ts = float(state.get("last_notify_sw_ts", 0.0))
    if now_ts - last_ts < dedup * 60:
        return
    state["last_notify_sw_ts"] = now_ts
    _notify(f"🔁 Đổi tuyến: {from_route} → {to_route} (lý do: {reason})")

# ---------- MAIN ----------
def run_once() -> Dict[str, Any]:
    cfg = _load_controller_cfg()
    allowed = cfg["allowed_routes"]
    default_route = cfg["default_route"]
    state = _load_state(default_route)

    # init lần đầu (in log cho dễ theo dõi)
    if not STATE_FILE.exists():
        _save_state(state)
        print(f"[Meta-Controller] init route = {state['current_route']} at { _utc_iso() }")

    # lấy quyết định LEFT gần nhất
    last_left = _read_last_left_decision()
    target = _decide_target_route(cfg, last_left).upper()
    if target not in allowed:
        # an toàn: nếu file cấu hình không cho phép, lùi về default
        target = default_route

    cur = state.get("current_route", default_route).upper()
    now_iso = _utc_iso()

    if cur != target:
        now_ts = _utc_ts()
        if _can_switch(now_ts, state, cfg):
            reason = f"left={last_left.get('decision','WAIT')}, conf={last_left.get('confidence',0):.2f}"
            _switch_route(state, target)
            _maybe_notify_switch(cfg, state, cur, target, reason)
            _save_state(state)
            print(f"[Meta-Controller] switch {cur} -> {target} at {now_iso} ({reason})")
        else:
            print(f"[Meta-Controller] want {target} but cooldown/limit block at {now_iso}")
    else:
        # không đổi gì, vẫn log trạng thái nhẹ
        print(f"[Meta-Controller] keep route = {cur} at {now_iso}")

    # Trả về gói thông tin ngắn để runner ghi log thêm nếu muốn
    return {
        "ts": now_iso,
        "current_route": state["current_route"],
        "target_route": target,
        "cooldown_sec": cfg["cooldown_sec"],
        "max_flips_per_hour": cfg["max_flips_per_hour"],
    }

def main() -> None:
    try:
        out = run_once()
        print("[Meta-Controller] state:", json.dumps(out, ensure_ascii=False))
    except Exception as e:
        print("[Meta-Controller] ERROR:", e)
        traceback.print_exc()

if __name__ == "__main__":
    main()
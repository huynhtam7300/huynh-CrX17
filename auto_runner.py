# auto_runner.py
# CrX 1.7 – CORE → Phase A
# Orchestrator: collector → etl → analyzer → decision → execution → monitor → evaluate → (report theo lịch)
from __future__ import annotations
import os
import sys
import time
import json
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ===== VERSION =====
VERSION = "CrX auto_runner v1.7.11 (pnl-sync scheduler + seed-cooldown + closeall)"

# ----- ENV / CONFIG -----
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass  # không bắt buộc

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

# Chu kỳ chạy (phút). Mặc định 15’ theo plan CrX.
LOOP_MINUTES = int(os.getenv("CRX_LOOP_MINUTES", "15"))
# Có bật đặt lệnh không (Binance Testnet)?
ENABLE_EXECUTOR = os.getenv("CRX_ENABLE_ORDER_EXECUTOR", "0") not in ("0", "false", "False", "")

# Cooldown cho Decision để tránh ra quyết định quá dày (giây)
COOLDOWN_DECISION_SEC = int(os.getenv("CRX_COOLDOWN_DECISION_SEC", "120"))
_last_decision_wallclock = 0.0  # sẽ seed từ file ở startup

# Cờ điều khiển đặt tại thư mục ROOT (đồng bộ dashboard)
FLAG_DIR      = Path(os.getenv("CRX_FLAG_DIR", str(ROOT))).resolve()
RELOAD_FLAG   = FLAG_DIR / "reload.flag"
STOP_FLAG     = FLAG_DIR / "stop.flag"
RISK_FLAG     = FLAG_DIR / "riskoff.flag"
CLOSEALL_FLAG = FLAG_DIR / "closeall.flag"

DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Toggle gửi thông báo (đọc động theo .env sau mỗi reload)
def _read_notify_toggles():
    return (
        os.getenv("CRX_ENABLE_NOTIFY_DECISION", "0") not in ("0","false","False",""),
        os.getenv("CRX_ENABLE_NOTIFY_FLAGS", "0") not in ("0","false","False",""),
    )
ENABLE_NOTIFY_DECISION, ENABLE_NOTIFY_FLAGS = _read_notify_toggles()

# Tùy chọn: feature flags (nếu có)
FF = None
try:
    from configs.feature_flags_loader import load_flags  # không bắt buộc
    FF = load_flags()
except Exception:
    FF = None

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def ts() -> str:
    return now_utc().strftime("%Y-%m-%d %H:%M:%S")

# ===== Watcher trạng thái cờ (nền) =====
_reload_event = threading.Event()
_risk_changed_event = threading.Event()  # báo có thay đổi Risk-off (bật/tắt)
_stop_state_last = None
_risk_state_last = None
_reload_state_last = None

def _flag_watcher(poll_sec: float = 1.0):
    """Theo dõi cờ mỗi 1s và phát sự kiện khi thay đổi."""
    global _stop_state_last, _risk_state_last, _reload_state_last
    while True:
        # RELOAD
        cur_reload = RELOAD_FLAG.exists()
        if cur_reload != _reload_state_last:
            print(f"[{ts()}] 👀 reload.flag = {cur_reload} at {RELOAD_FLAG}", flush=True)
            _reload_state_last = cur_reload
            if cur_reload:
                _reload_event.set()

        # STOP
        cur_stop = STOP_FLAG.exists()
        if cur_stop != _stop_state_last:
            print(f"[{ts()}] 👀 stop.flag   = {cur_stop} at {STOP_FLAG}", flush=True)
            _stop_state_last = cur_stop

        # RISK-OFF
        cur_risk = RISK_FLAG.exists()
        if cur_risk != _risk_state_last:
            print(f"[{ts()}] 👀 riskoff.flag= {cur_risk} at {RISK_FLAG}", flush=True)
            _risk_state_last = cur_risk
            _risk_changed_event.set()

        time.sleep(poll_sec)

# ----- TIỆN ÍCH CHẠY MODULE -----
def run_module(mod: str, timeout: int = 300) -> int:
    """Chạy 1 module bằng python -m. Trả về return code (0 = OK)."""
    print(f"[{ts()}] Chạy module: {mod}")
    try:
        res = subprocess.run([PYTHON, "-m", mod], capture_output=False, check=False, timeout=timeout)
        rc = res.returncode
    except subprocess.TimeoutExpired:
        print(f"[{ts()}] ⚠️  TIMEOUT: {mod}")
        rc = 124
    except Exception as e:
        print(f"[{ts()}] ❌ Lỗi chạy {mod}: {e}")
        rc = 1
    if rc != 0:
        print(f"[{ts()}] ⚠️  Module {mod} kết thúc với mã {rc}")
    return rc

def run_module_args(mod: str, args: list[str], timeout: int = 300) -> int:
    """Chạy module kèm tham số."""
    print(f"[{ts()}] Chạy module: {mod} {' '.join(args)}")
    try:
        res = subprocess.run([PYTHON, "-m", mod, *args], capture_output=False, check=False, timeout=timeout)
        return res.returncode
    except Exception as e:
        print(f"[{ts()}] ❌ Lỗi chạy {mod}: {e}")
        return 1

def run_if_exists(mod: str, timeout: int = 300) -> int:
    """Chỉ chạy nếu module có thật trong repo (tránh lỗi khi một số module chưa có)."""
    mod_path = ROOT / mod.replace(".", "/")
    exists = (mod_path.with_suffix(".py").exists() or (mod_path / "__init__.py").exists())
    if not exists:
        return 0
    return run_module(mod, timeout=timeout)

def should_run(flag_path: str, default_on: bool = True) -> bool:
    """Đọc feature flag nếu có; nếu không có FF loader → trả về mặc định."""
    if FF is None:
        return default_on
    try:
        return FF.is_on(flag_path, default_on)
    except Exception:
        return default_on

# ----- QUẢN LÝ CỜ -----
def _consume_reload_flag() -> bool:
    """Nếu có reload.flag hoặc event → xoá cờ (nếu có), reload .env và trả True."""
    global ENABLE_NOTIFY_DECISION, ENABLE_NOTIFY_FLAGS
    if _reload_event.is_set() or RELOAD_FLAG.exists():
        try:
            if RELOAD_FLAG.exists():
                RELOAD_FLAG.unlink()
        except Exception:
            pass
        _reload_event.clear()
        # reload env toggles
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
        except Exception:
            pass
        ENABLE_NOTIFY_DECISION, ENABLE_NOTIFY_FLAGS = _read_notify_toggles()
        print(f"[{ts()}] ENV reloaded: CRX_ENABLE_NOTIFY_DECISION={1 if ENABLE_NOTIFY_DECISION else 0} | CRX_ENABLE_NOTIFY_FLAGS={1 if ENABLE_NOTIFY_FLAGS else 0}")
        print(f"[{ts()}] 🔄 Nhận RELOAD → áp dụng config mới từ vòng kế tiếp.")
        return True
    return False

def _wait_stop_if_needed(poll_sec: int = 2) -> None:
    """Nếu có STOP → tạm dừng cho đến khi gỡ cờ."""
    if STOP_FLAG.exists():
        print(f"[{ts()}] ⏸️ STOP đang bật tại: {STOP_FLAG}. (Xoá stop.flag để tiếp tục)")
        while STOP_FLAG.exists():
            time.sleep(poll_sec)
        print(f"[{ts()}] ▶️ STOP đã gỡ. Tiếp tục chạy.")

_last_riskoff_state_print = None
def _read_risk_state() -> bool:
    """Đọc trạng thái risk-off và log khi thay đổi."""
    global _last_riskoff_state_print
    state = RISK_FLAG.exists()
    if state != _last_riskoff_state_print:
        if state:
            print(f"[{ts()}] 🛡️ RISK-OFF: BẬT (bỏ qua decision & order_executor).")
        else:
            print(f"[{ts()}] 🛡️ RISK-OFF: TẮT.")
        _last_riskoff_state_print = state
    return state

def _check_closeall_if_any():
    """Nếu có closeall.flag → gọi tools.close_all_positions rồi xoá cờ."""
    if CLOSEALL_FLAG.exists():
        print(f"[{ts()}] 🧹 Phát hiện closeall.flag → đóng toàn bộ vị thế (reduceOnly).")
        rc = run_module_args("tools.close_all_positions", ["--wait","8"], timeout=180)
        try:
            CLOSEALL_FLAG.unlink()
        except Exception:
            pass
        print(f"[{ts()}] 🧹 Close-all đã chạy (rc={rc}).")

# ----- NGỦ CÓ POLLING CỜ -----
def _sleep_until_next_tick(loop_minutes: int, poll_sec: int = 2) -> bool:
    """
    Ngủ đến mốc tick kế tiếp (00, 15, 30, 45…).
    Trong lúc ngủ: poll STOP/RELOAD và **đánh thức nếu Risk-off thay đổi**.
    Trả True nếu dậy sớm (do RELOAD hoặc RISK-OFF change).
    """
    now = datetime.now()
    minute = (now.minute // loop_minutes) * loop_minutes
    next_min = minute + loop_minutes
    next_tick = now.replace(second=0, microsecond=0)
    if next_min >= 60:
        next_tick = (next_tick + timedelta(hours=1)).replace(minute=0)
    else:
        next_tick = next_tick.replace(minute=next_min)

    print(f"[{ts()}] 💤 Ngủ đến mốc {next_tick.strftime('%H:%M:%S')} (poll={poll_sec}s)...")

    while True:
        now = datetime.now()
        if now >= next_tick:
            return False  # ngủ đủ

        _wait_stop_if_needed(poll_sec=poll_sec)
        _check_closeall_if_any()

        if _consume_reload_flag():
            print(f"[{ts()}] ⏩ Dậy sớm do RELOAD.")
            return True

        if _risk_changed_event.is_set():
            _risk_changed_event.clear()
            print(f"[{ts()}] ⏩ Dậy sớm do RISK-OFF thay đổi.")
            return True

        remain = (next_tick - now).total_seconds()
        time.sleep(poll_sec if remain > poll_sec else remain)

def _maybe_run_daily_report() -> None:
    """Chạy báo cáo ngày 1 lần/giờ (phút 00) để tránh spam."""
    now = datetime.now()
    if now.minute == 0:
        run_if_exists("report.report_daily", timeout=180)

# ===== HỖ TRỢ: PNL SYNC =====
def _file_age_minutes(p: Path) -> float:
    if not p.exists(): return 1e9
    return (time.time() - p.stat().st_mtime) / 60.0

def _maybe_run_pnl_sync() -> None:
    """
    Đồng bộ PnL theo lịch:
      - Mỗi mốc 00/15/30/45 phút, hoặc
      - Khi file đã cũ > 30 phút (đề phòng runner ngủ dài hay lỗi trước đó).
    """
    try:
        now = datetime.now()
        on_quarter = (now.minute % 15 == 0)
        p_sum = DATA_DIR / "pnl_summary.json"
        p_raw = DATA_DIR / "pnl_income_raw.json"
        stale = (_file_age_minutes(p_sum) > 30.0) or (_file_age_minutes(p_raw) > 30.0)
        if on_quarter or stale:
            run_if_exists("core.evaluator.pnl_sync", timeout=180)
    except Exception as e:
        print(f"[{ts()}] ⚠️ pnl_sync skip: {e}")

# ----- SEED COOLDOWN TỪ FILE -----
def _seed_cooldown_from_file():
    """Khởi tạo _last_decision_wallclock dựa trên quyết định cuối trong data/decision_history.json."""
    global _last_decision_wallclock
    try:
        f = DATA_DIR / "decision_history.json"
        if not f.exists():
            return
        obj = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(obj, list) and obj:
            last = obj[-1]
            ts_iso = last.get("timestamp")
            if ts_iso:
                try:
                    dt = datetime.fromisoformat(ts_iso.replace("Z","+00:00"))
                    _last_decision_wallclock = dt.timestamp()
                    print(f"[{ts()}] ⏱️ Seed cooldown từ file: last_decision={ts_iso}")
                except Exception:
                    pass
    except Exception:
        pass

# ----- VÒNG LẶP CHÍNH -----
def main():
    print(f"{VERSION}")
    print(f"🟢 Khởi động auto_runner.py ... (loop={LOOP_MINUTES} phút)")
    print(f"[{ts()}] ROOT={ROOT}")
    print(f"[{ts()}] FLAG_DIR={FLAG_DIR}")
    print(f"[{ts()}] reload.exists={RELOAD_FLAG.exists()} | stop.exists={STOP_FLAG.exists()} | riskoff.exists={RISK_FLAG.exists()}")

    # Seed cooldown từ file quyết định
    _seed_cooldown_from_file()

    # Khởi động watcher nền
    threading.Thread(target=_flag_watcher, daemon=True).start()

    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"[{ts()}] ⚠️  Không thấy file .env ở {env_path}. Hãy tạo để cấu hình API/Token.")
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(exist_ok=True)

    try:
        while True:
            start = time.time()

            # Poll cờ ngay đầu vòng
            _wait_stop_if_needed()
            _consume_reload_flag()
            _check_closeall_if_any()
            riskoff = _read_risk_state()

            # 1) COLLECTOR
            run_if_exists("core.collector.market_collector", timeout=300)

            # 2) FEATURE ETL
            run_if_exists("core.feature_etl.cleaner", timeout=120)
            run_if_exists("core.feature_etl.alignment", timeout=120)
            run_if_exists("core.feature_etl.selector", timeout=120)

            # 3) ANALYZER
            run_if_exists("core.analyzer.technical_analyzer", timeout=300)
            if should_run("modules.analyzer.aggregators.left_agg.enabled", True) or \
               should_run("modules.aggregators.left_agg.enabled", True):
                run_if_exists("core.aggregators.left_agg", timeout=120)

            # Nếu Risk-off vừa đổi giữa vòng → cập nhật & có thể bỏ qua Decision/Order
            if _risk_changed_event.is_set():
                _risk_changed_event.clear()
                riskoff = _read_risk_state()
                if riskoff:
                    print(f"[{ts()}] ⏭️  RISK-OFF bật giữa vòng: bỏ qua decision & order.")

            # 4) DECISION (bỏ qua khi risk-off) + COOLDOWN (seed từ file)
            if not riskoff:
                global _last_decision_wallclock
                now_wall = time.time()
                if (now_wall - _last_decision_wallclock) < COOLDOWN_DECISION_SEC:
                    remain = COOLDOWN_DECISION_SEC - (now_wall - _last_decision_wallclock)
                    print(f"[{ts()}] ⏳ Cooldown {COOLDOWN_DECISION_SEC}s (còn {remain:.1f}s): bỏ qua decision_* vòng này.")
                else:
                    run_if_exists("core.decision.decision_maker", timeout=120)
                    if should_run("modules.decision.meta_controller.enabled", True):
                        run_if_exists("core.decision.meta_controller", timeout=120)
                    _last_decision_wallclock = time.time()
            else:
                print(f"[{ts()}] ⏭️  RISK-OFF: bỏ qua decision_*.")

            # 5) CAPITAL / FUNDING (tùy chọn)
            if should_run("modules.capital.capital_gate.enabled", True):
                run_if_exists("core.capital.capital_gate", timeout=90)
            if should_run("modules.capital.funding_optimizer.enabled", True):
                run_if_exists("core.capital.funding_optimizer", timeout=90)

            # Cập nhật Risk-off lần nữa trước EXECUTION
            if _risk_changed_event.is_set():
                _risk_changed_event.clear()
                riskoff = _read_risk_state()
                if riskoff:
                    print(f"[{ts()}] ⏭️  RISK-OFF bật giữa vòng: bỏ qua order.")

            # 6) EXECUTION & MONITOR
            if ENABLE_EXECUTOR and not riskoff:
                run_if_exists("core.execution.order_executor", timeout=180)
            elif ENABLE_EXECUTOR and riskoff:
                print(f"[{ts()}] ⏭️  RISK-OFF: bỏ qua order_executor.")
            run_if_exists("core.execution.order_monitor", timeout=180)

            # 7) EVALUATE
            rc_eval = run_if_exists("core.evaluator.evaluate_latest", timeout=120)
            if rc_eval != 0:
                run_if_exists("core.evaluator.evaluate_decision", timeout=120)

            # 8) PnL SYNC + NOTIFY / REPORT
            _maybe_run_pnl_sync()  # <<< mới
            if ENABLE_NOTIFY_DECISION:
                run_if_exists("notifier.notify_decision", timeout=90)
            if ENABLE_NOTIFY_FLAGS:
                run_if_exists("notifier.notify_flags", timeout=60)
            _maybe_run_daily_report()

            # Tổng kết vòng
            dur = time.time() - start
            print(f"[{ts()}] ✅ Vòng chạy xong trong {dur:.1f}s")

            # Ngủ có polling cờ & thức dậy khi Risk-off thay đổi
            woke_early = _sleep_until_next_tick(LOOP_MINUTES, poll_sec=2)
            if woke_early:
                continue

    except KeyboardInterrupt:
        print(f"\n[{ts()}] 🛑 Dừng auto_runner theo yêu cầu (Ctrl+C).")
    except Exception as e:
        print(f"[{ts()}] ❌ Lỗi không mong muốn ở auto_runner: {e}")
        # không raise để hạn chế crash

if __name__ == "__main__":
    main()
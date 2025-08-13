import json
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"

def _load_json(p: Path, default=None):
    if default is None: default = {}
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return default

def _load_yaml(p: Path, default=None):
    if default is None: default = {}
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f) or default
        except Exception:
            return default

# ----- Cấu hình công khai dùng cho toàn hệ thống -----
CONFIG        = _load_json(CONFIGS_DIR / "config.json", {})
RISK_LIMITS   = _load_yaml(CONFIGS_DIR / "risk_limits.yaml", {})
FEATURE_FLAGS = _load_yaml(CONFIGS_DIR / "feature_flags.yaml", {})
KPI_POLICY    = _load_yaml(CONFIGS_DIR / "kpi_policy.yaml", {})

# Trợ giúp: lấy danh sách symbol/timeframe
SYMBOLS   = CONFIG.get("symbols", ["BTCUSDT", "ETHUSDT"])
TIMEFRAME = CONFIG.get("timeframe", "15m")
REPORT_TIME_UTC = CONFIG.get("report_time_utc", "15:55")
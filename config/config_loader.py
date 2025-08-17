"""
config_loader.py — Bộ tải & validate cấu hình SSOT cho CrX 1.7.7
- Đọc 11 file YAML trong thư mục cấu hình (mặc định: ./config/)
- Parse sang Pydantic models
- Tính yaml_hash (sha256) & chg_id
- Chạy cross-validators từ validators.py
- Cung cấp API load_bundle() để các module khác dùng.

Yêu cầu:
  pip install pydantic>=2 pyyaml

Sử dụng CLI:
  CRX_CONFIG_DIR=./config python config_loader.py
  # hoặc
  python config_loader.py --dir ./config
"""
from __future__ import annotations

import argparse
import os
import sys
import json
import yaml
import hashlib
from typing import Dict, List, Optional, Literal, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

# ============================
# Utils
# ============================

def _read_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# ============================
# Pydantic Models per config
# ============================

class Meta(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    version: str
    chg_id: str
    description: Optional[str] = ""

# CENTRAL
class CentralSecurity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cors: dict = Field(default_factory=dict)
    ip_allowlist: List[str] = Field(default_factory=list)
    jwt_ttl_minutes: int = 30

class CentralSLO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    central_p95_ms: int = 120
    telegram_p95_ms: int = 800
    nse_p95_ms: int = 1800

class CentralTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    slo: CentralSLO

class TieBreaker(BaseModel):
    model_config = ConfigDict(extra="ignore")
    priority: List[str] = Field(default_factory=list)
    weight: Dict[str, float] = Field(default_factory=dict)

class WaitRules(BaseModel):
    model_config = ConfigDict(extra="ignore")
    on_rebase_risk: bool = True
    max_wait_minutes: int = 30

class DecisionPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    min_confidence: float = 0.55
    tie_breaker: TieBreaker
    wait_rules: WaitRules

class Bundling(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    interval_minutes: int = 12
    max_events_per_bundle: int = 30
    notify_on: List[str] = Field(default_factory=list)

class TelegramTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    header: Optional[str] = ""
    footer: Optional[str] = ""
    show_confetti_on_good: Optional[bool] = False

class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chat_ids: List[str] = Field(default_factory=list)
    throttle_per_minute: Optional[int] = 6
    template: Optional[TelegramTemplate] = None

class Notifications(BaseModel):
    model_config = ConfigDict(extra="ignore")
    telegram: Optional[TelegramConfig] = None

class CentralConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    security: CentralSecurity
    telemetry: CentralTelemetry
    decision: DecisionPolicy
    bundling: Bundling
    notifications: Notifications

# CONTROLLER
class SymbolFairness(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_symbols_per_cycle: int = 2
    rotation: Literal["round_robin","random"] = "round_robin"

class Routing(BaseModel):
    model_config = ConfigDict(extra="ignore")
    allowed_routes: List[Literal["LEFT","RIGHT","WAIT"]] = ["LEFT","RIGHT","WAIT"]
    default_route: Literal["LEFT","RIGHT","WAIT"] = "WAIT"
    cooldown_switch_seconds: int = 180
    max_route_flips_per_hour: int = 6
    inherit_safe_mode_from_right: bool = True
    symbol_fairness: SymbolFairness = Field(default_factory=SymbolFairness)

class ControllerConstraints(BaseModel):
    model_config = ConfigDict(extra="ignore")
    require_ttl_plus_for_explore: bool = True
    max_parallel_orders: int = 2
    max_daily_new_positions: int = 10

class ControllerTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    switch: Optional[str] = None

class ControllerNotifications(BaseModel):
    model_config = ConfigDict(extra="ignore")
    telegram: Optional[TelegramConfig] = None
    template: Optional[ControllerTemplate] = None

class ControllerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    routing: Routing
    constraints: ControllerConstraints
    notifications: Optional[ControllerNotifications] = None

# LEFT
class TimeSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    start: str
    end: str

class Filters(BaseModel):
    model_config = ConfigDict(extra="ignore")
    regime: Dict[str, bool]
    multi_timeframe: Dict[str, Any]
    time_of_day: Dict[str, Any]
    funding_filter: Dict[str, Any]

class StrategyTrend(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    rsi_period: int = 14
    ema_period: int = 34
    confirm_mtf: Optional[str] = None

class StrategyBO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    lookback: int = 20
    atr_mult: float = 1.5

class StrategyMR(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    bb_period: int = 20
    bb_std: float = 2.0

class StrategyVWAP(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    session_reset: str = "00:00"

class Strategies(BaseModel):
    model_config = ConfigDict(extra="ignore")
    TREND: StrategyTrend
    BO: StrategyBO
    MR: StrategyMR
    VWAP: StrategyVWAP

class DefaultSLTP(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rr: float = 1.5
    max_sl_pct: float = 0.7
    take_profit_pct: float = 1.05

class PositionSizing(BaseModel):
    model_config = ConfigDict(extra="ignore")
    method: Literal["expected_value_after_fee","fixed_fraction"] = "expected_value_after_fee"
    max_notional_usd: float = 200
    min_notional_usd: float = 5

class RiskPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    default_sl_tp: DefaultSLTP
    position_sizing: PositionSizing

class LeftOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    signal_confidence_floor: float = 0.55
    max_signals_per_15m: int = 2

class LeftNotifications(BaseModel):
    model_config = ConfigDict(extra="ignore")
    executed_only: bool = True
    template: Dict[str, str]

class LeftConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    filters: Filters
    strategies: Strategies
    risk: RiskPolicy
    output: LeftOutput
    notifications: LeftNotifications

# RIGHT
class Tier(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    weight: float
    ttl_minutes: int

class Sources(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tiers: List[Tier]
    languages: List[str]
    dedupe_minutes: int

class Hysteresis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    up: float = 0.1
    down: float = 0.08

class Signals(BaseModel):
    model_config = ConfigDict(extra="ignore")
    buzz_threshold: float = 0.6
    lock_events: List[str] = Field(default_factory=list)
    hysteresis: Hysteresis = Field(default_factory=Hysteresis)

class SafeMode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    block_new_positions: bool = True
    allow_reduce_only: bool = True

class RightNotifications(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: Dict[str,str]

class RightConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    sources: Sources
    signals: Signals
    safe_mode: SafeMode
    notifications: RightNotifications

# SOUL
class DailySchedule(BaseModel):
    model_config = ConfigDict(extra="ignore")
    time_local: str
    include: List[str]

class WeeklySchedule(BaseModel):
    model_config = ConfigDict(extra="ignore")
    weekday: str
    time_local: str
    include: List[str]

class MonthlySchedule(BaseModel):
    model_config = ConfigDict(extra="ignore")
    day: int
    time_local: str
    include: List[str]

class SoulSchedule(BaseModel):
    model_config = ConfigDict(extra="ignore")
    daily: DailySchedule
    weekly: WeeklySchedule
    monthly: MonthlySchedule

class ReportStyle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    friendly: bool = True
    pro_section: bool = True
    dedupe_minutes: int = 45

class SoulNotifications(BaseModel):
    model_config = ConfigDict(extra="ignore")
    telegram: TelegramConfig

class SoulConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    schedule: SoulSchedule
    report_style: ReportStyle
    notifications: SoulNotifications

# BODY
class MaintenanceWindow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    schedule: List[str] = Field(default_factory=list)

class Modes(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cold_start: Literal["WAIT","LEFT","RIGHT"] = "WAIT"
    maintenance_window: MaintenanceWindow
    pause_flag_file: str = "reload.flag"

class Reconcile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    interval_seconds: int = 60
    full_reconcile_on_start: bool = True

class CircuitBreakers(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_drawdown_day_pct: float = 4.0
    max_consecutive_losses: int = 5
    max_latency_ms: int = 2500
    on_trigger: List[Literal["pause_new","reduce_only"]] = ["pause_new","reduce_only"]

class DegradeModes(BaseModel):
    model_config = ConfigDict(extra="ignore")
    network_slow: Literal["reduce_only","hold_new_orders"]
    data_partial: Literal["hold_new_orders","reduce_only"]

class HealthChecks(BaseModel):
    model_config = ConfigDict(extra="ignore")
    exchange_latency_ms_warn: int = 1200
    telegram_ping_fail_warn: int = 2

class BodySLO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    executor_p95_ms: int = 900
    api_p95_ms: int = 300

class BodyTelemetry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    slo: BodySLO

class BodyConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    modes: Modes
    reconcile: Reconcile
    circuit_breakers: CircuitBreakers
    degrade_modes: DegradeModes
    healthchecks: HealthChecks
    telemetry: BodyTelemetry

# EXECUTOR
class ExchangeCfg(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    dry_run: bool = False
    api_keys_env: List[str] = Field(default_factory=list)
    max_retries: int = 3
    retry_backoff_seconds: int = 2

class OrderPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    allowed_types: List[str]
    slippage_cap_bps: int = 15
    time_in_force: str = "GTC"
    reduce_only_on_exit: bool = True

class RiskHooks(BaseModel):
    model_config = ConfigDict(extra="ignore")
    min_confidence: float = 0.55
    max_leverage: int = 5
    per_symbol_max_position_usd: int = 300

class ReconcilerCfg(BaseModel):
    model_config = ConfigDict(extra="ignore")
    check_open_orders_seconds: int = 30
    cancel_stale_minutes: int = 20

class TimeSync(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enable_ntp: bool = True
    max_clock_skew_ms: int = 150

class ExecutorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    exchange: ExchangeCfg
    order_policy: OrderPolicy
    risk_hooks: RiskHooks
    reconciler: ReconcilerCfg
    time_sync: TimeSync

# CRX_REPORT
class FileExport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    path: str = "data/reports"

class Channels(BaseModel):
    model_config = ConfigDict(extra="ignore")
    telegram: List[str] = Field(default_factory=list)
    file_export: FileExport = Field(default_factory=FileExport)

class TemplateSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    sections: List[str]

class Templates(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: TemplateSection
    pro: TemplateSection

class CrxReportConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    channels: Channels
    templates: Templates

# DATASET_REGISTRY
class Dataset(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    schema: List[str]
    retention_days: int
    refresh: Optional[str] = None

class DatasetRegistryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    datasets: Dict[str, Dataset]

# MODEL_REGISTRY
class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    path: str
    cache_ok: Optional[bool] = None
    lang: Optional[str] = None
    features: Optional[List[str]] = None
    members: Optional[List[str]] = None
    weights: Optional[List[float]] = None

class ModelRegistryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    models: Dict[str, ModelSpec]

# CAPITAL_POLICY
class RiskLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_account_leverage: int
    per_trade_risk_pct: float
    per_day_max_new_capital_usd: int

class SymbolPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_leverage: int
    prefer_mode: Literal["perp","spot"] = "perp"

class KPIs(BaseModel):
    model_config = ConfigDict(extra="ignore")
    weekly: Dict[str, float]
    monthly: Dict[str, float]
    big_kpi: Dict[str, str]

class AutoPause(BaseModel):
    model_config = ConfigDict(extra="ignore")
    on_dd_pct: float
    on_abnormal_behavior: bool = True

class Allocations(BaseModel):
    model_config = ConfigDict(extra="ignore")
    main_trading_pct: int
    free_zone_pct: int
    notes: Optional[str] = None

class CapitalPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    meta: Meta
    risk_limits: RiskLimits
    allocations: Allocations
    symbol_policies: Dict[str, SymbolPolicy]
    kpi: KPIs
    auto_pause: AutoPause

# ============================
# Bundle + Loader
# ============================

class ConfigBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    central: CentralConfig
    controller: ControllerConfig
    left: LeftConfig
    right: RightConfig
    soul: SoulConfig
    body: BodyConfig
    executor: ExecutorConfig
    crx_report: CrxReportConfig
    dataset_registry: DatasetRegistryConfig
    model_registry: ModelRegistryConfig
    capital_policy: CapitalPolicyConfig
    # Metainfo
    yaml_hashes: Dict[str, str] = Field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "versions": {
                "central": self.central.meta.version,
                "controller": self.controller.meta.version,
                "left": self.left.meta.version,
                "right": self.right.meta.version,
                "soul": self.soul.meta.version,
                "body": self.body.meta.version,
                "executor": self.executor.meta.version,
                "crx_report": self.crx_report.meta.version,
                "dataset_registry": self.dataset_registry.meta.version,
                "model_registry": self.model_registry.meta.version,
                "capital_policy": self.capital_policy.meta.version,
            },
            "hashes": self.yaml_hashes,
        }

def load_bundle(config_dir: str) -> ConfigBundle:
    files = {
        "central": "central.yaml",
        "controller": "controller.yaml",
        "left": "left.yaml",
        "right": "right.yaml",
        "soul": "soul.yaml",
        "body": "body.yaml",
        "executor": "executor.yaml",
        "crx_report": "crx_report.yaml",
        "dataset_registry": "dataset_registry.yaml",
        "model_registry": "model_registry.yaml",
        "capital_policy": "capital_policy.yaml",
    }
    data = {}
    hashes = {}

    for key, fname in files.items():
        path = os.path.join(config_dir, fname)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Thiếu file cấu hình: {path}")
        txt = _read_text(path)
        hashes[key] = _sha256_text(txt)
        data[key] = _read_yaml(path)

    bundle = ConfigBundle(
        central=CentralConfig(**data["central"]),
        controller=ControllerConfig(**data["controller"]),
        left=LeftConfig(**data["left"]),
        right=RightConfig(**data["right"]),
        soul=SoulConfig(**data["soul"]),
        body=BodyConfig(**data["body"]),
        executor=ExecutorConfig(**data["executor"]),
        crx_report=CrxReportConfig(**data["crx_report"]),
        dataset_registry=DatasetRegistryConfig(**data["dataset_registry"]),
        model_registry=ModelRegistryConfig(**data["model_registry"]),
        capital_policy=CapitalPolicyConfig(**data["capital_policy"]),
        yaml_hashes=hashes,
    )
    return bundle

# ============================
# CLI
# ============================

def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", dest="config_dir", default=os.getenv("CRX_CONFIG_DIR","./config"), help="Thư mục chứa YAML (mặc định: ./config)")
    args = parser.parse_args()
    b = load_bundle(args.config_dir)

    # gọi cross validators
    try:
        from validators import cross_validate
    except Exception as e:
        print("⚠️  Không tìm thấy validators.py hoặc lỗi import, bỏ qua cross-validate.", file=sys.stderr)
        cross_err = None
    else:
        cross_err = cross_validate(b)

    print(json.dumps({"summary": b.summary(), "cross_validate": "OK" if not cross_err else cross_err}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    _main()

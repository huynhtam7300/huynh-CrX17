"""
validators.py — Kiểm tra chéo giữa các file YAML của CrX 1.7.7
Cách dùng: được gọi tự động khi chạy config_loader.py
"""

import re
from typing import List, Optional, Any

from config_loader import ConfigBundle

TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _err(msg: str) -> str:
    return f"❌ {msg}"


def _get(obj: Any, *path: str):
    """
    Lấy giá trị theo chuỗi key an toàn cho cả object (thuộc tính Pydantic) lẫn dict.
    _get(ff, "funding_filter", "enabled")
    """
    cur = obj
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return cur


def validate_percent_allocations(b: ConfigBundle, errs: List[str]):
    alloc = b.capital_policy.allocations
    total = alloc.main_trading_pct + alloc.free_zone_pct
    if total != 100:
        errs.append(_err(f"capital_policy.allocations tổng ≠ 100 (={total})."))


def validate_controller_routes(b: ConfigBundle, errs: List[str]):
    routing = b.controller.routing
    for r in routing.allowed_routes:
        if r not in ("LEFT", "RIGHT", "WAIT"):
            errs.append(_err(f"controller.routing.allowed_routes có giá trị lạ: {r}"))
    if routing.default_route not in routing.allowed_routes:
        errs.append(_err("controller.routing.default_route không nằm trong allowed_routes."))


def validate_right_safe_mode(b: ConfigBundle, errs: List[str]):
    # Nếu controller yêu cầu kế thừa safe_mode từ RIGHT thì RIGHT phải bật safe_mode
    if b.controller.routing.inherit_safe_mode_from_right and not b.right.safe_mode.enabled:
        errs.append(_err("right.safe_mode phải bật khi controller.routing.inherit_safe_mode_from_right=true."))


def validate_model_registry_weights(b: ConfigBundle, errs: List[str]):
    for name, m in b.model_registry.models.items():
        if m.members is not None or m.weights is not None:
            if not m.members or not m.weights:
                errs.append(_err(f"model_registry.models.{name} thiếu members hoặc weights."))
                continue
            if len(m.members) != len(m.weights):
                errs.append(_err(f"model_registry.models.{name} số lượng members ≠ weights."))
            if abs(sum(m.weights) - 1.0) > 1e-6:
                errs.append(_err(f"model_registry.models.{name} tổng weights phải = 1.0 (hiện={sum(m.weights):.4f})."))


def validate_dataset_registry(b: ConfigBundle, errs: List[str]):
    ds = b.dataset_registry.datasets
    if "market_candles" in ds:
        need = {"timestamp", "open", "high", "low", "close"}
        got = set(ds["market_candles"].schema)
        if not need.issubset(got):
            errs.append(_err("dataset_registry.market_candles.schema thiếu các cột cơ bản (timestamp/open/high/low/close)."))
    if "nse_events" in ds:
        need = {"timestamp", "title", "tier", "score", "ttl_min"}
        if not set(ds["nse_events"].schema).issuperset(need):
            errs.append(_err("dataset_registry.nse_events.schema thiếu trường tối thiểu (timestamp/title/tier/score/ttl_min)."))


def validate_soul_schedule(b: ConfigBundle, errs: List[str]):
    try:
        daily = b.soul.schedule.daily.time_local
        weekly = b.soul.schedule.weekly.time_local
        monthly = b.soul.schedule.monthly.time_local
    except Exception:
        errs.append(_err("soul.schedule thiếu time_local."))
        return
    for t in (daily, weekly, monthly):
        if not TIME_RE.match(t):
            errs.append(_err(f"soul.schedule time_local sai định dạng HH:MM: {t}"))


def validate_central_tiebreak(b: ConfigBundle, errs: List[str]):
    w = b.central.decision.tie_breaker.weight
    s = sum(w.values())
    # Cho phép sai số lớn, chỉ cảnh báo khi lệch quá nhiều
    if abs(s - 1.0) > 0.5:
        errs.append(_err(f"central.decision.tie_breaker.weight có tổng ≠ ~1.0 (hiện={s:.3f})."))


def validate_executor_env(b: ConfigBundle, errs: List[str]):
    keys = b.executor.exchange.api_keys_env
    for k in keys:
        if not re.match(r"^[A-Z0-9_]+$", k or ""):
            errs.append(_err(f"executor.exchange.api_keys_env chứa tên ENV không hợp lệ: {k}"))


def validate_slo_positive(b: ConfigBundle, errs: List[str]):
    slo = b.central.telemetry.slo
    if min(slo.central_p95_ms, slo.telegram_p95_ms, slo.nse_p95_ms) <= 0:
        errs.append(_err("central.telemetry.slo phải là số dương."))
    if min(b.body.telemetry.slo.executor_p95_ms, b.body.telemetry.slo.api_p95_ms) <= 0:
        errs.append(_err("body.telemetry.slo phải là số dương."))


def validate_left_filters(b: ConfigBundle, errs: List[str]):
    ff = b.left.filters
    # funding_filter là dict trong model Filters -> dùng _get
    enabled = _get(ff, "funding_filter", "enabled")
    max_abs_rate = _get(ff, "funding_filter", "max_abs_rate")
    if enabled and max_abs_rate is not None and max_abs_rate > 0.1:
        errs.append(_err("left.filters.funding_filter.max_abs_rate quá cao (>0.1)."))


def validate_right_sources(b: ConfigBundle, errs: List[str]):
    if not b.right.sources.tiers:
        errs.append(_err("right.sources.tiers trống."))
    for t in b.right.sources.tiers:
        if t.weight <= 0 or t.ttl_minutes <= 0:
            errs.append(_err("right.sources.tiers.* weight/ttl_minutes phải > 0."))


def validate_capital_symbols(b: ConfigBundle, errs: List[str]):
    if not b.capital_policy.symbol_policies:
        errs.append(_err("capital_policy.symbol_policies trống."))


def cross_validate(bundle: ConfigBundle) -> Optional[str]:
    """Trả về None nếu OK, hoặc chuỗi lỗi (nhiều dòng) nếu có lỗi."""
    errs: List[str] = []
    validate_percent_allocations(bundle, errs)
    validate_controller_routes(bundle, errs)
    validate_right_safe_mode(bundle, errs)
    validate_model_registry_weights(bundle, errs)
    validate_dataset_registry(bundle, errs)
    validate_soul_schedule(bundle, errs)
    validate_central_tiebreak(bundle, errs)
    validate_executor_env(bundle, errs)
    validate_slo_positive(bundle, errs)
    validate_left_filters(bundle, errs)
    validate_right_sources(bundle, errs)
    validate_capital_symbols(bundle, errs)

    if errs:
        return "\n".join(errs)
    return None
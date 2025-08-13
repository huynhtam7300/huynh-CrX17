# configs/feature_flags_loader.py
# CrX 1.7 – Feature Flags Loader (safe to add; import when ready)
from __future__ import annotations
import os
import sys
import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

try:
    import yaml  # pip install pyyaml
except Exception as e:
    print("⚠️  PyYAML chưa được cài. Chạy: pip install pyyaml", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "configs" / "feature_flags.yaml"

# --------- Utilities ---------
def deep_get(d: dict, path: str, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def deep_set(d: dict, path: str, value: Any):
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value

def deep_merge(a: dict, b: dict) -> dict:
    """
    Merge dict b into a (non-destructive for nested dicts).
    Scalars/lists in b overwrite a. Dicts are merged recursively.
    """
    out = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def env_overrides(prefix: str) -> Dict[str, Any]:
    """
    Convert ENV keys like FEATURE__modules__decision__meta_controller__enabled=true
    to a nested dict at path: modules.decision.meta_controller.enabled
    """
    res: Dict[str, Any] = {}
    plen = len(prefix)
    for k, v in os.environ.items():
        if not k.startswith(prefix):
            continue
        path = k[plen:].strip("_").replace("__", ".")
        # Coerce common types
        vv: Any = v
        lv = v.lower()
        if lv in ("true", "false"):
            vv = (lv == "true")
        else:
            # try int/float
            try:
                if "." in v:
                    vv = float(v)
                else:
                    vv = int(v)
            except ValueError:
                pass
        deep_set(res, path, vv)
    return res

# --------- Core Loader ---------
class FeatureFlags:
    def __init__(self, data: dict, effective: dict, chosen_phase: str, safety_fail_closed: bool, prefix: str):
        self._raw = data
        self._eff = effective
        self._phase = chosen_phase
        self._safety_fail_closed = safety_fail_closed
        self._env_prefix = prefix

    # Public API
    def phase(self) -> str:
        return self._phase

    def get(self, path: str, default=None):
        return deep_get(self._eff, path, default)

    def is_on(self, path: str, default: Optional[bool] = None) -> bool:
        val = self.get(path, default)
        if isinstance(val, bool):
            return val
        # Fail-closed: if not explicitly True/False, treat as False when safety is strict
        if self._safety_fail_closed:
            return False
        return bool(val)

    def require(self, paths: List[str]) -> Tuple[bool, List[str]]:
        missing = [p for p in paths if not self.is_on(p, False)]
        return (len(missing) == 0, missing)

    def raw(self) -> dict:
        return self._raw

    def effective(self) -> dict:
        return self._eff

# --------- Validation ---------
def validate_rules(eff: dict) -> List[str]:
    """
    Validate requires/excludes/safety_fail_closed rules.
    Return list of warnings/errors (strings). Empty list means OK.
    """
    msgs: List[str] = []

    reqs = deep_get(eff, "rules.requires", []) or []
    for rule in reqs:
        cond = rule.get("if")
        thens = rule.get("then") or []
        if not cond or not isinstance(thens, list):
            continue
        cond_val = deep_get(eff, cond, False)
        if cond_val:
            for p in thens:
                if not deep_get(eff, p, False):
                    msgs.append(f"[requires] '{cond}' bật nhưng '{p}' đang OFF")

    excludes = deep_get(eff, "rules.excludes", []) or []
    for rule in excludes:
        any_of = rule.get("any_of") or []
        if not isinstance(any_of, list) or len(any_of) < 2:
            continue
        on_count = sum(1 for p in any_of if deep_get(eff, p, False))
        if on_count > 1:
            note = rule.get("note", "")
            msgs.append(f"[excludes] Các cờ loại trừ đang đồng thời ON: {any_of}. {note}")

    # safety_fail_closed: enforce behavior only by messaging; actual block happens at call sites
    sfc = deep_get(eff, "rules.safety_fail_closed", []) or []
    for rule in sfc:
        key = rule.get("key")
        behavior = rule.get("behavior")
        if key and behavior == "block_on_unknown":
            # if key path missing or not bool, warn (the caller should treat as blocked)
            val = deep_get(eff, key, None)
            if val is None:
                msgs.append(f"[safety_fail_closed] '{key}' không xác định → nên block theo quy tắc.")
    return msgs

# --------- Phase Resolution ---------
def resolve_phase(data: dict, phase_arg: Optional[str]) -> str:
    defaults = data.get("defaults") or {}
    phases = data.get("phases") or {}
    phase = (phase_arg or defaults.get("phase") or "CORE").strip().upper()
    if phase not in phases or not deep_get(phases, f"{phase}.enabled", False):
        # fallback CORE if chosen invalid
        phase = "CORE"
    return phase

def apply_phase(data: dict, chosen: str) -> dict:
    # Start with defaults
    eff = {"defaults": data.get("defaults") or {}}
    # Copy entire structure as baseline for introspection (meta, rules, modules, etc.)
    for key in ("meta", "scopes", "phases", "modules", "rules", "phase_overrides"):
        if key in data:
            eff[key] = data[key]
    # Merge phase_overrides[CORE] first, then chosen (if different)
    overrides = data.get("phase_overrides") or {}
    core_ov = overrides.get("CORE") or {}
    eff = deep_merge(eff, core_ov)
    if chosen != "CORE":
        ch_ov = overrides.get(chosen) or {}
        eff = deep_merge(eff, ch_ov)
    # Store selected phase
    eff["selected_phase"] = chosen
    return eff

def apply_env_overrides(eff: dict, data: dict) -> dict:
    prefix = deep_get(data, "defaults.env_override_prefix", "FEATURE__")
    env = env_overrides(prefix)
    if env:
        eff = deep_merge(eff, env)
    return eff

# --------- Public load() ---------
def load_flags(path: Optional[Path] = None, phase: Optional[str] = None) -> FeatureFlags:
    cfg_path = path or CFG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {cfg_path}")

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    chosen = resolve_phase(raw, phase)
    eff = apply_phase(raw, chosen)
    eff = apply_env_overrides(eff, raw)

    safety_fail_closed = bool(deep_get(raw, "defaults.safety_fail_closed", True))
    prefix = deep_get(raw, "defaults.env_override_prefix", "FEATURE__")

    # Attach defaults at root for easy reads (optional)
    eff["__defaults"] = raw.get("defaults") or {}

    # Validation (warnings)
    problems = validate_rules(eff)
    if problems:
        eff["__validation_warnings"] = problems

    return FeatureFlags(raw, eff, chosen, safety_fail_closed, prefix)

# --------- CLI for quick check ---------
def _print_summary(ff: FeatureFlags):
    print(f"Phase được chọn: {ff.phase()}")
    if ff.effective().get("__validation_warnings"):
        print("\n⚠️  Cảnh báo cấu hình:")
        for m in ff.effective()["__validation_warnings"]:
            print(" -", m)

    def flag(path: str):
        return "ON " if ff.is_on(path, False) else "OFF"

    print("\n=== Modules chính ===")
    print(f"- collector.market_collector     [{flag('modules.collector.market_collector.enabled')}]")
    print(f"- analyzer.technical_analyzer    [{flag('modules.analyzer.technical_analyzer.enabled')}]")
    print(f"- aggregators.left_agg           [{flag('modules.analyzer.aggregators.left_agg.enabled') or ff.is_on('modules.aggregators.left_agg.enabled', False)}]")
    print(f"- decision.decision_maker        [{flag('modules.decision.decision_maker.enabled')}]")
    print(f"- decision.meta_controller       [{flag('modules.decision.meta_controller.enabled')}]")
    print(f"- capital.capital_gate           [{flag('modules.capital.capital_gate.enabled')}]")
    print(f"- capital.funding_optimizer      [{flag('modules.capital.funding_optimizer.enabled')}]  mode={ff.get('modules.capital.funding_optimizer.flags.mode','off')}")
    print(f"- kpi.kpi_tracker                [{flag('modules.kpi.kpi_tracker.enabled')}]")
    print(f"- execution.order_executor       [{flag('modules.execution.order_executor.enabled')}]")
    print(f"- execution.order_monitor        [{flag('modules.execution.order_monitor.enabled')}]")
    print(f"- reports.dashboard_min          [{flag('modules.reports_dashboard.dashboard_min.enabled')}]")
    print(f"- reports.dashboard_full         [{flag('modules.reports_dashboard.dashboard_full.enabled')}]")

def main_cli():
    p = argparse.ArgumentParser(description="CrX Feature Flags Loader")
    p.add_argument("--phase", type=str, default=None, help="CORE/A/B/C (overrides defaults.phase)")
    p.add_argument("--print", action="store_true", help="In tóm tắt các module chính")
    args = p.parse_args()

    ff = load_flags(phase=args.phase)
    if args.print:
        _print_summary(ff)
    else:
        # Mặc định in phase + cảnh báo
        _print_summary(ff)

if __name__ == "__main__":
    main_cli()
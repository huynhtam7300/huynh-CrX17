# config/config.py — shim tương thích: CONFIG đọc từ bundle YAML
from __future__ import annotations
import os
from typing import Any, Mapping

# Nạp load_bundle bền vững (3 lớp: relative -> top-level -> path)
try:
    from .config_loader import load_bundle
except Exception:
    try:
        from config_loader import load_bundle  # khi chạy như package root
    except Exception:
        import importlib.util, pathlib, sys
        _here = pathlib.Path(__file__).resolve().parent
        _p = _here / "config_loader.py"
        spec = importlib.util.spec_from_file_location("crx_cfg_loader", str(_p))
        _m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_m)  # type: ignore
        load_bundle = _m.load_bundle  # type: ignore

class _Node(dict):
    """Dict hỗ trợ truy cập cả attribute lẫn key, case-insensitive."""
    def __init__(self, d: Mapping[str, Any] | None = None):
        super().__init__()
        if d:
            for k, v in d.items():
                self[_normalize(k)] = self._wrap(v)
    def __getattr__(self, name: str) -> Any:
        key = _normalize(name)
        if key in self:
            return self[key]
        raise AttributeError(name)
    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(_normalize(key))
    def get(self, key: str, default=None) -> Any:
        return super().get(_normalize(key), default)
    @staticmethod
    def _wrap(v: Any) -> Any:
        if isinstance(v, dict):
            return _Node(v)
        return v

def _normalize(s: str) -> str:
    return str(s).strip().lower()

def _bundle_to_node() -> _Node:
    cfg_dir = os.getenv("CRX_CONFIG_DIR", "./config")
    b = load_bundle(cfg_dir)

    central = b.central.model_dump(); controller = b.controller.model_dump()
    left = b.left.model_dump(); right = b.right.model_dump(); soul = b.soul.model_dump()
    body = b.body.model_dump(); executor = b.executor.model_dump()
    crx_report = b.crx_report.model_dump(); dataset_registry = b.dataset_registry.model_dump()
    model_registry = b.model_registry.model_dump(); capital_policy = b.capital_policy.model_dump()

    root = {
        "central": central, "CENTRAL": central,
        "controller": controller, "CONTROLLER": controller,
        "left": left, "LEFT": left,
        "right": right, "RIGHT": right,
        "soul": soul, "SOUL": soul,
        "body": body, "BODY": body,
        "executor": executor, "EXECUTOR": executor,
        "crx_report": crx_report, "CRX_REPORT": crx_report,
        "dataset_registry": dataset_registry, "DATASET_REGISTRY": dataset_registry,
        "model_registry": model_registry, "MODEL_REGISTRY": model_registry,
        "capital_policy": capital_policy, "CAPITAL_POLICY": capital_policy,
        "exchange": executor.get("exchange", {}), "EXCHANGE": executor.get("exchange", {}),
        "order_policy": executor.get("order_policy", {}), "ORDER_POLICY": executor.get("order_policy", {}),
        "risk_hooks": executor.get("risk_hooks", {}), "RISK_HOOKS": executor.get("risk_hooks", {}),
    }
    return _Node(root)

# Biến cấu hình tương thích
CONFIG: _Node = _bundle_to_node()

def get_bundle():
    cfg_dir = os.getenv("CRX_CONFIG_DIR", "./config")
    return load_bundle(cfg_dir)
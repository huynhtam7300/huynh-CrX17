# tools/print_pipeline.py
from pathlib import Path

# pyyaml là tùy chọn. Nếu chưa cài, script vẫn chạy và coi như tất cả flag = OFF.
try:
    import yaml  # pip install pyyaml
except Exception:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
CFG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"

def on(b): 
    return "ON " if b else "OFF"

def load_flags():
    flags = {"enable_bandit": False, "enable_funding": False, "enable_kpi": False}
    ff = CFG_DIR / "feature_flags.yaml"
    if ff.exists() and yaml is not None:
        try:
            raw = yaml.safe_load(ff.read_text(encoding="utf-8")) or {}
            core = raw.get("core") or {}
            flags.update(
                {k: bool(core.get(k, False)) for k in flags.keys()}
            )
        except Exception:
            pass
    return flags

def check_artifacts():
    names = [
        "btc_candles.json",
        "eth_candles.json",
        "decision_history.json",
        "trade_history.json",
    ]
    return {n: (DATA_DIR / n).exists() for n in names}

def main():
    flags = load_flags()
    print("=== CrX 1.7 – Active Pipeline (CORE → Phase A) ===")
    print(f"- Collector         : core/collector/market_collector.py      [{on(True)}]")
    print(f"- Feature ETL       : cleaner → alignment → selector           [{on(True)}]")
    print(f"- Analyzer (Left)   : technical_analyzer + left_agg            [{on(True)}]")
    print(f"- Decision Maker    : core/decision/decision_maker.py          [{on(True)}]")
    print(f"- Meta-Controller   : core/decision/meta_controller.py         [{on(True)}]")
    print(f"- Bandit Optimizer  : core/capital/bandit_optimizer.py         [{on(flags['enable_bandit'])}]")
    print(f"- Funding Optimizer : core/capital/funding_optimizer.py        [{on(flags['enable_funding'])}]")
    print(f"- KPI Tracker       : core/kpi/kpi_tracker.py                  [{on(flags['enable_kpi'])}]")
    print(f"- Order Executor    : core/execution/order_executor.py         [{on(True)}]")
    print(f"- Order Monitor     : core/execution/order_monitor.py          [{on(True)}]")
    print(f"- Notifier          : notifier/notify_telegram.py              [{on(True)}]")
    print(f"- Daily Report      : report/report_daily.py                   [{on(True)}]")

    print("\n=== Configs in use ===")
    print(f"- configs/feature_flags.yaml  : {'FOUND' if (CFG_DIR/'feature_flags.yaml').exists() else 'MISSING'}")
    print(f"- configs/risk_limits.yaml    : {'FOUND' if (CFG_DIR/'risk_limits.yaml').exists() else 'MISSING'}")
    print(f"- configs/kpi_policy.yaml     : {'FOUND' if (CFG_DIR/'kpi_policy.yaml').exists() else 'MISSING'}")
    print(f"- .env                        : {'FOUND' if (ROOT/'.env').exists() else 'MISSING'}")

    print("\n=== Data Artifacts ===")
    for name, ok in check_artifacts().items():
        print(f"- {name:22} : {'OK' if ok else 'MISSING'}")

if __name__ == "__main__":
    main()
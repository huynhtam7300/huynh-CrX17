import yaml

def load_flags():
    try:
        with open("configs/feature_flags.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        # mặc định bật hết nếu thiếu file
        return {"core": {"enable_bandit": True, "enable_funding": True, "enable_kpi": True}}

FLAGS = load_flags()

def main():
    from pathlib import Path
    import pandas as pd
    from utils.io_utils import read_json

    from core.collector.market_collector import run as collect_run
    from core.risk.risk_intel import atr_percent
    from core.aggregators.left_agg import aggregate as left_aggregate
    from core.decision.meta_controller import meta_decide
    from core.risk.safety_layer import validate_order_basic
    from core.execution.order_executor import place_order
    from core.execution.order_monitor import poll_until_final
    from core.memory.decision_logger import log_decision
    from core.memory.trade_logger import log_trade
    from notifier.notify_telegram import send_telegram_message
    from configs.config import RISK_LIMITS, CONFIG
    from core.kpi.kpi_tracker import risk_factor as kpi_risk_factor
    from core.capital.funding_optimizer import adjust_size_by_funding
    from core.capital.bandit_optimizer import adjust_size_by_bandit

    def _load_df(path: Path) -> pd.DataFrame:
        data = read_json(path, {"open": [], "high": [], "low": [], "close": [], "volume": []})
        return pd.DataFrame(data)

    # 1) Thu thập dữ liệu
    collect_run()

    # 2) Tín hiệu LEFT
    df_btc = _load_df(Path("data/btc_candles.json"))
    if df_btc.empty or len(df_btc) < 50:
        send_telegram_message("⚠️ Not enough data")
        return

    left_sig = left_aggregate(df_btc)
    left_sig["risk"] = max(left_sig.get("risk", 0.0), atr_percent(df_btc) / 100.0)

    # 3) KPI factor theo flag
    if FLAGS.get("core", {}).get("enable_kpi", True):
        kpi_factor = kpi_risk_factor()
        kpi_reason = ["kpi_enabled"]
    else:
        kpi_factor = 1.0
        kpi_reason = ["kpi_disabled"]

    # 4) Meta decide (base size sau KPI/ATR)
    base_size = float(CONFIG.get("default_order", {}).get("size_pct", 0.5))
    meta = meta_decide(
        left_sig,
        atr_pct=left_sig["risk"] * 100.0,
        base_size_pct=base_size,
        kpi_risk_factor=kpi_factor
    )

    symbol = CONFIG.get("default_order", {}).get("symbol", "BTCUSDT")

    # 5) Bandit theo flag
    if meta["action"] in ("BUY", "SELL") and FLAGS.get("core", {}).get("enable_bandit", True):
        bandit = adjust_size_by_bandit(symbol, meta["action"], meta["suggested_size"])
    else:
        bandit = {"size": meta["suggested_size"], "factor": 1.0,
                  "reason": ["bandit_disabled" if meta["action"] in ("BUY","SELL") else "no_trade"]}

    meta["suggested_size_bandit"] = bandit["size"]
    meta["bandit_reason"] = bandit["reason"]
    meta["bandit_factor"] = bandit["factor"]

    # 6) Funding theo flag (áp trên size đã qua bandit)
    if meta["action"] in ("BUY", "SELL") and FLAGS.get("core", {}).get("enable_funding", True):
        funding = adjust_size_by_funding(symbol, meta["action"], meta["suggested_size_bandit"])
    else:
        funding = {"size": meta["suggested_size_bandit"], "reason": ["funding_disabled"
                   if meta["action"] in ("BUY","SELL") else "no_trade"], "rate": 0.0}

    meta["suggested_size_funding"] = funding["size"]
    meta["funding_reason"] = funding["reason"]
    meta["funding_rate"] = funding.get("rate", 0.0)

    # 7) Log quyết định
    log_decision({
        **left_sig,
        "meta_action": meta["action"],
        "suggested_size": meta["suggested_size"],
        "suggested_size_bandit": meta["suggested_size_bandit"],
        "suggested_size_funding": meta["suggested_size_funding"],
        "meta_reason": meta["meta_reason"],
        "bandit_reason": meta["bandit_reason"],
        "bandit_factor": meta["bandit_factor"],
        "funding_reason": meta["funding_reason"],
        "funding_rate": meta["funding_rate"],
        "kpi_note": kpi_reason
    })
    send_telegram_message(f"🤖 Meta: {meta}")

    # 8) Safety & Thực thi
    if meta["action"] in ("BUY", "SELL") and meta["suggested_size_funding"] > 0:
        leverage = int(CONFIG.get("default_order", {}).get("leverage", 1))
        notional = float(CONFIG.get("default_order", {}).get("notional_usdt", 50))

        desired = {"side": meta["action"], "size_pct": meta["suggested_size_funding"], "leverage": leverage}
        ok, reason = validate_order_basic(desired, RISK_LIMITS)
        if not ok:
            send_telegram_message(f"⛔ Blocked by Safety: {reason}")
            return

        r = place_order(symbol, meta["action"], size_pct=meta["suggested_size_funding"],
                        leverage=leverage, notional_usdt=notional)
        log_trade({"symbol": symbol, "side": meta["action"], **r})

        final = poll_until_final(symbol, r.get("order_id"), r.get("client_order_id"),
                                 timeout_sec=20, interval_sec=1.0)
        merged = {
            "symbol": symbol,
            "side": meta["action"],
            "status": final.get("status", r.get("status")),
            "cumQty": final.get("executedQty", r.get("cumQty", "0")),
            "avgPrice": final.get("avgPrice", r.get("avgPrice", "0")),
            "order_id": r.get("order_id"),
            "client_order_id": r.get("client_order_id") or r.get("order_uid")
        }
        log_trade(merged)
        send_telegram_message(f"📥 Order update: {merged}")
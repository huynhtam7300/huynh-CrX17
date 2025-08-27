#!/usr/bin/env bash
# scripts/phaseB_cycle.sh
set -euo pipefail

cd /home/crx/CrX17
source .venv/bin/activate

echo "[cycle] start $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# 1) Thu thập & ETL
python -m core.collector.market_collector
python -m core.feature_etl.cleaner
python -m core.feature_etl.alignment
python -m core.feature_etl.selector
python -m core.analyzer.technical_analyzer

# 2) Tổng hợp LEFT để ra quyết định thô
python -m core.aggregators.left_agg

# 3) GATE theo floor + ép symbol (chỉ xuất last_decision.json khi đạt ngưỡng)
python tools/append_latest_and_export.py || true

# 4) Tối ưu funding + thực thi + giám sát + đồng bộ PnL
python -m core.capital.funding_optimizer
python -m core.execution.order_executor
python -m core.execution.order_monitor
python -m core.evaluator.pnl_sync

echo "[cycle] done $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
#!/usr/bin/env bash
set -e
echo "[migrate] Kiểm tra & tạo file dữ liệu mặc định..."
mkdir -p data
touch data/decision_history.json data/trade_history.json data/system_health.log data/risk_incidents.log
echo "[]" > data/decision_history.json
echo "[]" > data/trade_history.json
echo "[migrate] Done."
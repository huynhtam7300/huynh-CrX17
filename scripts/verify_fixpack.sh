#!/usr/bin/env bash
set -euo pipefail
cd /home/crx/CrX17

echo "=== Build / Commit ==="
git rev-parse HEAD

echo "=== ENV floors (chỉ đọc) ==="
grep -nE '^CRX_OPEN_CONF_FLOOR=|^CRX_CLOSE_CONF_FLOOR=|^CRX_ENABLE_ORDER_EXECUTOR=' .env || true

echo "=== Signatures ==="
# 1) append_latest_and_export.py phải có main() và in [sync] latest:
grep -n '\[sync\] latest:' tools/append_latest_and_export.py

# 2) eod_kpi_notify.py phải có UTC-safe + lock chống gửi trùng
grep -n 'UTC = getattr(dt' tools/eod_kpi_notify.py
grep -n '_can_send_today' tools/eod_kpi_notify.py

# 3) phaseB_cycle.sh đủ 5 bước (collector → decision → append → meta → executor)
grep -n 'market_collector' scripts/phaseB_cycle.sh
grep -n 'decision_maker'    scripts/phaseB_cycle.sh
grep -n 'append_latest_and_export.py' scripts/phaseB_cycle.sh
grep -n 'meta_controller'   scripts/phaseB_cycle.sh
grep -n 'order_executor'    scripts/phaseB_cycle.sh

echo "=== Smoke once ==="
./scripts/smoke_phaseB.sh || true

echo "=== Recent log ==="
tail -n 120 logs/runner.log | egrep 'sync|Meta-Controller|decision source|EXECUTE|skip' || true

echo "=== OK (verify_fixpack) ==="
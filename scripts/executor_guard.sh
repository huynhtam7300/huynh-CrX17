#!/usr/bin/env bash
# scripts/executor_guard.sh
set -euo pipefail

cd /home/crx/CrX17
source .venv/bin/activate

# Áp dụng gate + ép symbol trước khi executor đọc file
python tools/append_latest_and_export.py || true

# Thực thi lệnh
python -m core.execution.order_executor
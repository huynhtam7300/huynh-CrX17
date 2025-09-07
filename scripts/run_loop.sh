#!/usr/bin/env bash
set -euo pipefail
export CRX_PROFILE="${CRX_PROFILE:-profiles/crx_phaseB.yaml}"
mkdir -p data logs

# gửi noti boot 1 lần đầu
CRX_BOOT_NOTI=1 python3 tools/notifier.py || true

while true; do
  echo "[loop] $(date -Is)"
  bash scripts/phaseB_cycle.sh
  python3 tools/soul_macro_report.py
  # noti nếu bias thay đổi / vượt ngưỡng
  python3 tools/notifier.py || true
  sleep 60
done
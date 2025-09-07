#!/usr/bin/env bash
set -euo pipefail
export CRX_PROFILE="${CRX_PROFILE:-profiles/crx_phaseB.yaml}"
mkdir -p data logs

# Gửi noti khởi động nếu bật cờ TG_BOOT_NOTI=1 trong .env
if [[ "${TG_ENABLE:-0}" == "1" && "${TG_BOOT_NOTI:-0}" == "1" ]]; then
  CRX_BOOT_NOTI=1 python3 tools/notifier.py || true
fi

while true; do
  echo "[loop] $(date -Is)"
  bash scripts/phaseB_cycle.sh
  python3 tools/soul_macro_report.py
  # Noti macro nếu có thay đổi (chỉ khi TG_ENABLE=1)
  if [[ "${TG_ENABLE:-0}" == "1" ]]; then
    python3 tools/notifier.py || true
  fi
  sleep 60
done
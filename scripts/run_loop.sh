#!/usr/bin/env bash
# scripts/run_loop.sh
# Vòng chạy chịu lỗi: không exit khi collector/pnl_sync lỗi vặt
set -u
export CRX_PROFILE="${CRX_PROFILE:-profiles/crx_phaseB.yaml}"
mkdir -p data logs

# Noti khởi động (chỉ khi bạn bật trong .env)
if [[ "${TG_ENABLE:-0}" == "1" && "${TG_BOOT_NOTI:-0}" == "1" ]]; then
  CRX_BOOT_NOTI=1 python3 tools/notifier.py || true
fi

while true; do
  echo "[loop] $(date -Is)"
  # chịu lỗi: nếu script con fail, chỉ log cảnh báo
  if ! bash scripts/phaseB_cycle.sh; then
    echo "[loop] WARN: phaseB_cycle exited non-zero" | tee -a run.log
  fi
  python3 tools/soul_macro_report.py || true
  if [[ "${TG_ENABLE:-0}" == "1" ]]; then
    python3 tools/notifier.py || true
  fi
  sleep 60
done
set -euo pipefail
export CRX_PROFILE="${CRX_PROFILE:-profiles/crx_phaseB.yaml}"
mkdir -p data logs
while true; do
  echo "[loop] $(date -Is)"
  bash scripts/phaseB_cycle.sh
  python3 tools/soul_macro_report.py
  sleep 60
done

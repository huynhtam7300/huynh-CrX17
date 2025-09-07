#!/usr/bin/env bash
set -euo pipefail

echo "=== CrX Smoke Phase B ==="
echo "CWD: $(pwd)"
echo "Profile (env): ${CRX_PROFILE:-<unset>}"
echo "----- files -----"
ls -l config/pro_plus.yaml || true
ls -l profiles/crx_phaseB.yaml || true
ls -l profiles/crx_phaseC.yaml || true

echo "----- profile summary (Phase B) -----"
egrep -n -i 'symbol|symbols|max_|floor|booster|buzz|lock' profiles/crx_phaseB.yaml || true

echo "----- pro_plus knobs -----"
egrep -n -i 'booster|buzz|lock|ladder|phase|floor|ttl|size' config/pro_plus.yaml || true

echo "----- runtime quick checks -----"
# floors từ env hay profile đều in ra ở log executor
tail -n 200 run.log | egrep -i 'floor|booster|buzz|lock' || true

echo "----- macro report -----"
python3 tools/soul_macro_report.py
jq . data/macro_bias.json 2>/dev/null || cat data/macro_bias.json

echo "OK: smoke done."
import json, os, time
from datetime import datetime, timezone

# vị trí file output
OUT = "data/macro_bias.json"

# giá trị an toàn mặc định (neutral) – Phase B: report-only
payload = {
  "ts": datetime.now(timezone.utc).astimezone().isoformat(),
  "version": "soul-macro-v1",
  "macro_bias_3m": "neutral",
  "macro_bias_6m": "neutral",
  "macro_conf": 0.50,
  "data_coverage": {"crypto_A": True, "macro_B": False, "optional_C": False},
  "notes": "bootstrap writer: Phase B report-only; sẽ thay bằng tính năng SOUL-MACRO đầy đủ."
}

os.makedirs("data", exist_ok=True)
with open(OUT, "w") as f:
    json.dump(payload, f, indent=2, ensure_ascii=False)

print(f"[soul-macro] wrote {OUT} at {payload['ts']}")

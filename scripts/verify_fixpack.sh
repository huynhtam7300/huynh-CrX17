#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; YEL='\033[1;33m'; GRN='\033[0;32m'; NC='\033[0m'
fail(){ echo -e "${RED}FAIL${NC} - $*"; exit 1; }
warn(){ echo -e "${YEL}WARN${NC} - $*"; }
pass(){ echo -e "${GRN}PASS${NC} - $*"; }

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
[ -n "$repo_root" ] || fail "Không phải thư mục git."
cd "$repo_root"

echo "==[ CrX PhaseB Verify Fixpack ]=="
echo "Repo : $repo_root"
echo "HEAD : $(git rev-parse HEAD)"
git fetch -q origin
head_sha="$(git rev-parse HEAD)"
main_sha="$(git rev-parse origin/main)"
if [ "$head_sha" != "$main_sha" ]; then
  fail "HEAD != origin/main. Hãy git pull/reset cho sạch."
else
  pass "Git sạch (HEAD == origin/main)."
fi

# Yêu cầu công cụ
command -v jq >/dev/null 2>&1 || fail "Thiếu 'jq'. sudo apt install -y jq"
pass "Đủ công cụ cơ bản (jq)."

# Đọc .env
ENV_FILE=".env"
[ -f "$ENV_FILE" ] || warn ".env không tìm thấy ở $ENV_FILE (bỏ qua check env nếu bạn đặt nơi khác)."
get_env(){ grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d'=' -f2- || true; }

OPEN_FLOOR="$(get_env CRX_OPEN_CONF_FLOOR)"
CLOSE_FLOOR="$(get_env CRX_CLOSE_CONF_FLOOR)"
ALLOW_ADD="$(get_env CRX_ALLOW_ADD)"

[ -n "${OPEN_FLOOR:-}" ] || warn "CRX_OPEN_CONF_FLOOR chưa đặt trong .env (yêu cầu Phase B: 0.65)."
[ -n "${CLOSE_FLOOR:-}" ] || warn "CRX_CLOSE_CONF_FLOOR chưa đặt trong .env (yêu cầu Phase B: 0.60)."
[ -n "${ALLOW_ADD:-}" ] || warn "CRX_ALLOW_ADD chưa đặt (nên =0 ở Phase B)."

if [ -n "${OPEN_FLOOR:-}" ] && awk "BEGIN{exit !($OPEN_FLOOR>=0.65)}"; then
  pass "OPEN_FLOOR ($OPEN_FLOOR) ≥ 0.65"
else
  warn "OPEN_FLOOR ($OPEN_FLOOR) < 0.65 theo policy Phase B."
fi
if [ -n "${CLOSE_FLOOR:-}" ] && awk "BEGIN{exit !($CLOSE_FLOOR>=0.60)}"; then
  pass "CLOSE_FLOOR ($CLOSE_FLOOR) ≥ 0.60"
else
  warn "CLOSE_FLOOR ($CLOSE_FLOOR) < 0.60 theo policy Phase B."
fi
if [ -n "${ALLOW_ADD:-}" ] && [ "${ALLOW_ADD:-0}" = "0" ]; then
  pass "CRX_ALLOW_ADD=0 (không cộng thêm vị thế)"; 
else
  warn "CRX_ALLOW_ADD khác 0 — cân nhắc đặt 0 ở Phase B."
fi

# Kiểm tra file quyết định gần nhất
DEC_FILE="last_decision.json"
if [ -f "$DEC_FILE" ]; then
  conf="$(jq -r '.confidence // empty' "$DEC_FILE")"
  sym="$(jq -r '.symbol // empty' "$DEC_FILE")"
  dec="$(jq -r '.decision // empty' "$DEC_FILE")"
  echo "Decision: decision=$dec confidence=$conf symbol=$sym"

  [ -n "$sym" ] || warn "Thiếu 'symbol' trong $DEC_FILE (thấy log 'sym=None'). Cần bổ sung khi export."
  if [ -n "${OPEN_FLOOR:-}" ] && [ -n "$conf" ]; then
    awk -v c="$conf" -v f="$OPEN_FLOOR" 'BEGIN{ if (c>=f) exit 0; else exit 1 }' \
      && pass "confidence ($conf) đạt ngưỡng mở ($OPEN_FLOOR)" \
      || warn "confidence ($conf) < ngưỡng mở ($OPEN_FLOOR) — Phase B sẽ không mở mới."
  fi
else
  warn "Không thấy $DEC_FILE — bỏ qua check decision."
fi

# Kiểm tra script smoke
if [ -x "scripts/smoke_phaseB.sh" ]; then
  pass "Có scripts/smoke_phaseB.sh (executable)."
else
  warn "Thiếu hoặc chưa chmod +x scripts/smoke_phaseB.sh"
fi

# Nhắc vị trí file export có 'symbol'
if grep -R --line-number -E '"symbol"\s*:' tools/append_latest_and_export.py >/dev/null 2>&1; then
  pass "append_latest_and_export.py có string 'symbol' (kiểm tra thô)."
else
  warn "Chưa thấy 'symbol' trong append_latest_and_export.py (check & bổ sung khi build JSON)."
fi

echo "==[ Kết thúc kiểm ]=="
#!/usr/bin/env bash
# scripts/verify_fixpack.sh  — V2
set -euo pipefail

RED='\033[0;31m'; YEL='\033[1;33m'; GRN='\033[0;32m'; NC='\033[0m'
fail(){ echo -e "${RED}FAIL${NC} - $*"; exit 1; }
warn(){ echo -e "${YEL}WARN${NC} - $*"; }
pass(){ echo -e "${GRN}PASS${NC} - $*"; }
info(){ echo "INFO - $*"; }

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
[ -n "$repo_root" ] || fail "Không phải thư mục git."
cd "$repo_root"

echo "==[ CrX PhaseB Verify Fixpack ]=="
echo "Repo : $repo_root"
git fetch -q origin
echo "HEAD : $(git rev-parse HEAD)"
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
  pass "Git sạch (HEAD == origin/main)."
else
  fail "HEAD != origin/main. Hãy pull/reset."
fi

# Công cụ
if command -v jq >/dev/null 2>&1; then
  pass "Đủ công cụ cơ bản (jq)."
else
  fail "Thiếu 'jq'. sudo apt install -y jq"
fi

# .env floors
ENV_FILE=".env"
get_env(){ grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d'=' -f2- || true; }
OPEN_FLOOR="$(get_env CRX_OPEN_CONF_FLOOR)"
CLOSE_FLOOR="$(get_env CRX_CLOSE_CONF_FLOOR)"
ALLOW_ADD="$(get_env CRX_ALLOW_ADD)"
FRESH_SEC="$(get_env CRX_DECISION_FRESH_SEC)"

[ -n "${OPEN_FLOOR:-}" ] && awk "BEGIN{exit !($OPEN_FLOOR>=0.65)}" \
  && pass "OPEN_FLOOR ($OPEN_FLOOR) ≥ 0.65" || warn "OPEN_FLOOR ($OPEN_FLOOR) < 0.65"
[ -n "${CLOSE_FLOOR:-}" ] && awk "BEGIN{exit !($CLOSE_FLOOR>=0.60)}" \
  && pass "CLOSE_FLOOR ($CLOSE_FLOOR) ≥ 0.60" || warn "CLOSE_FLOOR ($CLOSE_FLOOR) < 0.60"
[ "${ALLOW_ADD:-0}" = "0" ] && pass "CRX_ALLOW_ADD=0 (không cộng thêm vị thế)" || warn "CRX_ALLOW_ADD != 0"
[ -n "${FRESH_SEC:-}" ] && info "FRESH_SEC=$FRESH_SEC(s)" || info "FRESH_SEC=900(s) (mặc định)"

DEC="last_decision.json"
PREV="last_decision_preview.json"

# Nguồn quyết định hiện có?
if [ -f "$DEC" ]; then
  conf="$(jq -r '.confidence // empty' "$DEC")"
  sym="$(jq -r '.symbol // empty' "$DEC")"
  meta="$(jq -r '.meta_action // empty' "$DEC")"
  decs="$(jq -r '.decision // empty' "$DEC")"
  ts="$(jq -r '.timestamp // empty' "$DEC")"

  if [ -n "$sym" ]; then pass "symbol trong $DEC: $sym"; else fail "Thiếu 'symbol' trong $DEC"; fi
  typ="open"; floor="$OPEN_FLOOR"
  echo "$meta$decs" | grep -qiE '(^|[^A-Z])(close|flip)' && typ="close/flip" && floor="$CLOSE_FLOOR"

  if [ -n "$conf" ]; then
    awk -v c="$conf" -v f="$floor" 'BEGIN{exit !(c>=f)}' \
      && pass "confidence $conf đạt ngưỡng $typ ($floor)" \
      || warn "confidence $conf < ngưỡng $typ ($floor)"
  else
    warn "Thiếu confidence trong $DEC"
  fi

  if [ -n "$ts" ]; then
    # tính tuổi bản quyết định
    now=$(date -u +%s); tss=$(date -u -d "${ts/Z/+00:00}" +%s 2>/dev/null || echo 0)
    age=$((now - tss))
    info "$DEC age=${age}s"
  fi

elif [ -f "$PREV" ]; then
  pass "Đã gate: chỉ có $PREV (không xuất $DEC khi dưới ngưỡng)."
else
  warn "Không thấy $DEC và $PREV — có thể chưa có vòng quyết định."
fi

# Kiểm tra code export/guard
if grep -q "ensure_symbol" tools/append_latest_and_export.py 2>/dev/null; then
  pass "append_latest_and_export.py có ensure_symbol()"
else
  warn "Không thấy ensure_symbol() trong append_latest_and_export.py"
fi

if [ -x "scripts/executor_guard.sh" ]; then
  pass "Có scripts/executor_guard.sh (executable)."
else
  warn "Thiếu/chưa chmod +x scripts/executor_guard.sh"
fi

if [ -x "scripts/smoke_phaseB.sh" ]; then
  pass "Có scripts/smoke_phaseB.sh (executable)."
else
  warn "Thiếu/chưa chmod +x scripts/smoke_phaseB.sh"
fi

echo "==[ Kết thúc kiểm ]=="
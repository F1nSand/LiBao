#!/usr/bin/env bash
# M6-2 进化闭环·候选区 e2e 验证（需后端运行于 :8000，validate 跑真实 LLM）。
# 用法: bash scripts/verify_evolution.sh [base_url]
# 覆盖: 登录 → list seed 候选 → validate（真实 LLM）→ publish → rollback → tool 载体 40021 → 非法状态 40020。
set -euo pipefail

BASE="${1:-${BASE_URL:-http://localhost:8000/api/v1}}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS_N=0
FAIL_N=0
pass() { PASS_N=$((PASS_N + 1)); echo "  ✅ $1"; }
fail() { FAIL_N=$((FAIL_N + 1)); echo "  ❌ $1"; }

jget() { uv run --quiet python -c 'import sys,json;d=json.load(sys.stdin);[d:=d[k] for k in sys.argv[1].split(".")];print(d)' "$1"; }

echo "== M6-2 候选区 e2e 验证 (base=$BASE) =="

echo "[1] 后端健康"
curl -fsS "$BASE/system/health" >/dev/null || { echo "后端不可达: $BASE"; exit 1; }
pass "health"

echo "[2] 登录"
LOGIN="$(curl -fsS -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}")"
TOKEN="$(printf '%s' "$LOGIN" | jget data.token)"
[ -n "$TOKEN" ] || { fail "登录失败"; exit 1; }
AUTH=(-H "Authorization: Bearer $TOKEN")
pass "token 获取"

echo "[3] seed 候选在列"
curl -fsS "$BASE/evolution/candidates" "${AUTH[@]}" > "$TMP/list.json"
CNT="$(uv run --quiet python -c 'import sys,json;print(len(json.load(open(sys.argv[1],encoding="utf-8"))["data"]["items"]))' "$TMP/list.json")"
[ "$CNT" -ge 3 ] && pass "候选 $CNT 条（≥3 seed）" || { fail "候选不足 $CNT 条（先跑 seed）"; exit 1; }

# 取一条 candidate 状态的候选
CID="$(uv run --quiet python -c '
import sys, json
for c in json.load(open(sys.argv[1],encoding="utf-8"))["data"]["items"]:
    if c["status"] == "candidate":
        print(c["id"]); break
' "$TMP/list.json")"
[ -n "$CID" ] && pass "取 candidate 候选 $CID" || { fail "无 candidate 状态候选"; exit 1; }

echo "[4] validate（真实 LLM，同步，可能 10-30s）"
curl -fsS -X POST "$BASE/evolution/candidates/$CID/validate" "${AUTH[@]}" > "$TMP/validated.json"
VSTATUS="$(uv run --quiet python -c 'import sys,json;print(json.load(open(sys.argv[1],encoding="utf-8"))["data"]["status"])' "$TMP/validated.json")"
VRATE="$(uv run --quiet python -c 'import sys,json;print(json.load(open(sys.argv[1],encoding="utf-8"))["data"]["pass_rate"])' "$TMP/validated.json")"
{ [ "$VSTATUS" = "approved" ] || [ "$VSTATUS" = "rejected" ]; } \
  && pass "validate → $VSTATUS (pass_rate=$VRATE)" || { fail "validate 异常 status=$VSTATUS"; exit 1; }

if [ "$VSTATUS" = "approved" ]; then
  echo "[5] publish（approved → published）"
  curl -fsS -X POST "$BASE/evolution/candidates/$CID/publish" "${AUTH[@]}" > "$TMP/pub.json"
  PSTATUS="$(uv run --quiet python -c 'import sys,json;print(json.load(open(sys.argv[1],encoding="utf-8"))["data"]["status"])' "$TMP/pub.json")"
  [ "$PSTATUS" = "published" ] && pass "publish → published" || { fail "publish → $PSTATUS"; exit 1; }

  echo "[6] rollback（published → rolled_back）"
  curl -fsS -X POST "$BASE/evolution/candidates/$CID/rollback" "${AUTH[@]}" > "$TMP/rb.json"
  RSTATUS="$(uv run --quiet python -c 'import sys,json;print(json.load(open(sys.argv[1],encoding="utf-8"))["data"]["status"])' "$TMP/rb.json")"
  [ "$RSTATUS" = "rolled_back" ] && pass "rollback → rolled_back" || { fail "rollback → $RSTATUS"; exit 1; }
else
  echo "[5/6] validate 已 rejected（跳过 publish/rollback）"
fi

echo "[7] 手动建 tool 候选 → publish 应 40021"
cat > "$TMP/tool.json" <<'JSON'
{"title":"tool 载体候选","change_type":"tool"}
JSON
curl -fsS -X POST "$BASE/evolution/candidates" "${AUTH[@]}" -H 'Content-Type: application/json' \
  --data-binary @"$TMP/tool.json" > "$TMP/tool_created.json"
TCID="$(uv run --quiet python -c 'import sys,json;print(json.load(open(sys.argv[1],encoding="utf-8"))["data"]["id"])' "$TMP/tool_created.json")"
# 直接 publish（status=candidate 会先撞 40020；改为验证非法状态也符合预期）
CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/evolution/candidates/$TCID/publish" "${AUTH[@]}")"
BODY="$(curl -s -X POST "$BASE/evolution/candidates/$TCID/publish" "${AUTH[@]}")"
ECODE="$(printf '%s' "$BODY" | jget code)"
[ "$ECODE" = "40020" ] || [ "$ECODE" = "40021" ] \
  && pass "tool 候选 publish 拒绝（code=$ECODE）" || { fail "期望 40020/40021 实得 $ECODE"; exit 1; }

echo
echo "== 结果: $PASS_N 通过 / $FAIL_N 失败 =="
[ "$FAIL_N" -eq 0 ]

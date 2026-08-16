#!/usr/bin/env bash
# M5 评估回归 e2e 验证（需后端运行于 :8000，且 LLM_API_KEY 可用——评估跑真实 LLM）。
# 用法: bash scripts/verify_eval.sh [base_url]
# 覆盖: 登录 → seed 冒烟评估集存在 → 跑 run（8 条）→ 轮询 done → 断言 pass_rate ≥ 0.2（宽松阈值）。
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

echo "== M5 评估回归 e2e 验证 (base=$BASE) =="

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

echo "[3] seed 冒烟评估集存在"
SETS="$(curl -fsS "$BASE/system/evals/sets" "${AUTH[@]}")"
SET_ID="$(printf '%s' "$SETS" | uv run --quiet python -c '
import sys, json
for s in json.load(sys.stdin)["data"]:
    if s.get("name") == "smoke_eval":
        print(s["id"]); break
')"
[ -n "$SET_ID" ] && pass "smoke_eval 存在（$SET_ID）" || { fail "smoke_eval 缺失（先跑 seed）"; exit 1; }

echo "[4] 跑评估 run（smoke_eval，8 条，真实 LLM）"
cat > "$TMP/run.json" <<JSON
{"eval_set_id":"$SET_ID"}
JSON
RUN="$(curl -fsS -X POST "$BASE/system/evals/run" "${AUTH[@]}" -H 'Content-Type: application/json' \
  --data-binary @"$TMP/run.json")"
RUN_ID="$(printf '%s' "$RUN" | jget data.id)"
pass "run 发起 $RUN_ID"

STATUS="pending"
for _ in $(seq 1 120); do
  sleep 2
  # 中文响应经 Git Bash 管道会 GBK 转码损坏 JSON → 写文件 + python 直接读文件（绕过控制台编码）
  curl -fsS "$BASE/system/evals/runs/$RUN_ID" "${AUTH[@]}" > "$TMP/detail.json"
  STATUS="$(uv run --quiet python -c 'import sys,json;d=json.load(open(sys.argv[1],encoding="utf-8"));print(d["data"]["run"]["status"])' "$TMP/detail.json")"
  [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ] && break
done
[ "$STATUS" = "done" ] && pass "run 完成（status=done）" || { fail "run $STATUS"; exit 1; }

PASS_RATE="$(uv run --quiet python -c 'import sys,json;print(json.load(open(sys.argv[1],encoding="utf-8"))["data"]["run"]["pass_rate"])' "$TMP/detail.json")"
if uv run --quiet python -c "import sys; sys.exit(0 if float('$PASS_RATE') >= 0.2 else 1)"; then
  pass "pass_rate=$PASS_RATE（≥0.2 宽松阈值）"
else
  fail "pass_rate=$PASS_RATE 低于 0.2"
fi

echo
echo "== 结果: $PASS_N 通过 / $FAIL_N 失败 =="
[ "$FAIL_N" -eq 0 ]

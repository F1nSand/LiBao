#!/usr/bin/env bash
# M4.5 派发链路 e2e 验证（需后端运行于 :8000，且 LLM_API_KEY 可用——派发依赖真实 LLM）。
# 用法: bash scripts/verify_subagent.sh [base_url]
# 覆盖: 登录 → 无 agent_id 建会话(落通用助手) → 流式派发 subagent(SSE 断言 2 条 agent_switch + done) → 清理。
set -euo pipefail

BASE="${1:-${BASE_URL:-http://localhost:8000/api/v1}}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123}"
TAG="$(date +%s)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS_N=0
FAIL_N=0
pass() { PASS_N=$((PASS_N + 1)); echo "  ✅ $1"; }
fail() { FAIL_N=$((FAIL_N + 1)); echo "  ❌ $1"; }

# 信封 JSON 字段提取: echo "$json" | jget data.token
jget() { uv run --quiet python -c 'import sys,json;d=json.load(sys.stdin);[d:=d[k] for k in sys.argv[1].split(".")];print(d)' "$1"; }
# 字符串计数: echo "$text" | jcount "agent_switch"
jcount() { uv run --quiet python -c 'import sys;print(sys.stdin.read().count(sys.argv[1]))' "$1"; }

echo "== Subagent 派发 e2e 验证 (base=$BASE, tag=$TAG) =="

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

# 含中文的 JSON body 必须写文件再 --data-binary @file（Git Bash→curl.exe 按 GBK 转码，直传中文会被拒 400）。

echo "[3] 无 agent_id 建会话（单通用 Agent）"
cat > "$TMP/conv.json" <<JSON
{"title":"verify_subagent_$TAG"}
JSON
CONV="$(curl -fsS -X POST "$BASE/conversations" "${AUTH[@]}" -H 'Content-Type: application/json' \
  --data-binary @"$TMP/conv.json")"
CONV_ID="$(printf '%s' "$CONV" | jget data.id)"
AGENT_ID="$(printf '%s' "$CONV" | jget data.agent_id)"
[ -n "$CONV_ID" ] && [ -n "$AGENT_ID" ] && pass "建会话 $CONV_ID（agent_id=$AGENT_ID 已落）" \
  || { fail "建会话/agent_id 缺失"; exit 1; }

echo "[4] 流式派发 subagent（SSE 断言 2 条 agent_switch + done）"
cat > "$TMP/chat.json" <<JSON
{"conversation_id":"$CONV_ID","message":{"content":"请务必先调用 dispatch_subagent 工具派发 code_review subagent 审查这段 Python 代码：def add(a, b): return a + b。不要直接回答，派发后报告审查结论。"},"stream":true}
JSON
# 显式捕获 curl 退出码（set -e 下命令替换失败会静默终止，改为 fail+exit 明确报错）
if ! curl -sN -X POST "$BASE/chat/stream" "${AUTH[@]}" -H 'Content-Type: application/json' \
  --data-binary @"$TMP/chat.json" --max-time 180 > "$TMP/sse.txt"; then
  fail "流式请求失败（curl 非零，可能 LLM 超时/派发未触发）"; exit 1
fi

# 按事件 type 精确计数（agent_switch 帧 = event: 头 + data: JSON 各出现一次，避免重复计）
SWITCH_N="$(jcount '"type": "agent_switch"' < "$TMP/sse.txt")"
[ "$SWITCH_N" -ge 2 ] && pass "agent_switch 出现 ${SWITCH_N} 条（≥2：进入+离开）" || fail "agent_switch 仅 $SWITCH_N 条"
( grep -q '"from_agent": "通用助手"' "$TMP/sse.txt" ) && pass "进入方向 通用助手→subagent" || fail "缺进入方向 agent_switch"
( grep -q '"to_agent": "通用助手"' "$TMP/sse.txt" ) && pass "离开方向 subagent→通用助手" || fail "缺离开方向 agent_switch"
( grep -q '"type": "done"' "$TMP/sse.txt" ) && pass "done 出现" || fail "缺 done"

echo "[5] 清理"
curl -fsS -X DELETE "$BASE/conversations/$CONV_ID" "${AUTH[@]}" >/dev/null && pass "清理会话" || fail "清理会话"

echo
echo "== 结果: $PASS_N 通过 / $FAIL_N 失败 =="
[ "$FAIL_N" -eq 0 ]

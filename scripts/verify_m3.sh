#!/usr/bin/env bash
# M3 记忆/知识库/附件核心闭环 e2e 验证（需后端运行于 :8000）。
# 用法: bash scripts/verify_m3.sh [base_url]
# 覆盖: 登录 → KB 全链(建集合/传文档/轮询索引/混合检索) → 记忆卡 CRUD → 附件(上传/分析/二进制回读) → 清理。
# 不含 /memory/maintenance（会整理用户全部真实卡片，留手动验证）。
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

echo "== M3 e2e 验证 (base=$BASE, tag=$TAG) =="

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

# 含中文的 JSON body 必须写文件再 --data-binary @file:
# Git Bash → curl.exe 跨进程按 Windows codepage(GBK)转码,直传中文 argv 会被后端拒 400。

echo "[3] KB 全链"
cat > "$TMP/coll.json" <<JSON
{"name":"verify_$TAG","description":"e2e 验证集合"}
JSON
COLL="$(curl -fsS -X POST "$BASE/kb/collections" "${AUTH[@]}" -H 'Content-Type: application/json' \
  --data-binary @"$TMP/coll.json")"
COLL_ID="$(printf '%s' "$COLL" | jget data.id)"
pass "建集合 $COLL_ID"

cat > "$TMP/doc.txt" <<TXT
Agent 框架支持记忆、知识库检索与附件分析三大能力,本段为验证脚本写入的测试内容。
TXT
DOC="$(curl -fsS -X POST "$BASE/kb/collections/$COLL_ID/documents" "${AUTH[@]}" -F "file=@$TMP/doc.txt")"
DOC_ID="$(printf '%s' "$DOC" | jget data.id)"
pass "上传文档 $DOC_ID"

STATUS="uploaded"
for _ in $(seq 1 30); do
  sleep 1
  STATUS="$(curl -fsS "$BASE/kb/documents/$DOC_ID/status" "${AUTH[@]}" | jget data.status)"
  if [ "$STATUS" = "indexed" ] || [ "$STATUS" = "failed" ]; then break; fi
done
[ "$STATUS" = "indexed" ] && pass "索引完成" || fail "索引 $STATUS"

cat > "$TMP/search.json" <<JSON
{"query":"知识库检索","collection_ids":["$COLL_ID"],"top_k":5}
JSON
SEARCH="$(curl -fsS -X POST "$BASE/kb/search" "${AUTH[@]}" -H 'Content-Type: application/json' \
  --data-binary @"$TMP/search.json")"
# 数组计数不经过 jget(jget 对复合结构输出 Python repr 单引号,json.load 会失败)
HITS="$(printf '%s' "$SEARCH" | uv run --quiet python -c 'import sys,json;print(len(json.load(sys.stdin)["data"]))')"
[ "${HITS:-0}" -gt 0 ] && pass "混合检索命中 ${HITS} 条" || fail "检索无命中"

echo "[4] 记忆卡"
cat > "$TMP/card.json" <<JSON
{"card_type":"note","title":"verify 测试卡","body":{"text":"e2e 验证记忆"},"tags":["verify"]}
JSON
CARD="$(curl -fsS -X POST "$BASE/memory/longterm" "${AUTH[@]}" -H 'Content-Type: application/json' \
  --data-binary @"$TMP/card.json")"
CARD_ID="$(printf '%s' "$CARD" | jget data.id)"
pass "创建记忆卡 $CARD_ID"
curl -fsS "$BASE/memory/longterm/$CARD_ID/versions" "${AUTH[@]}" >/dev/null
pass "版本列表"

echo "[5] 附件链"
printf '%s' "attachment verify payload" > "$TMP/att.txt"
ATT="$(curl -fsS -X POST "$BASE/uploads" "${AUTH[@]}" -F "file=@$TMP/att.txt")"
ATT_ID="$(printf '%s' "$ATT" | jget data.id)"
pass "上传附件 $ATT_ID"

ASTAT="uploaded"
for _ in $(seq 1 15); do
  sleep 1
  ASTAT="$(curl -fsS "$BASE/attachments/$ATT_ID/analysis" "${AUTH[@]}" | jget data.status)"
  if [ "$ASTAT" = "ready" ] || [ "$ASTAT" = "failed" ]; then break; fi
done
[ "$ASTAT" = "ready" ] && pass "附件分析 ready" || fail "附件分析 $ASTAT"

curl -fsS "$BASE/attachments/$ATT_ID" "${AUTH[@]}" -o "$TMP/down.txt"
cmp -s "$TMP/att.txt" "$TMP/down.txt" && pass "二进制回读一致" || fail "二进制回读不一致"

echo "[6] 清理"
curl -fsS -X DELETE "$BASE/kb/collections/$COLL_ID" "${AUTH[@]}" >/dev/null && pass "清理集合" || fail "清理集合"
curl -fsS -X DELETE "$BASE/memory/longterm/$CARD_ID" "${AUTH[@]}" >/dev/null && pass "清理记忆卡" || fail "清理记忆卡"
curl -fsS -X DELETE "$BASE/attachments/$ATT_ID" "${AUTH[@]}" >/dev/null && pass "清理附件" || fail "清理附件"

echo
echo "== 结果: $PASS_N 通过 / $FAIL_N 失败 =="
[ "$FAIL_N" -eq 0 ]

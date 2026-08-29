<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Message, ToolCallRecord } from '@/types'
import type { StreamState, ToolCallCardState } from '@/composables/useChatStream'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import ToolCallCard from './ToolCallCard.vue'
import AttachmentBubble from './AttachmentBubble.vue'
import { formatCost, formatTokens, thinkPreview, toolCallSummary } from '@/utils/format'

/**
 * 消息气泡（docs/02 §5.3/§5.4.3）：
 * 助手消息 = 「活动区 + 回复气泡」双区——工具调用 / agent 切换 / 思考以紧凑行出现在
 * 回复气泡上方（多工具/思考往下递进，非气泡）；文本为气泡正文。
 * - message：持久化消息（content → 气泡；tool_calls[] 按 position → 活动区）
 * - stream：流式实时段（按事件序拆分到两区）
 */
const props = defineProps<{
  message?: Message
  stream?: StreamState | null
}>()

type ActivityItem =
  | { kind: 'tool'; card: ToolCallCardState }
  | { kind: 'agent'; from: string; to: string; reason?: string }
  | { kind: 'thinking'; text: string }

type TextSeg = { kind: 'text'; content: string; streaming: boolean }

interface RenderParts {
  activity: ActivityItem[]
  text: TextSeg | null
}

function fromRecord(c: ToolCallRecord): ToolCallCardState {
  return {
    tool_call_id: c.tool_call_id,
    tool_name: c.tool_name,
    input: c.input,
    structured: c.output,
    status: (c.status as ToolCallCardState['status']) ?? 'done',
    durationMs: c.duration_ms,
    startedAt: Date.now(),
  }
}

function toolPlaceholder(calls: Array<{ tool_name: string; input: unknown }>): string {
  const first = toolCallSummary(calls[0].tool_name, calls[0].input)
  return calls.length > 1 ? `${first} 等 ${calls.length} 个工具` : first
}

function partsFromStream(s: StreamState): RenderParts {
  const activity: ActivityItem[] = []
  let text: TextSeg | null = null
  const toolCalls: Array<{ tool_name: string; input: unknown }> = []
  for (const seg of s.segments) {
    if (seg.kind === 'text') {
      // 文本：唯一文本段 → 回复气泡（活动区下方）；done 后无持久化场景切 markdown 渲染
      text = { kind: 'text', content: seg.text, streaming: s.streaming }
    } else if (seg.kind === 'tool') {
      const card = s.toolCalls[seg.cardId]
      if (card) {
        activity.push({ kind: 'tool', card })
        toolCalls.push({ tool_name: card.tool_name, input: card.input })
      }
    } else if (seg.kind === 'agent') {
      activity.push({ kind: 'agent', from: seg.from, to: seg.to, reason: seg.reason })
    } else {
      activity.push({ kind: 'thinking', text: seg.text })
    }
  }
  // 工具轮无文本 → 占位消息「调用 [工具]：入参」（流式中即时显示）
  if (!text && toolCalls.length) text = { kind: 'text', content: toolPlaceholder(toolCalls), streaming: s.streaming }
  return { activity, text }
}

function partsFromMessage(m: Message): RenderParts {
  const activity: ActivityItem[] = []
  // 推理链在工具/文本之上（模型先思考再行动）
  if (m.thinking?.trim()) activity.push({ kind: 'thinking', text: m.thinking })
  const calls = [...(m.tool_calls ?? [])].sort((a, b) => a.position - b.position)
  for (const c of calls) activity.push({ kind: 'tool', card: fromRecord(c) })
  const hasContent = !!(m.content ?? '').trim()
  let text: TextSeg | null = null
  if (hasContent) text = { kind: 'text', content: m.content, streaming: false }
  else if (calls.length) text = { kind: 'text', content: toolPlaceholder(calls), streaming: false }
  return { activity, text }
}

const parts = computed<RenderParts>(() => {
  if (props.stream) return partsFromStream(props.stream)
  if (props.message) return partsFromMessage(props.message)
  return { activity: [], text: null }
})

/** thinking 折叠展开态（按活动项索引）：默认收起显示单行预览，整行点击展开全文 */
const expandedThinking = ref<Set<number>>(new Set())
function isThinkingExpanded(i: number): boolean {
  return expandedThinking.value.has(i)
}
function toggleThinking(i: number): void {
  const s = new Set(expandedThinking.value)
  if (s.has(i)) s.delete(i)
  else s.add(i)
  expandedThinking.value = s
}

/** thinking 行 hover 态（悬停时行左侧才出现三角） */
const thinkingHover = ref<Set<number>>(new Set())
function isThinkingHover(i: number): boolean {
  return thinkingHover.value.has(i)
}
function setThinkingHover(i: number, v: boolean): void {
  const s = new Set(thinkingHover.value)
  if (v) s.add(i)
  else s.delete(i)
  thinkingHover.value = s
}

const role = computed(() => (props.stream ? 'assistant' : props.message?.role ?? 'user'))
const hasUserText = computed(() => !!props.message?.content?.trim())

/** 逐轮 token_usage/cost footer（docs/03 §3 多消息扩展）：仅持久化消息路径，防御式（无数据即空） */
const usageText = computed(() => {
  if (props.stream) return ''
  const tok = formatTokens(props.message?.token_usage)
  const cost = formatCost(props.message?.cost)
  return [tok, cost].filter(Boolean).join(' · ')
})
</script>

<template>
  <div class="msg" :class="role">
    <div class="msg-avatar">
      <el-avatar :size="28" :class="`avatar-${role}`">
        {{ role === 'user' ? '我' : 'AI' }}
      </el-avatar>
    </div>

    <div class="msg-content">
      <!-- 用户消息：纯文本 + 附件 + 工作区文件引用（独立气泡，不套 .msg-text 助手框） -->
      <template v-if="role === 'user' && message">
        <AttachmentBubble v-if="message.attachments?.length" :refs="message.attachments" />
        <div v-if="message.file_refs?.length" class="file-refs">
          <span v-for="fr in message.file_refs" :key="fr.path" class="file-ref-chip" :title="fr.path">
            <el-icon :size="12"><Document /></el-icon>
            <span class="mono">{{ fr.path }}</span>
          </span>
        </div>
        <div v-if="hasUserText" class="user-text">{{ message.content }}</div>
      </template>

      <!-- 助手消息：活动区（工具/切换/思考）在回复气泡上方，往下递进 -->
      <template v-else>
        <div v-if="parts.activity.length" class="msg-activity">
          <template v-for="(item, i) in parts.activity" :key="i">
            <ToolCallCard
              v-if="item.kind === 'tool'"
              :tool-name="item.card.tool_name"
              :status="item.card.status"
              :error="item.card.error"
              :input="item.card.input"
              :output="item.card.structured"
              :duration-ms="item.card.durationMs"
            />
            <div v-else-if="item.kind === 'agent'" class="agent-switch">
              <el-icon :size="13"><Switch /></el-icon>
              <span class="agent-switch-label"><b>{{ item.from }}</b> → <b>{{ item.to }}</b></span>
              <span v-if="item.reason" class="agent-switch-reason">{{ item.reason }}</span>
            </div>
            <button
              v-else
              type="button"
              class="thinking-row"
              :aria-expanded="isThinkingExpanded(i)"
              @click="toggleThinking(i)"
              @mouseenter="setThinkingHover(i, true)"
              @mouseleave="setThinkingHover(i, false)"
            >
              <!-- 左侧：平时思考图标，hover 变展开三角（展开时保持三角） -->
              <span class="thinking-arrow">
                <el-icon :size="12"><component :is="isThinkingExpanded(i) ? 'ArrowDown' : (isThinkingHover(i) ? 'ArrowRight' : 'Aim')" /></el-icon>
              </span>
              <span v-if="isThinkingExpanded(i)" class="thinking-text">{{ item.text }}</span>
              <span v-else class="thinking-preview">{{ thinkPreview(item.text) }}</span>
            </button>
          </template>
        </div>

        <div v-if="parts.text" class="msg-text">
          <MarkdownRenderer :raw="parts.text.content" :streaming="parts.text.streaming" />
        </div>
        <div v-if="usageText" class="msg-usage">{{ usageText }}</div>
        <div v-if="!parts.activity.length && !parts.text && !stream" class="msg-empty">…</div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  gap: 10px;
  padding: 10px 16px;
}
.msg-avatar {
  flex-shrink: 0;
}
.avatar-user {
  background: var(--app-primary-fill);
  color: var(--app-on-primary);
}
.avatar-assistant {
  background: #eef0f5;
  color: var(--app-text-secondary);
}
.msg-content {
  flex: 1;
  min-width: 0;
  max-width: 80%;
}
.msg.user {
  flex-direction: row-reverse;
}
.msg.user .msg-content {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.file-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 4px;
  justify-content: flex-end;
}
.file-ref-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  background: color-mix(in srgb, var(--app-primary) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--app-primary) 30%, transparent);
  border-radius: var(--app-radius-lg);
  font-size: 12px;
  color: var(--app-link);
  max-width: 260px;
}
.file-ref-chip .mono {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mono {
  font-family: var(--app-font-mono);
}
.user-text {
  background: var(--app-primary-fill);
  color: var(--app-on-primary);
  padding: 8px 16px;
  border-radius: var(--app-radius-lg);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  max-width: 100%;
}
.msg-text {
  background: var(--app-content-bg);
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius-lg);
  padding: 8px 16px;
  line-height: 1.7;
  box-shadow: var(--app-shadow-card);
}

/* 活动区：紧凑行（工具/agent切换/思考），非气泡，往下递进 */
.msg-activity {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 2px 2px 6px;
}
.agent-switch,
.thinking-row {
  display: inline-flex;
  gap: 6px;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-xs);
  line-height: 20px;
}
.agent-switch {
  align-items: center;
}
.agent-switch-label b {
  font-weight: 600;
  color: var(--app-link);
}
.agent-switch-reason {
  color: var(--app-text-tertiary);
}
/* thinking：无外框平铺行（非气泡），默认收起单行预览，整行点击展开 */
.thinking-row {
  width: 100%;
  align-items: flex-start;
  padding: 0;
  border: none;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.thinking-arrow {
  color: var(--app-text-muted);
  display: flex;
  flex-shrink: 0;
  transition: color 0.15s;
}
.thinking-row:hover .thinking-arrow {
  color: var(--app-link);
}
.thinking-preview {
  flex: 1;
  min-width: 0;
  font-size: var(--app-font-size-xs);
  color: var(--app-text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thinking-text {
  flex: 1;
  min-width: 0;
  font-size: var(--app-font-size-xs);
  color: var(--app-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}
.msg-empty {
  color: var(--app-text-muted);
}
.msg-usage {
  font-size: var(--app-font-size-xs);
  color: var(--app-text-tertiary);
  margin-top: 8px;
  padding-left: 2px;
}
</style>

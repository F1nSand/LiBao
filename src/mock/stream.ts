import type { ChatRequest, Message, SseEnvelope, SseEventType, ToolCallRecord } from '@/types'
import { delay, randHex, uid } from './util'
import { DEFAULT_AGENT_ID, messages } from './db'

export interface SseScriptItem {
  type: SseEventType
  payload: unknown
  delayMs: number
}

/** 中断确认上下文：chat/stream 触发 interrupt 时记录，resume 时恢复同一工具卡 */
export interface ConfirmCtx {
  taskId: string
  toolCallId: string
  jobRef: string
  conversationId: string
  expression: string
  content: string
}

const confirmCtxMap = new Map<string, ConfirmCtx>()

export function getConfirmCtx(taskId: string): ConfirmCtx | undefined {
  return confirmCtxMap.get(taskId)
}

export function setConfirmCtx(ctx: ConfirmCtx): void {
  confirmCtxMap.set(ctx.taskId, ctx)
}

function tok(text: string, ms = 160): SseScriptItem {
  return { type: 'token', payload: { text }, delayMs: delay(ms) }
}

function doneEvent(message: Message, tokenUsage?: Record<string, unknown>): SseScriptItem {
  // 落库：刷新页面/重进会话时从 GET /conversations/{id}/messages 拉取能保留（前端不再 done 后 refresh，改为流式内容补齐 append）
  if (!messages[message.conversation_id]) messages[message.conversation_id] = []
  messages[message.conversation_id].push(message)
  return {
    type: 'done',
    payload: {
      message_id: message.id,
      token_usage: tokenUsage ?? { prompt_tokens: 48, completion_tokens: 36, total_tokens: 84 },
      cost: 0.0012,
      message,
    },
    delayMs: delay(120),
  }
}

/** 简单四则运算（demo 用） */
function calcExpression(expr: string): number {
  const m = expr.match(/(-?\d+(?:\.\d+)?)\s*[*x×]\s*(-?\d+(?:\.\d+)?)/)
  if (m) return Math.round(parseFloat(m[1]) * parseFloat(m[2]) * 100) / 100
  const a = expr.match(/(-?\d+(?:\.\d+)?)\s*[+/]\s*(-?\d+(?:\.\d+)?)/)
  if (a) {
    const lhs = parseFloat(a[1])
    const rhs = parseFloat(a[2])
    return Math.round((lhs + rhs) * 100) / 100
  }
  return 42
}

/**
 * chat/stream 主脚本：
 * - 危险操作 / 计算类 → calculator（require_confirm）→ interrupt 后关流，等 resume
 * - 其余 → web_search 异步占位 → 回填快路径
 */
export function buildChatScript(req: ChatRequest): SseScriptItem[] {
  const content = req.message?.content ?? ''
  const conversationId = req.conversation_id ?? uid('c')
  const taskId = uid('task')
  const messageId = uid('msg')

  const base: SseScriptItem[] = [
    {
      // 单通用 Agent：message_start 仍发 agent_id（契约字段），值为默认通用 Agent
      type: 'message_start',
      payload: { message_id: messageId, agent_id: DEFAULT_AGENT_ID, conversation_id: conversationId, task_id: taskId },
      delayMs: delay(80),
    },
  ]

  const isDanger = /危险操作|danger|delete|删除/.test(content)
  const isCalc = /\d/.test(content) && /计算|[*x×+/-]/.test(content)

  if (isDanger || isCalc) {
    const toolCallId = uid('tc')
    const jobRef = uid('job')
    setConfirmCtx({ taskId, toolCallId, jobRef, conversationId, expression: content, content })
    return [
      ...base,
      tok(isDanger ? '检测到需要人工确认的操作，正在请求工具…\n' : '我来计算一下，先调用计算器。\n'),
      {
        type: 'tool_call',
        payload: { tool_call_id: toolCallId, tool_name: 'calculator', input: { expression: content }, require_confirm: true },
        delayMs: delay(200),
      },
      {
        type: 'interrupt',
        payload: {
          node_id: 'node_tool',
          payload: { tool_name: 'calculator', expression: content, reason: isDanger ? '危险操作需确认' : '工具调用需确认' },
          confirm_required: true,
          task_id: taskId,
        },
        delayMs: delay(180),
      },
    ]
  }

  // 默认：web_search 占位 → 回填
  const toolCallId = uid('tc')
  const jobRef = uid('job')
  const summaryLines = [
    `## 关于「${content}」的检索结果\n`,
    '1. **摘要一**：与该主题相关的简要说明与要点。',
    '2. **摘要二**：补充背景与相关链接。',
    '3. **摘要三**：进一步阅读建议。\n',
  ]
  const fullText = `正在检索「${content}」…\n\n${summaryLines.join('\n')}`
  return [
    ...base,
    tok('正在检索相关信息…\n'),
    {
      type: 'tool_call',
      payload: { tool_call_id: toolCallId, tool_name: 'web_search', input: { query: content, limit: 5 }, require_confirm: false },
      delayMs: delay(200),
    },
    {
      type: 'tool_result',
      payload: { tool_call_id: toolCallId, tool_name: 'web_search', ok: true, summary: '处理中…', placeholder: true, job_ref: jobRef },
      delayMs: delay(120),
    },
    {
      type: 'agent_switch',
      payload: { from_agent: '通用助手', to_agent: 'research', reason: '检索结果需复核' },
      delayMs: delay(100),
    },
    tok('检索完成，整理结果中…\n'),
    {
      type: 'tool_result',
      payload: {
        tool_call_id: toolCallId,
        tool_name: 'web_search',
        ok: true,
        summary: `找到 3 条相关结果`,
        structured: { hits: summaryLines.length },
        placeholder: false,
        job_ref: jobRef,
        duration_ms: 812,
      },
      delayMs: delay(200),
    },
    tok(fullText),
    doneEvent(
      {
        id: messageId,
        conversation_id: conversationId,
        role: 'assistant',
        content: fullText,
        attachments: [],
        tool_calls: [
          { tool_call_id: toolCallId, tool_name: 'web_search', input: { query: content }, output: { hits: summaryLines.length }, status: 'done', position: 0, duration_ms: 812 },
        ] satisfies ToolCallRecord[],
        trace_id: `tr_${randHex(12)}`,
        created_at: new Date().toISOString(),
      },
    ),
  ]
}

/** resume 脚本：approved=true 占位→回填→done；false 取消→done */
export function buildResumeScript(taskId: string, approved: boolean): SseScriptItem[] {
  const ctx = getConfirmCtx(taskId)
  const conversationId = ctx?.conversationId ?? uid('c')
  const messageId = uid('msg')
  const toolCallId = ctx?.toolCallId ?? uid('tc')
  const jobRef = ctx?.jobRef ?? uid('job')
  const result = ctx ? calcExpression(ctx.expression) : 42
  const content = ctx?.content ?? ''

  if (!approved) {
    const cancelledText = `已取消该操作（${content || '计算'}）。\n`
    return [
      tok('收到，已取消该操作。\n'),
      tok(cancelledText),
      doneEvent(
        {
          id: messageId,
          conversation_id: conversationId,
          role: 'assistant',
          content: cancelledText,
          attachments: [],
          tool_calls: [
            { tool_call_id: toolCallId, tool_name: 'calculator', input: { expression: content }, status: 'cancelled', position: 0 },
          ],
          created_at: new Date().toISOString(),
        },
      ),
    ]
  }

  const finalText = `计算结果：**${result}**\n`
  return [
    tok('已确认，正在执行工具…\n'),
    {
      type: 'tool_result',
      payload: { tool_call_id: toolCallId, tool_name: 'calculator', ok: true, summary: '处理中…', placeholder: true, job_ref: jobRef },
      delayMs: delay(120),
    },
    tok('工具执行中，请稍候…\n'),
    {
      type: 'tool_result',
      payload: {
        tool_call_id: toolCallId,
        tool_name: 'calculator',
        ok: true,
        summary: `计算结果：${result}`,
        structured: { result },
        placeholder: false,
        job_ref: jobRef,
        duration_ms: 320,
      },
      delayMs: delay(240),
    },
    tok(finalText),
    doneEvent(
      {
        id: messageId,
        conversation_id: conversationId,
        role: 'assistant',
        content: finalText,
        attachments: [],
        tool_calls: [
          { tool_call_id: toolCallId, tool_name: 'calculator', input: { expression: content }, output: { result }, status: 'done', position: 0, duration_ms: 320 },
        ] satisfies ToolCallRecord[],
        trace_id: `tr_${randHex(12)}`,
        created_at: new Date().toISOString(),
      },
    ),
  ]
}

/** 任务事件订阅回放：模拟 status → progress → done */
export function buildTaskEventsScript(taskId: string): SseScriptItem[] {
  return [
    { type: 'status', payload: { status: 'running' }, delayMs: delay(60) },
    { type: 'run_progress', payload: { stage: 'thinking', progress: 20 }, delayMs: delay(120) },
    {
      type: 'agent_switch',
      payload: { from_agent: '通用助手', to_agent: 'proposal_review', reason: '方案需评审' },
      delayMs: delay(140),
    },
    { type: 'status', payload: { status: 'running' }, delayMs: delay(160) },
    { type: 'run_progress', payload: { stage: 'executing', progress: 80 }, delayMs: delay(200) },
    {
      type: 'done',
      payload: { message_id: `msg_${taskId}`, token_usage: { total_tokens: 120 }, cost: 0.002 },
      delayMs: delay(180),
    },
  ]
}

/** 生成单个 SSE 信封（由 server 写流） */
export function toEnvelope(item: SseScriptItem, seq: number): SseEnvelope {
  return { id: `evt_${seq}`, seq, type: item.type, ts: Date.now(), payload: item.payload }
}


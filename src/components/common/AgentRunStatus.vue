<script setup lang="ts">
import { computed } from 'vue'
import type { AgentRunPhase } from '@/composables/useChatStream'

const props = defineProps<{
  phase: AgentRunPhase
  detail?: string | null
}>()

const LABELS: Record<AgentRunPhase, string> = {
  idle: '',
  starting: '正在启动',
  running: '处理中',
  thinking: '思考中',
  tool: '正在调用',
  delegating: '协同处理中',
  responding: '生成回复',
  finalizing: '整理回复',
  waiting_confirm: '等待确认',
  resuming: '已确认，正在继续',
  cancelling: '正在中断',
  cancelled: '已中断',
  done: '已完成',
  failed: '运行失败',
  reconnecting: '连接中断，正在重连',
  disconnected: '连接已断开',
  recoverable: '运行中断（可恢复）',
  background_running: '任务仍在后台执行',
  retrying: '模型连接中断，正在从最近断点重试',
}

const activePhases = new Set<AgentRunPhase>(['starting', 'running', 'thinking', 'tool', 'delegating', 'responding', 'finalizing', 'resuming', 'cancelling', 'reconnecting', 'retrying'])
const label = computed(() => {
  const base = LABELS[props.phase]
  if (!props.detail) return base
  if (props.phase === 'tool') return `正在执行 · ${props.detail}（正在调用）`
  if (props.phase === 'delegating') return `${props.detail} · ${base}`
  // retrying 的 detail = （attempt/max），拼成「…重试（1/1）」
  if (props.phase === 'retrying') return base + props.detail
  return base
})
const active = computed(() => activePhases.has(props.phase))
const title = computed(() => label.value.length > 24 ? label.value : undefined)
</script>

<template>
  <div
    v-if="label"
    class="run-status"
    :class="[`run-status-${phase}`, { active }]"
    role="status"
    aria-live="polite"
    :aria-busy="active"
    :title="title"
  >
    <span class="run-status-indicator" :class="{ active }" aria-hidden="true" />
    <Transition name="run-status-label">
      <span :key="label" class="run-status-label">{{ label }}</span>
    </Transition>
  </div>
</template>

<style scoped>
.run-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 28px;
  max-width: min(320px, 100%);
  padding: 4px 10px;
  border: 1px solid var(--app-border-light);
  border-radius: 999px;
  background: var(--app-content-bg);
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-xs);
  white-space: nowrap;
  box-shadow: var(--app-shadow-card);
  overflow: hidden;
}
.run-status-label {
  overflow: hidden;
  text-overflow: ellipsis;
}
.run-status-indicator {
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
  border: 2px solid currentColor;
  border-radius: 50%;
  color: var(--app-text-muted);
}
.run-status-indicator.active {
  color: var(--app-primary);
  border-top-color: transparent;
  animation: run-status-spin 0.9s linear infinite;
}
.run-status-tool,
.run-status-responding,
.run-status-thinking,
.run-status-delegating,
.run-status-finalizing,
.run-status-reconnecting,
.run-status-retrying,
.run-status-background_running {
  color: var(--app-primary-dark);
}
.run-status-waiting_confirm,
.run-status-recoverable {
  color: var(--app-warning);
}
.run-status-cancelled,
.run-status-disconnected {
  color: var(--app-text-secondary);
}
.run-status-done {
  color: var(--app-success);
}
.run-status-failed {
  color: var(--app-danger);
}
.run-status-label-enter-active,
.run-status-label-leave-active {
  transition: opacity 160ms var(--ease-out), transform 160ms var(--ease-out);
}
.run-status-label-enter-from,
.run-status-label-leave-to {
  opacity: 0;
  transform: translateY(2px);
}
@keyframes run-status-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .run-status-indicator.active { animation: none; }
  .run-status-label-enter-active,
  .run-status-label-leave-active { transition: opacity 100ms ease-out; }
  .run-status-label-enter-from,
  .run-status-label-leave-to { transform: none; }
}
</style>

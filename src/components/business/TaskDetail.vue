<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import { useSSE } from '@/composables/useSSE'
import { getToken } from '@/utils/token'
import type { AgentSwitchPayload, SseEnvelope, Task } from '@/types'
import StatusTag from '@/components/common/StatusTag.vue'
import JsonViewer from '@/components/common/JsonViewer.vue'

/** 任务详情（docs/02 §6.2 / docs/03 §5.3）：进度 + 事件 SSE 回放 + 取消/恢复 */
const props = defineProps<{ taskId: string | null }>()

const store = useTaskStore()
const task = ref<Task | null>(null)
const events = ref<SseEnvelope[]>([])

const sse = useSSE(
  () => (props.taskId ? `/api/v1/tasks/${props.taskId}/events` : ''),
  () => ({
    method: 'GET',
    headers: {
      Accept: 'text/event-stream',
      ...(getToken() ? { Authorization: `Bearer ${getToken()!}` } : {}),
    },
  }),
  {
    onEvent: (ev) => events.value.push(ev),
  },
)

/** agent_switch 事件的可读化（多 Agent 切换，docs/03 §3.3） */
function agentSwitchInfo(p: AgentSwitchPayload): { from?: string; to?: string; reason?: string } {
  return { from: p.from_agent, to: p.to_agent, reason: p.reason }
}

interface EventItem {
  id: string
  seq: number
  type: SseEnvelope['type']
  payload: unknown
  info?: { from?: string; to?: string; reason?: string }
}

/** 事件回放展示项：agent_switch 额外归一化出 info，其余原样 */
const eventItems = computed<EventItem[]>(() =>
  events.value.map((e) => ({
    id: e.id,
    seq: e.seq,
    type: e.type,
    payload: e.payload,
    info: e.type === 'agent_switch' ? agentSwitchInfo(e.payload as AgentSwitchPayload) : undefined,
  })),
)

async function load() {
  if (!props.taskId) return
  events.value = []
  try {
    task.value = await store.get(props.taskId)
  } catch {
    ElMessage.error('任务不存在或已删除')
  }
}

async function onCancel() {
  if (!task.value) return
  await store.cancel(task.value.id)
  await load()
}

async function onResume(approved: boolean) {
  if (!task.value) return
  await store.resume(task.value.id, { approved })
  await load()
}

watch(() => props.taskId, load, { immediate: true })
onMounted(() => sse.connect())
</script>

<template>
  <div v-if="task" class="task-detail">
    <div class="task-head">
      <span class="mono task-id">{{ task.id }}</span>
      <StatusTag :status="task.status" />
    </div>

    <el-progress :percentage="task.progress ?? 0" class="task-progress" />

    <div class="task-row"><span class="task-label">Agent</span><span>{{ task.agent_id }}</span></div>
    <div class="task-row"><span class="task-label">输入</span><JsonViewer :data="task.input" /></div>
    <div v-if="task.output !== undefined" class="task-row"><span class="task-label">输出</span><JsonViewer :data="task.output" /></div>

    <div v-if="task.status === 'waiting_confirm' && task.pending_confirm" class="task-confirm">
      <div class="task-label">等待确认</div>
      <JsonViewer :data="task.pending_confirm" />
      <div class="confirm-actions">
        <el-button size="small" @click="onResume(false)">拒绝</el-button>
        <el-button size="small" type="primary" @click="onResume(true)">确认</el-button>
      </div>
    </div>

    <div class="task-actions">
      <el-button
        v-if="task.status === 'pending' || task.status === 'running'"
        size="small"
        type="danger"
        @click="onCancel"
      >取消任务</el-button>
    </div>

    <div class="event-log">
      <div class="event-log-title">事件回放（SSE）</div>
      <div v-for="e in eventItems" :key="e.id" class="event-item">
        <template v-if="e.info">
          <span class="event-type mono">agent_switch</span>
          <span class="event-seq">seq={{ e.seq }}</span>
          <span class="agent-switch-chip">
            <b>{{ e.info.from }}</b> → <b>{{ e.info.to }}</b>
            <span v-if="e.info.reason" class="agent-switch-reason">{{ e.info.reason }}</span>
          </span>
        </template>
        <template v-else>
          <span class="event-type mono">{{ e.type }}</span>
          <span class="event-seq">seq={{ e.seq }}</span>
          <JsonViewer :data="e.payload" />
        </template>
      </div>
      <div v-if="events.length === 0" class="event-empty">等待事件…</div>
    </div>
  </div>
  <el-empty v-else description="请选择任务查看详情" />
</template>

<style scoped>
.task-detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 13px;
}
.task-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
.task-row {
  display: flex;
  gap: 8px;
}
.task-label {
  color: var(--app-text-muted);
  width: 44px;
  flex-shrink: 0;
}
.task-confirm {
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: var(--app-radius);
  padding: 8px;
  background: #fffbf0;
}
.confirm-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.event-log {
  border-top: 1px solid var(--app-border-light);
  padding-top: 8px;
  max-height: 320px;
  overflow-y: auto;
}
.event-log-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.event-item {
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  padding: 6px 8px;
  margin-bottom: 6px;
  background: var(--app-bg);
}
.event-type {
  color: var(--app-primary);
  font-weight: 600;
}
.agent-switch-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--app-text-muted);
}
.agent-switch-chip b {
  color: var(--app-primary);
}
.agent-switch-reason {
  color: var(--app-text-muted);
}
.event-seq {
  color: var(--app-text-muted);
  font-size: 11px;
  margin-left: 6px;
}
.event-empty {
  color: var(--app-text-muted);
  font-size: 12px;
  padding: 12px 0;
  text-align: center;
}
</style>

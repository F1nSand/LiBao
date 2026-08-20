<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useSystemStore } from '@/stores/system'
import { formatDate } from '@/utils/format'
import type { SystemLog } from '@/types'
import TraceTimeline from '@/components/business/TraceTimeline.vue'
import EmptyState from '@/components/common/EmptyState.vue'

/** 系统监控/运行日志（docs/02 §4 / docs/03 §5.8）：运行日志 + 点行看 trace 全链路 */
const store = useSystemStore()

const logsFilter = reactive({ trace_id: '', level: '' })
const traceDrawer = ref(false)
const activeTraceId = ref<string | null>(null)

onMounted(() => {
  void store.listLogs()
})

async function searchLogs() {
  await store.listLogs({
    trace_id: logsFilter.trace_id || undefined,
    level: logsFilter.level || undefined,
  })
}

function openTrace(traceId: string) {
  activeTraceId.value = traceId
  traceDrawer.value = true
}

function onRowClick(row: SystemLog) {
  openTrace(row.trace_id)
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">系统</h2>
        <p class="app-page-subtitle">运行日志（点行查看 trace 全链路）</p>
      </div>
    </div>

    <template v-if="!store.logsUnavailable">
      <div class="log-filter">
        <el-input v-model="logsFilter.trace_id" size="small" placeholder="按 trace_id 过滤" clearable style="width: 220px" @keyup.enter="searchLogs" />
        <el-select v-model="logsFilter.level" size="small" placeholder="级别" clearable style="width: 120px" @change="searchLogs">
          <el-option label="DEBUG" value="DEBUG" />
          <el-option label="INFO" value="INFO" />
          <el-option label="WARNING" value="WARNING" />
          <el-option label="ERROR" value="ERROR" />
        </el-select>
        <el-button size="small" type="primary" @click="searchLogs">查询</el-button>
      </div>
      <el-table :data="store.logs" size="small" class="log-table" @row-click="onRowClick">
        <el-table-column prop="trace_id" label="trace_id" width="130">
          <template #default="{ row }"><span class="mono">{{ row.trace_id }}</span></template>
        </el-table-column>
        <el-table-column prop="level" label="级别" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.level === 'ERROR' ? 'danger' : row.level === 'WARNING' ? 'warning' : 'info'">{{ row.level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="event" label="事件" width="150" />
        <el-table-column prop="message" label="消息" min-width="200" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </template>
    <EmptyState v-else text="后端暂未实现运行日志接口" />

    <el-drawer :model-value="traceDrawer" title="Trace 全链路" size="480px" @close="traceDrawer = false">
      <TraceTimeline :trace-id="activeTraceId" />
    </el-drawer>
  </div>
</template>

<style scoped>
.log-filter {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.log-table {
  cursor: pointer;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

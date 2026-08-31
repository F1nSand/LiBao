<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useSystemStore } from '@/stores/system'
import { formatDate } from '@/utils/format'
import type { SystemLog } from '@/types'
import TraceTimeline from '@/components/business/TraceTimeline.vue'
import AsyncState from '@/components/common/AsyncState.vue'
import PaginationPanel from '@/components/common/PaginationPanel.vue'

/** 系统监控/运行日志（《02》前端设计 §4 / 《02》接口契约 §5.8）：运行日志 + 点行看 trace 全链路 */
const store = useSystemStore()

const logsFilter = reactive({ trace_id: '', level: '' })
const traceDrawer = ref(false)
const activeTraceId = ref<string | null>(null)
const page = ref(1)
const pageSize = ref(20)

onMounted(() => {
  void store.listLogs()
})

async function searchLogs() {
  page.value = 1
  await store.listLogs({
    page: page.value,
    page_size: pageSize.value,
    trace_id: logsFilter.trace_id || undefined,
    level: logsFilter.level || undefined,
  })
}

async function onPage(nextPage: number, nextPageSize: number) {
  page.value = nextPage
  pageSize.value = nextPageSize
  await store.listLogs({
    page: page.value,
    page_size: pageSize.value,
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

    <div class="log-filter app-filter-bar">
        <el-input v-model="logsFilter.trace_id" size="small" placeholder="按 trace_id 过滤" clearable style="width: 220px" @keyup.enter="searchLogs" />
        <el-select v-model="logsFilter.level" size="small" placeholder="级别" clearable style="width: 120px" @change="searchLogs">
          <el-option label="DEBUG" value="DEBUG" />
          <el-option label="INFO" value="INFO" />
          <el-option label="WARNING" value="WARNING" />
          <el-option label="ERROR" value="ERROR" />
        </el-select>
        <el-button size="small" type="primary" @click="searchLogs">查询</el-button>
    </div>
    <AsyncState
        :status="store.logsUnavailable ? 'unavailable' : store.status"
        :error-message="store.errorMessage"
        empty-text="暂无运行日志"
        unavailable-text="后端暂未实现运行日志接口"
        @retry="store.retry"
      >
        <div class="app-table-wrap">
          <el-table :data="store.logs" size="small" class="log-table" @row-click="onRowClick">
        <el-table-column prop="trace_id" label="trace_id" width="130">
          <template #default="{ row }">
            <button type="button" class="trace-link mono" :aria-label="`查看 trace ${row.trace_id}`" @click.stop="openTrace(row.trace_id)">{{ row.trace_id }}</button>
          </template>
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
        </div>
        <PaginationPanel
          v-if="store.logTotal > pageSize"
          :total="store.logTotal"
          :page="page"
          :page_size="pageSize"
          :disabled="store.status === 'loading'"
          @change="onPage"
        />
    </AsyncState>

    <el-drawer :model-value="traceDrawer" title="Trace 全链路" size="480px" @close="traceDrawer = false">
      <TraceTimeline :trace-id="activeTraceId" />
    </el-drawer>
  </div>
</template>

<style scoped>
.log-filter {
  margin-bottom: 8px;
}
.log-table {
  min-width: 760px;
  cursor: pointer;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-card);
  overflow: hidden;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
.trace-link {
  padding: 2px 4px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-link);
  cursor: pointer;
}
.trace-link:hover {
  text-decoration: underline;
}
@media (max-width: 768px) {
  .log-filter > * {
    flex: 1 1 180px;
    min-width: 0;
  }
  .log-filter :deep(.el-input),
  .log-filter :deep(.el-select) {
    width: 100% !important;
  }
}
</style>

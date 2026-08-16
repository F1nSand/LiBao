<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useSystemStore } from '@/stores/system'
import { formatDate } from '@/utils/format'
import type { SystemLog } from '@/types'
import TraceTimeline from '@/components/business/TraceTimeline.vue'
import CostChart from '@/components/business/CostChart.vue'
import EvalManage from '@/components/system/EvalManage.vue'
import EmptyState from '@/components/common/EmptyState.vue'

/** 系统监控/日志（docs/02 §4 / docs/03 §5.8）：运行日志 + trace + 评估 + 成本 */
const store = useSystemStore()

const tab = ref('logs')
const logsFilter = reactive({ trace_id: '', level: '' })
const traceDrawer = ref(false)
const activeTraceId = ref<string | null>(null)

onMounted(() => {
  void store.listLogs()
  void store.loadCost()
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
        <p class="app-page-subtitle">运行日志 / trace 全链路 / 评估 / 成本</p>
      </div>
    </div>

    <el-tabs v-model="tab" class="sys-tabs">
      <!-- 运行日志 -->
      <el-tab-pane label="运行日志" name="logs">
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
      </el-tab-pane>

      <!-- 评估（docs/02 §6.2 / docs 06 §2.4）：评估集/用例/运行历史/配对比较 -->
      <el-tab-pane label="评估" name="evals">
        <template v-if="!store.evalsUnavailable">
        <EvalManage />
        </template>
        <EmptyState v-else text="后端暂未实现评估接口" />
      </el-tab-pane>

      <!-- 成本 -->
      <el-tab-pane label="成本" name="cost">
        <template v-if="!store.costUnavailable">
        <div class="cost-summary app-card">
          <div class="cost-item">
            <div class="cost-value">¥{{ store.cost?.total_cost.toFixed(2) ?? '-' }}</div>
            <div class="cost-label">总成本</div>
          </div>
          <div class="cost-item">
            <div class="cost-value">{{ store.cost?.total_calls ?? '-' }}</div>
            <div class="cost-label">总调用量</div>
          </div>
          <div class="cost-item">
            <div class="cost-value">{{ store.cost?.by_provider.length ?? 0 }}</div>
            <div class="cost-label">Provider 数</div>
          </div>
        </div>
        <div class="cost-providers" v-if="store.cost?.by_provider.length">
          <el-tag v-for="p in store.cost.by_provider" :key="p.provider" size="small" type="info" class="cost-provider-tag">
            {{ p.provider }}：¥{{ p.cost.toFixed(2) }} / {{ p.calls }} 次
          </el-tag>
        </div>
        <CostChart :data="store.cost" />
        </template>
        <EmptyState v-else text="后端暂未实现成本接口" />
      </el-tab-pane>
    </el-tabs>

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
.eval-set {
  padding: 12px 16px;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.eval-set-head {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}
.eval-name {
  font-weight: 600;
}
.eval-desc {
  font-size: 12px;
  color: var(--app-text-muted);
}
.eval-meta {
  color: var(--app-text-muted);
  font-size: 12px;
  margin-left: auto;
}
.eval-result {
  padding: 12px 16px;
}
.eval-result-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.cost-summary {
  display: flex;
  gap: 40px;
  padding: 16px 20px;
  margin-bottom: 12px;
}
.cost-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--app-primary);
}
.cost-label {
  font-size: 12px;
  color: var(--app-text-muted);
}
.cost-providers {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
</style>

<script setup lang="ts">
import { ElMessageBox } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import { formatDate } from '@/utils/format'
import StatusTag from '@/components/common/StatusTag.vue'

/** 任务列表（docs/02 §6.2）：状态过滤 + 分页 + 取消 */
const store = useTaskStore()
const emit = defineEmits<{ detail: [id: string] }>()

const STATUS_OPTIONS = [
  { label: '全部', value: '' },
  { label: '排队中', value: 'pending' },
  { label: '运行中', value: 'running' },
  { label: '等待确认', value: 'waiting_confirm' },
  { label: '已完成', value: 'done' },
  { label: '已取消', value: 'cancelled' },
  { label: '失败', value: 'failed' },
]

async function onCancel(id: string) {
  await ElMessageBox.confirm('确认取消该任务？（不可恢复）', '取消确认', { type: 'warning' })
  await store.cancel(id)
}
</script>

<template>
  <div class="task-list app-card">
    <div class="task-filter">
      <el-select
        :model-value="store.statusFilter"
        size="small"
        placeholder="状态过滤"
        @change="store.setStatusFilter"
      >
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
    </div>

    <el-table :data="store.tasks" v-loading="store.loading" size="small">
      <el-table-column prop="id" label="ID" width="110">
        <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
      </el-table-column>
      <el-table-column prop="agent_id" label="Agent" width="100" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }"><StatusTag :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="进度" width="140">
        <template #default="{ row }">
          <el-progress :percentage="row.progress ?? 0" :stroke-width="6" />
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="160">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="emit('detail', row.id)">详情</el-button>
          <el-button
            v-if="row.status === 'pending' || row.status === 'running'"
            size="small"
            text
            type="danger"
            @click="onCancel(row.id)"
          >取消</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.task-filter {
  padding: 10px;
  border-bottom: 1px solid var(--app-border-light);
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

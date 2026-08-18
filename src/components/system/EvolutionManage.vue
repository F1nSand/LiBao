<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useEvolutionStore } from '@/stores/evolution'
import type { CandidateAction } from '@/stores/evolution'
import { CANDIDATE_CHANGE_LABEL, CANDIDATE_STATUS_LABEL } from '@/constants/labels'
import { formatDate } from '@/utils/format'
import type { Candidate, CandidateChangeType, CandidateStatus } from '@/types'

/** 经验候选区（docs/06 §5 契约提案，mock 演示；后端未实现 → SystemView 侧 EmptyState）：
 * 候选 → 验证 → 批准 → 发布 → 回滚；详情抽屉展示变更契约字段。 */
const store = useEvolutionStore()

const drawerVisible = ref(false)
const detail = ref<Candidate | null>(null)
const actionLoading = ref<string | null>(null)

const STATUS_OPTIONS: Array<{ value: CandidateStatus | 'all'; label: string }> = [
  { value: 'all', label: '全部状态' },
  ...Object.entries(CANDIDATE_STATUS_LABEL).map(([value, label]) => ({ value: value as CandidateStatus, label })),
]

const TAG_TYPE: Record<CandidateStatus, 'info' | 'primary' | 'success' | 'warning' | 'danger'> = {
  candidate: 'info',
  validating: 'primary',
  approved: 'success',
  rejected: 'danger',
  published: 'success',
  rolled_back: 'warning',
}

/** 变更契约字段（docs/06 §5.6） */
const FIELDS: Array<{ key: keyof Candidate; label: string }> = [
  { key: 'evidence', label: '失败证据' },
  { key: 'root_cause', label: '推断根因' },
  { key: 'proposed_change', label: '候选修改' },
  { key: 'expected_fix', label: '预期修复' },
  { key: 'affected_behaviors', label: '受损行为' },
  { key: 'validation_cases', label: '验证用例' },
]

const ACTION_LABEL: Record<CandidateAction, string> = {
  validate: '验证',
  publish: '发布',
  reject: '拒绝',
  rollback: '回滚',
}

/** 状态动作配置（行内操作按钮 = 循环渲染；状态机与 mock 迁移约束一致） */
const ACTIONS: Array<{ action: CandidateAction; when: CandidateStatus; type: 'primary' | 'success' | 'warning' | 'danger' }> = [
  { action: 'validate', when: 'candidate', type: 'primary' },
  { action: 'reject', when: 'candidate', type: 'danger' },
  { action: 'publish', when: 'approved', type: 'success' },
  { action: 'rollback', when: 'published', type: 'warning' },
]

function renderField(v: unknown): string {
  if (v == null) return '未提供'
  if (Array.isArray(v)) return v.length ? v.join('；') : '未提供'
  return String(v)
}

/** el-table slot 的 row 是 any → 显示层用带收窄的 helper（避免隐式 any 索引 Record） */
function changeLabel(changeType: unknown): string {
  return CANDIDATE_CHANGE_LABEL[changeType as CandidateChangeType] ?? String(changeType)
}
function statusLabel(status: unknown): string {
  return CANDIDATE_STATUS_LABEL[status as CandidateStatus] ?? String(status)
}
function statusTagType(status: unknown): string {
  return TAG_TYPE[status as CandidateStatus] ?? 'info'
}

function reload() {
  void store.list()
}

async function openDetail(row: Candidate) {
  const id = row.id
  drawerVisible.value = true
  detail.value = row
  const d = await store.detail(id)
  // 竞态守卫：快速连点 A→B 时忽略 A 的迟到响应（真实后端有网络延迟时触发）
  if (d && detail.value?.id === id) detail.value = d
}

async function doAction(row: Candidate, action: CandidateAction) {
  const isDestructive = action === 'reject' || action === 'rollback'
  try {
    await ElMessageBox.confirm(`确认对「${row.title}」执行「${ACTION_LABEL[action]}」？`, '候选区操作', {
      type: isDestructive ? 'warning' : 'info',
      confirmButtonText: ACTION_LABEL[action],
    })
  } catch {
    return
  }
  actionLoading.value = `${row.id}:${action}`
  try {
    await store.runAction(row.id, action)
    ElMessage.success(`${ACTION_LABEL[action]}成功`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    actionLoading.value = null
  }
}

onMounted(() => void store.list())
</script>

<template>
  <div class="evolve">
    <div class="evolve-toolbar">
      <el-select v-model="store.statusFilter" size="small" style="width: 140px" @change="reload">
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
      </el-select>
      <el-input
        v-model="store.search"
        size="small"
        placeholder="搜索标题"
        clearable
        style="width: 220px"
        @keyup.enter="reload"
        @clear="reload"
      />
      <span class="evolve-total">共 {{ store.total }} 条候选</span>
    </div>

    <el-table :data="store.candidates" v-loading="store.loading" size="small" class="evolve-table" @row-click="openDetail">
      <el-table-column prop="title" label="变更提案" min-width="240" show-overflow-tooltip />
      <el-table-column label="载体" width="90">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ changeLabel(row.change_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="90">
        <template #default="{ row }">{{ row.source_type }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <template v-for="a in ACTIONS" :key="a.action">
            <el-button
              v-if="row.status === a.when"
              size="small"
              :type="a.type"
              text
              :loading="actionLoading === `${row.id}:${a.action}`"
              @click.stop="doAction(row, a.action)"
            >{{ ACTION_LABEL[a.action] }}</el-button>
          </template>
          <span v-if="['validating', 'rejected', 'rolled_back'].includes(row.status)" class="evolve-none">—</span>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer :model-value="drawerVisible" title="候选详情" size="480px" @close="drawerVisible = false">
      <div v-if="detail" class="evolve-detail">
        <div class="evolve-detail-title">{{ detail.title }}</div>
        <div class="evolve-meta">
          <el-tag size="small" :type="TAG_TYPE[detail.status]">{{ CANDIDATE_STATUS_LABEL[detail.status] }}</el-tag>
          <el-tag size="small" type="info">{{ CANDIDATE_CHANGE_LABEL[detail.change_type] }}</el-tag>
          <span class="mono evolve-src">{{ detail.source_type }}</span>
          <span v-if="detail.source_conversation_id" class="mono evolve-src">{{ detail.source_conversation_id }}</span>
        </div>
        <dl class="evolve-fields">
          <template v-for="f in FIELDS" :key="f.key">
            <dt>{{ f.label }}</dt>
            <dd>{{ renderField(detail[f.key]) }}</dd>
          </template>
        </dl>
      </div>
      <div v-else class="evolve-none">加载中…</div>
    </el-drawer>
  </div>
</template>

<style scoped>
.evolve-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.evolve-total {
  font-size: 12px;
  color: var(--app-text-muted);
  margin-left: auto;
}
.evolve-table {
  cursor: pointer;
}
.evolve-none {
  color: var(--app-text-muted);
  font-size: 12px;
}
.evolve-detail-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 8px;
  line-height: 1.5;
}
.evolve-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.evolve-src {
  font-size: 12px;
  color: var(--app-text-muted);
}
.evolve-fields {
  margin: 0;
}
.evolve-fields dt {
  font-size: 12px;
  color: var(--app-text-muted);
  margin-top: 10px;
}
.evolve-fields dd {
  margin: 2px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--app-text-main);
  white-space: pre-wrap;
  word-break: break-word;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

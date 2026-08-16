<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSystemStore } from '@/stores/system'
import { runEval as apiRunEval } from '@/api/system'
import { swallowNotImplemented } from '@/utils/http-envelope'
import { formatDate } from '@/utils/format'
import type { EvalCaseResult, EvalRun, EvalSet } from '@/types'
import StatusTag from '@/components/common/StatusTag.vue'

/**
 * 评估管理（docs/02 §6.2 / docs 06 §2.4）：评估集 CRUD + 用例管理 + 运行历史 + 配对比较。
 * 数据走 system store；后端未实现时 SystemView 外层用 EmptyState 降级。
 */
const store = useSystemStore()

const selectedSet = ref<EvalSet | null>(null)
const selectedRun = ref<EvalRun | null>(null)
const runResult = ref<{ run: EvalRun; results: EvalCaseResult[] } | null>(null)
const evalRunLoading = ref(false)

/* 新建/重命名集 */
const setDialog = ref(false)
const setForm = reactive({ name: '', description: '', editingId: null as string | null })
/* 添加用例 */
const caseDialog = ref(false)
const caseForm = reactive({ input: '', expected: '', layer: 'L1' })
/* 配对比较 */
const pairDialog = ref(false)
const pairForm = reactive({ candidateRunId: '', baselineRunId: '' })

onMounted(() => {
  void store.listEvals()
  void store.loadEvalRuns()
})

function selectSet(set: EvalSet) {
  selectedSet.value = set
  void store.loadEvalCases(set.id)
}

/* ---------- 评估集 ---------- */
function openCreateSet() {
  Object.assign(setForm, { name: '', description: '', editingId: null })
  setDialog.value = true
}
function openEditSet(set: EvalSet) {
  Object.assign(setForm, { name: set.name, description: set.description ?? '', editingId: set.id })
  setDialog.value = true
}
async function saveSet() {
  if (!setForm.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  if (setForm.editingId) await store.updateSet(setForm.editingId, { name: setForm.name.trim(), description: setForm.description.trim() || undefined })
  else await store.createSet({ name: setForm.name.trim(), description: setForm.description.trim() || undefined })
  setDialog.value = false
  ElMessage.success('已保存')
}
async function onDeleteSet(set: EvalSet) {
  await ElMessageBox.confirm(`删除评估集「${set.name}」及其全部用例？`, '确认删除', { type: 'warning' })
  await store.removeSet(set.id)
  if (selectedSet.value?.id === set.id) selectedSet.value = null
  ElMessage.success('已删除')
}

/* ---------- 用例 ---------- */
function openAddCase() {
  Object.assign(caseForm, { input: '', expected: '', layer: 'L1' })
  caseDialog.value = true
}
async function saveCase() {
  if (!selectedSet.value) return
  if (!caseForm.input.trim() || !caseForm.expected.trim()) {
    ElMessage.warning('请输入输入与期望输出')
    return
  }
  await store.addCase(selectedSet.value.id, { input: caseForm.input.trim(), expected: caseForm.expected.trim(), layer: caseForm.layer || undefined })
  caseDialog.value = false
  ElMessage.success('已添加')
}
async function onToggleCase(caseId: string, active: boolean) {
  if (!selectedSet.value) return
  await store.toggleCase(selectedSet.value.id, caseId, active)
}
async function onDeleteCase(caseId: string) {
  if (!selectedSet.value) return
  await ElMessageBox.confirm('删除该用例？', '确认删除', { type: 'warning' })
  await store.removeCase(selectedSet.value.id, caseId)
}

/* ---------- 运行 ---------- */
const EVAL_POLL_INTERVAL_MS = 2500
const EVAL_POLL_TIMEOUT_MS = 120_000
const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

async function onRunEval(evalSetId: string) {
  evalRunLoading.value = true
  try {
    const run = await swallowNotImplemented(apiRunEval(evalSetId))
    if (!run) {
      ElMessage.warning('后端暂未实现评估运行接口')
      return
    }
    // 后台链（docs/03 §5.8）：轮询至终态
    const deadline = Date.now() + EVAL_POLL_TIMEOUT_MS
    let detail = await swallowNotImplemented(store.evalRunDetail(run.id))
    while (detail && detail.run.status !== 'done' && detail.run.status !== 'failed' && Date.now() < deadline) {
      await delay(EVAL_POLL_INTERVAL_MS)
      detail = await swallowNotImplemented(store.evalRunDetail(run.id))
    }
    if (!detail) {
      ElMessage.warning('后端暂未实现评估结果接口')
      return
    }
    runResult.value = detail
    selectedRun.value = detail.run
    void store.loadEvalRuns()
    if (detail.run.status === 'failed') ElMessage.error('评估运行失败')
    else ElMessage.success(`评估运行完成 · 通过率 ${Math.round((detail.run.pass_rate ?? 0) * 100)}%`)
  } finally {
    evalRunLoading.value = false
  }
}

async function selectRun(run: EvalRun) {
  selectedRun.value = run
  const detail = await swallowNotImplemented(store.evalRunDetail(run.id))
  if (detail) runResult.value = detail
}

/* ---------- 配对比较 ---------- */
function openPair() {
  pairForm.candidateRunId = selectedRun.value?.id ?? store.evalRuns[0]?.id ?? ''
  pairForm.baselineRunId = store.evalRuns.find((r) => r.id !== pairForm.candidateRunId)?.id ?? ''
  pairDialog.value = true
}
async function loadPairwise() {
  if (!pairForm.candidateRunId || !pairForm.baselineRunId) {
    ElMessage.warning('请选择候选运行与基线运行')
    return
  }
  await store.loadPairwise(pairForm.candidateRunId, pairForm.baselineRunId)
  pairDialog.value = false
}
const OUTCOME_LABEL: Record<string, string> = { win: '改进', lose: '回退', tie: '持平' }
</script>

<template>
  <div class="eval-manage">
    <div class="eval-cols">
      <!-- 评估集 -->
      <div class="eval-pane app-card">
        <div class="pane-head">
          <span class="pane-title">评估集</span>
          <el-button size="small" type="primary" @click="openCreateSet">新建</el-button>
        </div>
        <el-table :data="store.evalSets" size="small" highlight-current-row @current-change="(r: EvalSet) => r && selectSet(r)">
          <el-table-column prop="name" label="名称" min-width="100">
            <template #default="{ row }"><span class="eval-name">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column prop="case_count" label="用例" width="56" />
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click.stop="selectSet(row)">用例</el-button>
              <el-button size="small" link type="success" :loading="evalRunLoading" @click.stop="onRunEval(row.id)">运行</el-button>
              <el-dropdown trigger="click" @command="(c: string) => c === 'edit' ? openEditSet(row) : onDeleteSet(row)">
                <el-button size="small" link type="info">⋯</el-button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item command="edit">重命名</el-dropdown-item><el-dropdown-item command="del" divided>删除</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 用例（选中集） -->
      <div v-if="selectedSet" class="eval-pane app-card">
        <div class="pane-head">
          <span class="pane-title">{{ selectedSet.name }} · 用例</span>
          <el-button size="small" type="primary" @click="openAddCase">添加用例</el-button>
        </div>
        <el-table :data="store.evalCases" size="small">
          <el-table-column prop="input" label="输入" min-width="130" show-overflow-tooltip />
          <el-table-column prop="expected" label="期望" min-width="100" show-overflow-tooltip />
          <el-table-column prop="layer" label="层" width="56" />
          <el-table-column label="启用" width="64">
            <template #default="{ row }">
              <el-switch :model-value="row.active" size="small" @change="(v: boolean) => onToggleCase(row.id, v)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="56">
            <template #default="{ row }">
              <el-button size="small" link type="danger" @click="onDeleteCase(row.id)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 运行历史 -->
      <div class="eval-pane app-card">
        <div class="pane-head">
          <span class="pane-title">运行历史</span>
          <el-button size="small" :loading="evalRunLoading" @click="onRunEval(selectedSet?.id ?? store.evalSets[0]?.id ?? '')">运行评估</el-button>
          <el-button size="small" @click="openPair">配对比较</el-button>
        </div>
        <el-table :data="store.evalRuns" size="small" highlight-current-row @current-change="(r: EvalRun) => r && selectRun(r)">
          <el-table-column label="状态" width="72">
            <template #default="{ row }"><StatusTag :status="row.status" /></template>
          </el-table-column>
          <el-table-column label="通过率" width="66">
            <template #default="{ row }">{{ row.pass_rate != null ? `${Math.round(row.pass_rate * 100)}%` : '—' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="时间" width="140">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
        </el-table>
        <div v-if="runResult" class="run-result">
          <div class="run-result-title">运行结果（{{ Math.round((runResult.run.pass_rate ?? 0) * 100) }}%）</div>
          <el-table :data="runResult.results" size="small">
            <el-table-column prop="input" label="输入" min-width="110" show-overflow-tooltip />
            <el-table-column label="结果" width="70">
              <template #default="{ row }"><el-tag size="small" :type="row.pass ? 'success' : 'danger'">{{ row.pass ? 'PASS' : 'FAIL' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="latency_ms" label="耗时ms" width="70" />
            <el-table-column prop="cost" label="成本" width="70" />
          </el-table>
        </div>
      </div>
    </div>

    <!-- 配对比较结果 -->
    <div v-if="store.pairwise" class="pairwise app-card">
      <div class="pane-head">
        <span class="pane-title">配对比较（候选 {{ Math.round(store.pairwise.summary.candidate_pass_rate * 100) }}% vs 基线 {{ Math.round(store.pairwise.summary.baseline_pass_rate * 100) }}%，Δ{{ (store.pairwise.summary.delta * 100).toFixed(1) }}%）</span>
        <span class="pairwise-count">W {{ store.pairwise.summary.wins }} · L {{ store.pairwise.summary.losses }} · T {{ store.pairwise.summary.ties }}</span>
      </div>
      <el-table :data="store.pairwise.matrix" size="small">
        <el-table-column prop="input" label="用例" min-width="120" show-overflow-tooltip />
        <el-table-column label="基线" width="70">
          <template #default="{ row }">{{ row.baseline_pass ? 'PASS' : 'FAIL' }}</template>
        </el-table-column>
        <el-table-column label="候选" width="70">
          <template #default="{ row }">{{ row.candidate_pass ? 'PASS' : 'FAIL' }}</template>
        </el-table-column>
        <el-table-column label="结果" width="70">
          <template #default="{ row }">
            <el-tag size="small" :type="row.outcome === 'win' ? 'success' : row.outcome === 'lose' ? 'danger' : 'info'">{{ OUTCOME_LABEL[row.outcome] }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建/重命名集 -->
    <el-dialog :model-value="setDialog" :title="setForm.editingId ? '重命名评估集' : '新建评估集'" width="420px" @close="setDialog = false">
      <el-form label-width="60px">
        <el-form-item label="名称"><el-input v-model="setForm.name" placeholder="评估集名称" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="setForm.description" placeholder="用途说明" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="setDialog = false">取消</el-button><el-button type="primary" @click="saveSet">保存</el-button></template>
    </el-dialog>

    <!-- 添加用例 -->
    <el-dialog :model-value="caseDialog" title="添加用例" width="480px" @close="caseDialog = false">
      <el-form label-width="60px">
        <el-form-item label="输入"><el-input v-model="caseForm.input" type="textarea" :rows="2" placeholder="用户输入 / 任务描述" /></el-form-item>
        <el-form-item label="期望"><el-input v-model="caseForm.expected" type="textarea" :rows="2" placeholder="期望输出 / 判定依据" /></el-form-item>
        <el-form-item label="层级">
          <el-select v-model="caseForm.layer" style="width: 160px">
            <el-option v-for="l in ['L1', 'L2', 'L3', 'L4', 'L5']" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="caseDialog = false">取消</el-button><el-button type="primary" @click="saveCase">添加</el-button></template>
    </el-dialog>

    <!-- 配对比较选择 -->
    <el-dialog :model-value="pairDialog" title="配对比较" width="480px" @close="pairDialog = false">
      <el-form label-width="80px">
        <el-form-item label="候选运行">
          <el-select v-model="pairForm.candidateRunId" style="width: 100%">
            <el-option v-for="r in store.evalRuns" :key="r.id" :label="`${formatDate(r.created_at)} · ${r.pass_rate != null ? Math.round(r.pass_rate * 100) + '%' : '—'}`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="基线运行">
          <el-select v-model="pairForm.baselineRunId" style="width: 100%">
            <el-option v-for="r in store.evalRuns" :key="r.id" :label="`${formatDate(r.created_at)} · ${r.pass_rate != null ? Math.round(r.pass_rate * 100) + '%' : '—'}`" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="pairDialog = false">取消</el-button><el-button type="primary" @click="loadPairwise">比较</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.eval-cols {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.eval-pane {
  flex: 1;
  min-width: 0;
  padding: 12px;
}
.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.pane-title {
  font-weight: 600;
}
.eval-name {
  font-weight: 500;
}
.run-result {
  margin-top: 10px;
  border-top: 1px solid var(--app-border-light);
  padding-top: 8px;
}
.run-result-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.pairwise {
  margin-top: 12px;
  padding: 12px;
}
.pairwise-count {
  color: var(--app-text-muted);
  font-size: 12px;
}
</style>

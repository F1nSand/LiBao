<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { agentTemplate } from '@/mock/db'
import type { Agent, AgentConfigInput } from '@/types'
import AgentConfigForm from '@/components/business/AgentConfigForm.vue'
import AgentTestRunner from '@/components/business/AgentTestRunner.vue'
import StatusTag from '@/components/common/StatusTag.vue'

/** Agent 管理（docs/02 §4 / docs/03 §5.4）：CRUD + 发布/下线 + 试跑 */
const store = useAgentStore()

const formVisible = ref(false)
const editingId = ref<string | null>(null)
const form = reactive<AgentConfigInput>({ ...agentTemplate() })

const testVisible = ref(false)
const activeAgent = ref<Agent | null>(null)

onMounted(() => void store.list())

function openCreate() {
  editingId.value = null
  Object.assign(form, agentTemplate())
  formVisible.value = true
}

function openEdit(a: Agent) {
  editingId.value = a.id
  Object.assign(form, {
    name: a.name,
    model: a.model,
    system_prompt: a.system_prompt,
    skills: [...a.skills],
    tools: [...a.tools],
    graph_template: a.graph_template,
    max_steps: a.max_steps,
  })
  formVisible.value = true
}

async function save() {
  if (!form.name || !form.model) {
    ElMessage.warning('请填写名称与模型')
    return
  }
  const body: AgentConfigInput = {
    name: form.name,
    model: form.model,
    system_prompt: form.system_prompt,
    skills: form.skills ?? [],
    tools: form.tools ?? [],
    graph_template: form.graph_template,
    max_steps: form.max_steps ?? 50,
  }
  if (editingId.value) await store.update(editingId.value, body)
  else await store.create(body)
  formVisible.value = false
  ElMessage.success('已保存')
}

async function onPublish(a: Agent) {
  await store.publish(a.id)
  ElMessage.success('已发布')
}

async function onUnpublish(a: Agent) {
  await store.unpublish(a.id)
  ElMessage.success('已下线')
}

async function onDelete(a: Agent) {
  await ElMessageBox.confirm(`确认删除 Agent「${a.name}」？（软删，保留历史版本）`, '删除确认', { type: 'warning' })
  await store.remove(a.id)
  ElMessage.success('已删除')
}

function onTest(a: Agent) {
  activeAgent.value = a
  testVisible.value = true
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">Agents</h2>
        <p class="app-page-subtitle">模型 / 提示词 / 技能 / 工具配置</p>
      </div>
      <el-button type="primary" :icon="'Plus'" @click="openCreate">新建 Agent</el-button>
    </div>

    <div v-loading="store.loading" class="agent-grid">
      <el-card v-for="a in store.agents" :key="a.id" shadow="hover" class="agent-card">
        <template #header>
          <div class="agent-card-head">
            <span class="agent-name">{{ a.name }}</span>
            <StatusTag :status="a.status" />
          </div>
        </template>
        <div class="agent-meta">
          <div class="agent-row"><span class="agent-label">模型</span><span class="mono">{{ a.model }}</span></div>
          <div class="agent-row"><span class="agent-label">模板</span><span>{{ a.graph_template }}</span></div>
          <div class="agent-row"><span class="agent-label">工具</span><span>{{ a.tools.length }} 个</span></div>
          <div class="agent-row"><span class="agent-label">版本</span><span>v{{ a.current_version }}</span></div>
        </div>
        <template #footer>
          <div class="agent-actions">
            <el-button size="small" @click="openEdit(a)">编辑</el-button>
            <el-button v-if="a.status !== 'published'" size="small" type="success" @click="onPublish(a)">发布</el-button>
            <el-button v-else size="small" type="warning" @click="onUnpublish(a)">下线</el-button>
            <el-button size="small" type="primary" plain @click="onTest(a)">试跑</el-button>
            <el-button size="small" type="danger" plain @click="onDelete(a)">删除</el-button>
          </div>
        </template>
      </el-card>
      <el-empty v-if="!store.loading && store.agents.length === 0" description="暂无 Agent" />
    </div>

    <el-dialog
      :model-value="formVisible"
      :title="editingId ? '编辑 Agent（保存即新建版本）' : '新建 Agent'"
      width="560px"
      @close="formVisible = false"
    >
      <AgentConfigForm :model="form" @update:model="(v) => Object.assign(form, v)" />
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="testVisible" :title="`试跑：${activeAgent?.name ?? ''}`" width="640px" @close="testVisible = false">
      <AgentTestRunner v-if="activeAgent" :agent-id="activeAgent.id" />
    </el-dialog>
  </div>
</template>

<style scoped>
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  overflow-y: auto;
  padding-bottom: 20px;
}
.agent-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.agent-name {
  font-weight: 600;
}
.agent-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.agent-row {
  display: flex;
  gap: 8px;
}
.agent-label {
  color: var(--app-text-muted);
  width: 44px;
  flex-shrink: 0;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
.agent-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>

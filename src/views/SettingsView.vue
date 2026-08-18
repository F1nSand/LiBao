<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listUsers,
  createUser,
  patchUserRole,
  patchUserStatus,
  deleteUser,
} from '@/api/users'
import { listHooks, registerHook, unregisterHook } from '@/api/hooks'
import { listProviders, createProvider, updateProvider, deleteProvider } from '@/api/provider'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import { formatDate } from '@/utils/format'
import EmptyState from '@/components/common/EmptyState.vue'
import { ROLE_LABEL } from '@/constants/labels'
import type { ProviderConfig, Role, User, WebhookConfig } from '@/types'

/** 设置（docs/02 §4 / docs/03 §5.1）：用户与权限 + Provider 配置 + Webhook 管理 */
const tab = ref('users')

const users = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
/** 后端未实现 /users（HTTP 404 打标）→ 用户 tab 显示空态 */
const usersUnavailable = computed(() => isUnavailable(FEATURE.users))

const createVisible = ref(false)
const createForm = reactive({ username: '', password: '', name: '', role: 'viewer' as Role, org_id: 'org_1' })

/** 组织筛选（数据隔离：客户端过滤，不改 listUsers 契约；org_id 来自 mock/真实用户数据） */
const orgFilter = ref('all')
const orgOptions = computed(() => [...new Set(users.value.map((u) => u.org_id).filter((v): v is string => !!v))])
const filteredUsers = computed(() =>
  orgFilter.value === 'all' ? users.value : users.value.filter((u) => u.org_id === orgFilter.value),
)

/* ---------- Provider 配置（契约见 api/provider.ts，后端未实现走降级） ---------- */
const providers = ref<ProviderConfig[]>([])
const providersUnavailable = computed(() => isUnavailable(FEATURE.providers))
const providerDialog = ref(false)
const providerForm = reactive({ name: 'openai', base_url: '', api_key: '', model: '' })
const providerLoading = ref(false)

/* ---------- Webhook 管理（docs/03 §5.10） ---------- */
const hooks = ref<WebhookConfig[]>([])
const hooksUnavailable = computed(() => isUnavailable(FEATURE.hooks))
const hookDialog = ref(false)
const hookForm = reactive({ tool_id: '', token: '', conversation_id: '' })

async function load(pageNo = 1) {
  loading.value = true
  try {
    // 后端未实现 /users → 返回 undefined（已打标），页面显示空态；其余错误照常抛
    const res = await swallowNotImplemented(listUsers({ page: pageNo, page_size: pageSize }))
    if (res) {
      users.value = res.items
      total.value = res.total
      page.value = res.page
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  void loadProviders()
  void loadHooks()
})

async function onCreate() {
  if (!createForm.username || !createForm.password) {
    ElMessage.warning('请填写用户名与密码')
    return
  }
  // 后端未实现写操作 → 返回 undefined（已打标，tab 折叠空态），不弹错不崩
  const created = await swallowNotImplemented(
    createUser({ ...createForm, name: createForm.name || createForm.username }),
  )
  if (created === undefined) return
  createVisible.value = false
  Object.assign(createForm, { username: '', password: '', name: '', role: 'viewer', org_id: 'org_1' })
  ElMessage.success('用户已创建')
  await load()
}

async function onChangeRole(u: User, role: Role) {
  const ok = await swallowNotImplemented(patchUserRole(u.id, role))
  if (ok === undefined) return
  u.role = role
  ElMessage.success('角色已更新')
}

async function onChangeStatus(u: User, enabled: boolean) {
  if (!enabled) {
    await ElMessageBox.confirm(`禁用用户「${u.name}」将立即踢下线，确认？`, '禁用确认', { type: 'warning' })
  }
  const ok = await swallowNotImplemented(patchUserStatus(u.id, enabled))
  if (ok === undefined) return
  u.enabled = enabled
  ElMessage.success(enabled ? '已启用' : '已禁用')
}

async function onDelete(u: User) {
  await ElMessageBox.confirm(`确认删除用户「${u.name}」？（软删，保留历史）`, '删除确认', { type: 'warning' })
  const ok = await swallowNotImplemented(deleteUser(u.id))
  if (ok === undefined) return
  ElMessage.success('已删除')
  await load()
}

/* ---------- Provider 配置 ---------- */
async function loadProviders() {
  providerLoading.value = true
  try {
    const list = await swallowNotImplemented(listProviders())
    if (list) providers.value = list
  } finally {
    providerLoading.value = false
  }
}

async function openAddProvider() {
  Object.assign(providerForm, { name: 'openai', base_url: '', api_key: '', model: '' })
  providerDialog.value = true
}

async function saveProvider() {
  const created = await swallowNotImplemented(
    createProvider({
      name: providerForm.name,
      base_url: providerForm.base_url || undefined,
      api_key: providerForm.api_key || undefined,
      model: providerForm.model || undefined,
    }),
  )
  if (created === undefined) return // 后端未实现 → 打标降级，不弹错
  providerDialog.value = false
  ElMessage.success('Provider 已保存')
  await loadProviders()
}

async function onToggleProvider(p: ProviderConfig, enabled: boolean) {
  const ok = await swallowNotImplemented(updateProvider(p.id, { enabled }))
  if (ok === undefined) return
  p.enabled = enabled
}

async function onDeleteProvider(id: string) {
  await ElMessageBox.confirm('删除该 Provider 配置？', '确认删除', { type: 'warning' })
  const ok = await swallowNotImplemented(deleteProvider(id))
  if (ok === undefined) return
  ElMessage.success('已删除')
  await loadProviders()
}

/* ---------- Webhook 管理 ---------- */
async function loadHooks() {
  const list = await swallowNotImplemented(listHooks())
  if (list) hooks.value = list
}

async function registerWebhook() {
  if (!hookForm.tool_id.trim() || !hookForm.token.trim()) {
    ElMessage.warning('请填写 tool_id 与 token')
    return
  }
  const created = await swallowNotImplemented(
    registerHook(hookForm.tool_id.trim(), {
      token: hookForm.token.trim(),
      conversation_id: hookForm.conversation_id.trim() || undefined,
    }),
  )
  if (created === undefined) return
  hookDialog.value = false
  Object.assign(hookForm, { tool_id: '', token: '', conversation_id: '' })
  ElMessage.success('Webhook 已注册')
  await loadHooks()
}

async function onDeleteHook(toolId: string) {
  await ElMessageBox.confirm(`删除 ${toolId} 的 webhook？`, '确认删除', { type: 'warning' })
  const ok = await swallowNotImplemented(unregisterHook(toolId))
  if (ok === undefined) return
  ElMessage.success('已删除')
  await loadHooks()
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">设置</h2>
        <p class="app-page-subtitle">Provider / 用户与权限 / Webhook 管理</p>
      </div>
    </div>

    <el-tabs v-model="tab" class="settings-tabs">
      <el-tab-pane label="用户与权限" name="users">
        <template v-if="!usersUnavailable">
          <div class="users-toolbar">
            <el-select v-model="orgFilter" size="small" style="width: 130px">
              <el-option label="全部组织" value="all" />
              <el-option v-for="org in orgOptions" :key="org" :label="org" :value="org" />
            </el-select>
            <el-button type="primary" :icon="'Plus'" @click="createVisible = true">新建用户</el-button>
          </div>
          <el-table :data="filteredUsers" v-loading="loading" size="small">
            <el-table-column prop="username" label="用户名" width="140" />
            <el-table-column prop="name" label="姓名" width="140" />
            <el-table-column prop="org_id" label="组织" width="100">
              <template #default="{ row }"><span class="mono">{{ row.org_id ?? '—' }}</span></template>
            </el-table-column>
            <el-table-column label="角色" width="160">
              <template #default="{ row }">
                <el-select :model-value="row.role" size="small" @change="(r: Role) => onChangeRole(row, r)">
                  <el-option v-for="(label, val) in ROLE_LABEL" :key="val" :label="label" :value="val" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  size="small"
                  @change="(v: boolean) => onChangeStatus(row, v)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="danger" @click="onDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <EmptyState v-else text="后端暂未实现用户与权限接口" />
      </el-tab-pane>

      <!-- Provider 配置（契约见 api/provider.ts，后端未实现走降级） -->
      <el-tab-pane label="Provider 配置" name="provider">
        <template v-if="!providersUnavailable">
          <div class="users-toolbar">
            <el-button type="primary" :icon="'Plus'" @click="openAddProvider">添加 Provider</el-button>
          </div>
          <el-table :data="providers" v-loading="providerLoading" size="small">
            <el-table-column prop="name" label="Provider" width="120" />
            <el-table-column prop="base_url" label="Base URL" min-width="200" show-overflow-tooltip />
            <el-table-column prop="model" label="模型" width="140" />
            <el-table-column label="API Key" width="90">
              <template #default="{ row }">{{ row.has_key ? '已配置' : '未配置' }}</template>
            </el-table-column>
            <el-table-column label="启用" width="80">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" size="small" @change="(v: boolean) => onToggleProvider(row, v)" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" text type="danger" @click="onDeleteProvider(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <EmptyState v-else text="后端暂未实现 Provider 配置接口（契约已发交接板）" />
      </el-tab-pane>

      <!-- Webhook 管理（docs/03 §5.10） -->
      <el-tab-pane label="Webhook 管理" name="hooks">
        <template v-if="!hooksUnavailable">
          <div class="users-toolbar">
            <el-button type="primary" :icon="'Plus'" @click="hookDialog = true">注册 Webhook</el-button>
          </div>
          <el-table :data="hooks" size="small">
            <el-table-column prop="tool_id" label="tool_id" width="160" />
            <el-table-column label="目标会话" min-width="260">
              <template #default="{ row }"><span class="mono">{{ row.conversation_id ?? '—' }}</span></template>
            </el-table-column>
            <el-table-column label="启用" width="80">
              <template #default="{ row }">{{ row.enabled ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180">
              <template #default="{ row }">{{ row.created_at ? formatDate(row.created_at) : '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" text type="danger" @click="onDeleteHook(row.tool_id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <EmptyState v-else text="后端暂未实现 Webhook 接口" />
      </el-tab-pane>
    </el-tabs>

    <el-dialog :model-value="createVisible" title="新建用户" width="440px" @close="createVisible = false">
      <el-form label-width="80px">
        <el-form-item label="用户名"><el-input v-model="createForm.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="createForm.password" type="password" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="组织"><el-input v-model="createForm.org_id" placeholder="如 org_1 / org_2" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role">
            <el-option v-for="(label, val) in ROLE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 添加 Provider -->
    <el-dialog :model-value="providerDialog" title="添加 Provider" width="460px" @close="providerDialog = false">
      <el-form label-width="80px">
        <el-form-item label="Provider">
          <el-select v-model="providerForm.name">
            <el-option label="OpenAI" value="openai" />
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="Qwen" value="qwen" />
            <el-option label="Kimi" value="kimi" />
            <el-option label="Ollama" value="ollama" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL"><el-input v-model="providerForm.base_url" placeholder="https://api.openai.com/v1" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="providerForm.api_key" type="password" show-password placeholder="凭证走密钥管理，不回传" /></el-form-item>
        <el-form-item label="模型"><el-input v-model="providerForm.model" placeholder="默认模型，如 gpt-4o / deepseek-chat" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialog = false">取消</el-button>
        <el-button type="primary" @click="saveProvider">保存</el-button>
      </template>
    </el-dialog>

    <!-- 注册 Webhook -->
    <el-dialog :model-value="hookDialog" title="注册 Webhook" width="460px" @close="hookDialog = false">
      <el-form label-width="90px">
        <el-form-item label="tool_id"><el-input v-model="hookForm.tool_id" placeholder="事件型工具的 id，如 tl_demo_notify" /></el-form-item>
        <el-form-item label="Token"><el-input v-model="hookForm.token" placeholder="共享密钥（只存 hash，调用方需保管）" /></el-form-item>
        <el-form-item label="目标会话"><el-input v-model="hookForm.conversation_id" placeholder="事件投递目标会话（可选）" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="hookDialog = false">取消</el-button>
        <el-button type="primary" @click="registerWebhook">注册</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.users-toolbar {
  margin-bottom: 10px;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

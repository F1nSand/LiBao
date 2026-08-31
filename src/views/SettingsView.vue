<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listProviders, createProvider, updateProvider, deleteProvider, activateProvider, getActiveProvider } from '@/api/provider'
import { getSandboxSettings, updateSandboxSettings } from '@/api/sandbox'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import EmptyState from '@/components/common/EmptyState.vue'
import { useNotifications } from '@/composables/useNotifications'
import { useSSE } from '@/composables/useSSE'
import { THEMES, getStoredTheme } from '@/theme/themes'
import NotificationPane from '@/components/layout/NotificationPane.vue'
import ThemePane from '@/components/layout/ThemePane.vue'
import AsyncState from '@/components/common/AsyncState.vue'
import ResponsiveDialog from '@/components/common/ResponsiveDialog.vue'
import type { ProviderConfig } from '@/types'
import type { SandboxMode, SandboxSettings } from '@/api/sandbox'

type ProviderListStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error' | 'unavailable'

/** 设置（《02》前端设计 §4 / 《02》接口契约 §5.1）：单用户本地模式 → Provider 配置 / 通知 / 主题 三个 pane（tag 切换，非悬浮窗） */

/* ---------- 设置组切换 ---------- */
const activeTab = ref<'provider' | 'sandbox' | 'notifications' | 'theme'>('provider')
const pageSubtitle = computed(
  () => ({ provider: 'Provider 配置', sandbox: '命令执行沙箱', notifications: '通知', theme: '主题配色' })[activeTab.value],
)

/* ---------- 主题（themeId 由本页持有，tag 圆点 + ThemePane 同源） ---------- */
const themeId = ref(getStoredTheme())
const currentPrimary = computed(() => THEMES.find((t) => t.id === themeId.value)?.preview.primary ?? '')

/* ---------- 通知（模块级单例状态；SSE 连接归本页持有，卸载断流） ---------- */
const { unread, load: loadNotifications, applyEvent } = useNotifications()
const sse = useSSE(
  '/api/v1/notifications/stream',
  () => ({ method: 'GET', headers: { Accept: 'text/event-stream' } }),
  { onEvent: applyEvent },
)

/* ---------- Provider 配置（契约见 api/provider.ts，后端未实现走降级） ---------- */
const providers = ref<ProviderConfig[]>([])
const providersUnavailable = computed(() => isUnavailable(FEATURE.providers))
const activeProvider = ref<ProviderConfig | null>(null)
const providerDialog = ref(false)
const providerDialogMode = ref<'create' | 'edit'>('create')
const providerForm = reactive({
  id: '',
  name: '',
  website: '',
  base_url: '',
  is_full_url: false,
  api_key: '',
  model: '',
})
const providerStatus = ref<ProviderListStatus>('idle')
const providerErrorMessage = ref<string | null>(null)
const providerSubmitting = ref(false)
const providerNameRef = ref<HTMLElement | null>(null)
const providerNameError = ref('')
const providerBaseUrlError = ref('')
const providerModelError = ref('')

const sandboxSettings = ref<SandboxSettings | null>(null)
const sandboxLoading = ref(false)
const sandboxSaving = ref(false)
const sandboxError = ref<string | null>(null)
const sandboxModes: Array<{ id: SandboxMode; title: string; detail: string }> = [
  { id: 'powershell', title: 'PowerShell 7', detail: '宿主工作区 · Windows 原生语法' },
  { id: 'git_bash', title: 'Git Bash', detail: '宿主工作区 · POSIX shell 语法' },
  { id: 'docker', title: 'Docker Bash', detail: '容器强隔离 · 无网络、只挂载当前工作区' },
]

onMounted(() => {
  void loadProviders()
  void loadActiveProvider()
  void loadSandboxSettings()
  void loadNotifications()
  if (!isUnavailable(FEATURE.notifications)) sse.connect()
})
onBeforeUnmount(() => sse.disconnect())

/* ---------- Provider 配置 ---------- */
async function loadProviders() {
  providerStatus.value = 'loading'
  providerErrorMessage.value = null
  try {
    const list = await swallowNotImplemented(listProviders())
    if (list) {
      providers.value = list
      providerStatus.value = list.length ? 'success' : 'success-empty'
    } else {
      providerStatus.value = 'unavailable'
    }
  } catch (e) {
    providerStatus.value = 'error'
    providerErrorMessage.value = e instanceof Error ? e.message : 'Provider 列表加载失败'
  }
}

async function loadSandboxSettings() {
  sandboxLoading.value = true
  sandboxError.value = null
  try {
    sandboxSettings.value = await getSandboxSettings()
  } catch (e) {
    sandboxError.value = e instanceof Error ? e.message : '沙箱设置加载失败'
  } finally {
    sandboxLoading.value = false
  }
}

async function selectSandboxMode(mode: SandboxMode) {
  const backend = sandboxSettings.value?.backends[mode]
  if (!backend?.available) {
    ElMessage.warning(backend?.detail || '该沙箱后端不可用')
    return
  }
  const previous = sandboxSettings.value
  sandboxSaving.value = true
  try {
    sandboxSettings.value = await updateSandboxSettings(mode)
    ElMessage.success(`已切换到 ${sandboxModes.find((item) => item.id === mode)?.title}`)
  } catch (e) {
    sandboxSettings.value = previous
    ElMessage.error(e instanceof Error ? e.message : '沙箱切换失败')
  } finally {
    sandboxSaving.value = false
  }
}

async function retryProviders() {
  await loadProviders()
}

function onTabKeydown(e: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
  const current = e.currentTarget as HTMLElement
  const tabs = Array.from(current.parentElement?.querySelectorAll<HTMLElement>('[role="tab"]') ?? [])
  const position = tabs.indexOf(current)
  const nextPosition = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : position + (e.key === 'ArrowRight' ? 1 : -1)
  const next = tabs[nextPosition]
  if (!next) return
  e.preventDefault()
  next.focus()
  const nextTab = next.dataset.tab as typeof activeTab.value | undefined
  if (nextTab) activeTab.value = nextTab
}

async function loadActiveProvider() {
  const active = await swallowNotImplemented(getActiveProvider())
  if (active !== undefined) activeProvider.value = active
}

function resetProviderForm() {
  Object.assign(providerForm, {
    id: '', name: '', website: '', base_url: '', is_full_url: false, api_key: '', model: '',
  })
  providerNameError.value = ''
  providerBaseUrlError.value = ''
  providerModelError.value = ''
}

async function openAddProvider() {
  resetProviderForm()
  providerDialogMode.value = 'create'
  providerDialog.value = true
}

function openEditProvider(p: ProviderConfig) {
  Object.assign(providerForm, {
    id: p.id,
    name: p.name,
    website: p.website || '',
    base_url: p.base_url || '',
    is_full_url: p.is_full_url || false,
    api_key: '', // 编辑时留空 = 不修改（后端只写不读，无法回显明文）
    model: p.model || '',
  })
  providerDialogMode.value = 'edit'
  providerDialog.value = true
}

async function saveProvider() {
  providerNameError.value = providerForm.name.trim() ? '' : '请输入 Provider 名称'
  providerBaseUrlError.value = providerForm.base_url.trim() ? '' : '请输入请求地址'
  providerModelError.value = providerForm.model.trim() ? '' : '请输入模型名'
  if (providerNameError.value || providerBaseUrlError.value || providerModelError.value) {
    ElMessage.warning('请填写名称、请求地址和模型名')
    await nextTick()
    providerNameRef.value?.focus()
    return
  }
  providerSubmitting.value = true
  const body = {
    name: providerForm.name,
    website: providerForm.website || undefined,
    base_url: providerForm.base_url || undefined,
    is_full_url: providerForm.is_full_url,
    model: providerForm.model || undefined,
    ...(providerForm.api_key ? { api_key: providerForm.api_key } : {}), // 留空 = 不传（编辑不改 key）
  }
  try {
    const saved = providerDialogMode.value === 'create'
      ? await swallowNotImplemented(createProvider(body))
      : await swallowNotImplemented(updateProvider(providerForm.id, body))
    if (saved === undefined) return // 后端未实现 → 打标降级，不弹错
    providerDialog.value = false
    ElMessage.success(providerDialogMode.value === 'create' ? 'Provider 已保存' : 'Provider 已更新')
    await loadProviders()
  } finally {
    providerSubmitting.value = false
  }
}

async function onActivateProvider(p: ProviderConfig) {
  const activated = await swallowNotImplemented(activateProvider(p.id))
  if (activated === undefined) return
  ElMessage.success(`已切换为 ${activated.name}`)
  await loadProviders()
  await loadActiveProvider()
}

async function onDeleteProvider(id: string) {
  await ElMessageBox.confirm('删除该 Provider 配置？', '确认删除', { type: 'warning' })
  const ok = await swallowNotImplemented(deleteProvider(id))
  if (ok === undefined) return
  ElMessage.success('已删除')
  await loadProviders()
  await loadActiveProvider()
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">设置</h2>
        <p class="app-page-subtitle">{{ pageSubtitle }}</p>
      </div>
    </div>

    <div class="settings-tabs">
      <div class="settings-tag-row" role="tablist" aria-label="设置分区">
        <button
          type="button"
          id="settings-provider-tab"
          role="tab"
          data-tab="provider"
          aria-controls="settings-provider-panel"
          :aria-selected="activeTab === 'provider'"
          class="settings-tag"
          :class="{ active: activeTab === 'provider' }"
          @click="activeTab = 'provider'"
          @keydown="onTabKeydown"
        >
          Provider 配置
        </button>
        <button
          type="button"
          id="settings-sandbox-tab"
          role="tab"
          data-tab="sandbox"
          aria-controls="settings-sandbox-panel"
          :aria-selected="activeTab === 'sandbox'"
          class="settings-tag"
          :class="{ active: activeTab === 'sandbox' }"
          @click="activeTab = 'sandbox'"
          @keydown="onTabKeydown"
        >
          沙箱
        </button>
        <button
          type="button"
          id="settings-notifications-tab"
          role="tab"
          data-tab="notifications"
          aria-controls="settings-notifications-panel"
          :aria-selected="activeTab === 'notifications'"
          class="notif-tag"
          :class="{ active: activeTab === 'notifications' }"
          aria-label="通知"
          @click="activeTab = 'notifications'"
          @keydown="onTabKeydown"
        >
          <el-icon :size="14"><Bell /></el-icon><span>通知</span>
          <span v-if="unread > 0" class="notif-tag-badge">{{ unread > 99 ? '99+' : unread }}</span>
        </button>
        <button
          type="button"
          id="settings-theme-tab"
          role="tab"
          data-tab="theme"
          aria-controls="settings-theme-panel"
          :aria-selected="activeTab === 'theme'"
          class="theme-tag"
          :class="{ active: activeTab === 'theme' }"
          title="主题配色"
          @click="activeTab = 'theme'"
          @keydown="onTabKeydown"
        >
          <span class="theme-tag-dot" :style="{ background: currentPrimary }" /><span>主题</span>
        </button>
      </div>

      <Transition name="settings-pane" mode="out-in">
        <div v-if="activeTab === 'provider'" id="settings-provider-panel" key="provider" class="settings-pane" role="tabpanel" aria-labelledby="settings-provider-tab">
          <template v-if="!providersUnavailable">
            <div class="users-toolbar">
              <span v-if="activeProvider" class="active-hint">
                当前生效：<b>{{ activeProvider.name }}</b> · {{ activeProvider.model }}
              </span>
              <el-button type="primary" :icon="'Plus'" @click="openAddProvider">添加 Provider</el-button>
            </div>
            <AsyncState
              :status="providersUnavailable ? 'unavailable' : providerStatus"
              :error-message="providerErrorMessage"
              empty-text="暂无 Provider 配置"
              empty-action-text="添加 Provider"
              @retry="retryProviders"
              @action="openAddProvider"
            >
              <div class="app-table-wrap">
                <el-table :data="providers" size="small">
              <el-table-column label="别名" width="160">
                <template #default="{ row }">
                  <span>{{ row.name }}</span>
                  <el-tag v-if="row.enabled" size="small" type="success" class="active-tag">当前</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="model" label="模型" width="150" show-overflow-tooltip />
              <el-table-column label="请求地址" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.base_url }}{{ row.is_full_url ? '' : ' …/chat/completions' }}
                </template>
              </el-table-column>
              <el-table-column label="官网" width="140" show-overflow-tooltip>
                <template #default="{ row }">
                  <a v-if="row.website" :href="row.website" target="_blank" rel="noopener">{{ row.website }}</a>
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="API Key" width="90">
                <template #default="{ row }">{{ row.has_key ? '已配置' : '未配置' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="170">
                <template #default="{ row }">
                  <el-button v-if="!row.enabled" size="small" text type="primary" @click="onActivateProvider(row)">
                    设为当前
                  </el-button>
                  <el-button size="small" text @click="openEditProvider(row)">编辑</el-button>
                  <el-button size="small" text type="danger" @click="onDeleteProvider(row.id)">删除</el-button>
                </template>
              </el-table-column>
                </el-table>
              </div>
            </AsyncState>
          </template>
          <EmptyState v-else text="后端暂未实现 Provider 配置接口（契约已发交接板）" />
        </div>
        <div v-else-if="activeTab === 'sandbox'" id="settings-sandbox-panel" key="sandbox" class="settings-pane" role="tabpanel" aria-labelledby="settings-sandbox-tab">
          <AsyncState :status="sandboxLoading ? 'loading' : (sandboxError ? 'error' : 'success')" :error-message="sandboxError" @retry="loadSandboxSettings">
            <div class="sandbox-mode-grid">
              <button
                v-for="item in sandboxModes"
                :key="item.id"
                type="button"
                class="sandbox-mode-card"
                :class="{ active: sandboxSettings?.mode === item.id, unavailable: !sandboxSettings?.backends[item.id]?.available }"
                :disabled="sandboxSaving || !sandboxSettings?.backends[item.id]?.available"
                @click="selectSandboxMode(item.id)"
              >
                <span class="sandbox-mode-title">{{ item.title }}</span>
                <span class="sandbox-mode-detail">{{ item.detail }}</span>
                <span class="sandbox-mode-status">
                  {{ sandboxSettings?.backends[item.id]?.available ? '可用' : (sandboxSettings?.backends[item.id]?.detail || '不可用') }}
                </span>
              </button>
            </div>
            <p v-if="sandboxSettings" class="sandbox-review-hint">
              独立命令审查：{{ sandboxSettings.review.enabled ? (sandboxSettings.review.configured ? '已启用' : '未配置，使用规则降级') : '已关闭' }}。
              依赖安装和远程脚本会额外请求人工确认。
            </p>
          </AsyncState>
        </div>
        <div v-else-if="activeTab === 'notifications'" id="settings-notifications-panel" key="notifications" role="tabpanel" aria-labelledby="settings-notifications-tab">
          <NotificationPane />
        </div>
        <div v-else id="settings-theme-panel" key="theme" role="tabpanel" aria-labelledby="settings-theme-tab">
          <ThemePane v-model="themeId" />
        </div>
      </Transition>
    </div>

    <!-- 添加/编辑 Provider -->
    <ResponsiveDialog
      :model-value="providerDialog"
      :title="providerDialogMode === 'create' ? '添加 Provider' : '编辑 Provider'"
      width="500px"
      @close="providerDialog = false"
    >
      <el-form label-width="100px">
        <el-form-item label="名称（别名）" required :error="providerNameError">
          <el-input ref="providerNameRef" v-model="providerForm.name" placeholder="如：我的 DeepSeek / 公司内网代理" @input="providerNameError = ''" />
        </el-form-item>
        <el-form-item label="官网链接">
          <el-input v-model="providerForm.website" placeholder="https://platform.deepseek.com（可选，仅展示）" />
        </el-form-item>
        <el-form-item label="请求地址" required :error="providerBaseUrlError">
          <el-input
            v-model="providerForm.base_url"
            placeholder="https://api.deepseek.com 或 https://api.openai.com/v1"
            @input="providerBaseUrlError = ''"
          />
        </el-form-item>
        <el-form-item label="完整 URL">
          <el-switch v-model="providerForm.is_full_url" />
          <span class="url-hint">
            {{
              providerForm.base_url
                ? (providerForm.is_full_url
                  ? '已填写完整请求地址（含 /chat/completions）'
                  : '自动拼接 → ' + providerForm.base_url.replace(/\/+$/, '') + '/chat/completions')
                : '关闭 = 自动拼接 /chat/completions'
            }}
          </span>
        </el-form-item>
        <el-form-item label="模型名" required :error="providerModelError">
          <el-input v-model="providerForm.model" placeholder="裸名，如 gpt-4o / deepseek-chat" @input="providerModelError = ''" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="providerForm.api_key"
            type="password"
            show-password
            :placeholder="providerDialogMode === 'edit' ? '留空 = 不修改' : '凭证只写不读，不回传'"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialog = false">取消</el-button>
        <el-button type="primary" :loading="providerSubmitting" :disabled="providerSubmitting" @click="saveProvider">保存</el-button>
      </template>
    </ResponsiveDialog>
  </div>
</template>

<style scoped>
.users-toolbar {
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.active-hint {
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-sm);
}
.active-tag {
  margin-left: 6px;
}
.muted {
  color: var(--app-text-disabled, #bbb);
}
.url-hint {
  margin-left: 8px;
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-xs, 12px);
}
.settings-tabs {
  background: var(--app-content-bg);
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-card);
  padding: 4px 16px 16px;
}
.settings-tag-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--app-border-light);
  margin-bottom: 16px;
  flex-wrap: wrap;
}
/* 统一 tag（Provider/通知/主题）：hover 主色 + active 高亮 + 按压反馈 */
.settings-tag,
.notif-tag,
.theme-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: var(--app-radius);
  border: 1px solid var(--app-border-light);
  background: var(--app-content-bg);
  font-size: var(--app-font-size-sm);
  font-family: inherit;
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s var(--ease-out), color 0.2s var(--ease-out), transform 160ms var(--ease-out);
}
.settings-tag:hover,
.notif-tag:hover,
.theme-tag:hover {
  border-color: var(--app-primary);
  color: var(--app-primary);
}
.settings-tag.active,
.notif-tag.active,
.theme-tag.active {
  border-color: var(--app-primary);
  color: var(--app-primary);
  background: var(--app-bg);
}
.settings-tag:active,
.notif-tag:active,
.theme-tag:active {
  transform: scale(0.97);
}
.notif-tag-badge {
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: 8px;
  background: var(--app-danger);
  color: #fff;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}
.theme-tag-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1px solid var(--app-border-light);
  flex-shrink: 0;
}
.sandbox-mode-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.sandbox-mode-card {
  display: flex;
  min-height: 132px;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  background: var(--app-content-bg);
  color: var(--app-text-primary);
  text-align: left;
  cursor: pointer;
}
.sandbox-mode-card.active {
  border-color: var(--app-primary);
  box-shadow: 0 0 0 1px var(--app-primary);
}
.sandbox-mode-card.unavailable {
  opacity: 0.55;
  cursor: not-allowed;
}
.sandbox-mode-title { font-weight: 600; }
.sandbox-mode-detail,
.sandbox-mode-status,
.sandbox-review-hint { color: var(--app-text-secondary); font-size: var(--app-font-size-sm); }
@media (max-width: 768px) {
  .sandbox-mode-grid { grid-template-columns: 1fr; }
}
/* pane 切换过渡（emil：leave 快 60ms、enter 140ms，总 <300ms） */
.settings-pane-enter-active {
  transition: opacity 140ms var(--ease-out), transform 140ms var(--ease-out);
}
.settings-pane-leave-active {
  transition: opacity 60ms ease;
}
.settings-pane-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.settings-pane-leave-to {
  opacity: 0;
}
@media (max-width: 768px) {
  .settings-tabs {
    padding-inline: 10px;
  }
  .settings-tag-row {
    gap: 6px;
  }
  .settings-tag,
  .notif-tag,
  .theme-tag {
    min-height: var(--app-control-touch);
    padding-inline: 10px;
  }
  .users-toolbar {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
  .users-toolbar :deep(.el-button) {
    width: 100%;
  }
}
</style>

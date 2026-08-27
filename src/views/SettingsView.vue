<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listProviders, createProvider, updateProvider, deleteProvider, activateProvider, getActiveProvider } from '@/api/provider'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import EmptyState from '@/components/common/EmptyState.vue'
import { useNotifications } from '@/composables/useNotifications'
import { useSSE } from '@/composables/useSSE'
import { THEMES, getStoredTheme } from '@/theme/themes'
import NotificationPane from '@/components/layout/NotificationPane.vue'
import ThemePane from '@/components/layout/ThemePane.vue'
import type { ProviderConfig } from '@/types'

/** 设置（docs/02 §4 / docs/03 §5.1）：单用户本地模式 → Provider 配置 / 通知 / 主题 三个 pane（tag 切换，非悬浮窗） */

/* ---------- 设置组切换 ---------- */
const activeTab = ref<'provider' | 'notifications' | 'theme'>('provider')
const pageSubtitle = computed(
  () => ({ provider: 'Provider 配置', notifications: '通知', theme: '主题配色' })[activeTab.value],
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
const providerLoading = ref(false)

onMounted(() => {
  void loadProviders()
  void loadActiveProvider()
  void loadNotifications()
  if (!isUnavailable(FEATURE.notifications)) sse.connect()
})
onBeforeUnmount(() => sse.disconnect())

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

async function loadActiveProvider() {
  const active = await swallowNotImplemented(getActiveProvider())
  if (active !== undefined) activeProvider.value = active
}

function resetProviderForm() {
  Object.assign(providerForm, {
    id: '', name: '', website: '', base_url: '', is_full_url: false, api_key: '', model: '',
  })
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
  const body = {
    name: providerForm.name,
    website: providerForm.website || undefined,
    base_url: providerForm.base_url || undefined,
    is_full_url: providerForm.is_full_url,
    model: providerForm.model || undefined,
    ...(providerForm.api_key ? { api_key: providerForm.api_key } : {}), // 留空 = 不传（编辑不改 key）
  }
  const saved = providerDialogMode.value === 'create'
    ? await swallowNotImplemented(createProvider(body))
    : await swallowNotImplemented(updateProvider(providerForm.id, body))
  if (saved === undefined) return // 后端未实现 → 打标降级，不弹错
  providerDialog.value = false
  ElMessage.success(providerDialogMode.value === 'create' ? 'Provider 已保存' : 'Provider 已更新')
  await loadProviders()
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
      <div class="settings-tag-row">
        <button
          type="button"
          class="settings-tag"
          :class="{ active: activeTab === 'provider' }"
          @click="activeTab = 'provider'"
        >
          Provider 配置
        </button>
        <button
          type="button"
          class="notif-tag"
          :class="{ active: activeTab === 'notifications' }"
          aria-label="通知"
          @click="activeTab = 'notifications'"
        >
          <el-icon :size="14"><Bell /></el-icon><span>通知</span>
          <span v-if="unread > 0" class="notif-tag-badge">{{ unread > 99 ? '99+' : unread }}</span>
        </button>
        <button
          type="button"
          class="theme-tag"
          :class="{ active: activeTab === 'theme' }"
          title="主题配色"
          @click="activeTab = 'theme'"
        >
          <span class="theme-tag-dot" :style="{ background: currentPrimary }" /><span>主题</span>
        </button>
      </div>

      <Transition name="settings-pane" mode="out-in">
        <div v-if="activeTab === 'provider'" key="provider" class="settings-pane">
          <template v-if="!providersUnavailable">
            <div class="users-toolbar">
              <span v-if="activeProvider" class="active-hint">
                当前生效：<b>{{ activeProvider.name }}</b> · {{ activeProvider.model }}
              </span>
              <el-button type="primary" :icon="'Plus'" @click="openAddProvider">添加 Provider</el-button>
            </div>
            <el-table :data="providers" v-loading="providerLoading" size="small">
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
          </template>
          <EmptyState v-else text="后端暂未实现 Provider 配置接口（契约已发交接板）" />
        </div>
        <NotificationPane v-else-if="activeTab === 'notifications'" key="notifications" />
        <ThemePane v-else key="theme" v-model="themeId" />
      </Transition>
    </div>

    <!-- 添加/编辑 Provider -->
    <el-dialog
      :model-value="providerDialog"
      :title="providerDialogMode === 'create' ? '添加 Provider' : '编辑 Provider'"
      width="500px"
      @close="providerDialog = false"
    >
      <el-form label-width="100px">
        <el-form-item label="名称（别名）" required>
          <el-input v-model="providerForm.name" placeholder="如：我的 DeepSeek / 公司内网代理" />
        </el-form-item>
        <el-form-item label="官网链接">
          <el-input v-model="providerForm.website" placeholder="https://platform.deepseek.com（可选，仅展示）" />
        </el-form-item>
        <el-form-item label="请求地址">
          <el-input
            v-model="providerForm.base_url"
            placeholder="https://api.deepseek.com 或 https://api.openai.com/v1"
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
        <el-form-item label="模型名">
          <el-input v-model="providerForm.model" placeholder="裸名，如 gpt-4o / deepseek-chat" />
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
        <el-button type="primary" @click="saveProvider">保存</el-button>
      </template>
    </el-dialog>
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
</style>

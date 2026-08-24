<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listProviders, createProvider, updateProvider, deleteProvider } from '@/api/provider'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import EmptyState from '@/components/common/EmptyState.vue'
import NotificationBell from '@/components/layout/NotificationBell.vue'
import ThemeSwitcher from '@/components/layout/ThemeSwitcher.vue'
import type { ProviderConfig } from '@/types'

/** 设置（docs/02 §4 / docs/03 §5.1）：单用户本地模式 → Provider 配置 */

/* ---------- Provider 配置（契约见 api/provider.ts，后端未实现走降级） ---------- */
const providers = ref<ProviderConfig[]>([])
const providersUnavailable = computed(() => isUnavailable(FEATURE.providers))
const providerDialog = ref(false)
const providerForm = reactive({ name: 'openai', base_url: '', api_key: '', model: '' })
const providerLoading = ref(false)

onMounted(() => {
  void loadProviders()
})

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
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">设置</h2>
        <p class="app-page-subtitle">Provider 配置</p>
      </div>
    </div>

    <div class="settings-tabs">
      <div class="settings-tag-row">
        <span class="settings-tag active">Provider 配置</span>
        <NotificationBell />
        <ThemeSwitcher />
      </div>

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
    </div>

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
  </div>
</template>

<style scoped>
.users-toolbar {
  margin-bottom: 8px;
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
.settings-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: var(--app-radius);
  border: 1px solid var(--app-border-light);
  background: var(--app-content-bg);
  font-size: var(--app-font-size-sm);
  color: var(--app-text-secondary);
}
.settings-tag.active {
  border-color: var(--app-primary);
  color: var(--app-primary);
  background: var(--app-bg);
}
</style>

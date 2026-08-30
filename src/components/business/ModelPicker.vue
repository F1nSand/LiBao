<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { activateProvider, getActiveProvider, listProviders } from '@/api/provider'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { ProviderConfig } from '@/types'

const providers = ref<ProviderConfig[]>([])
const activeProvider = ref<ProviderConfig | null>(null)
const menuVisible = ref(false)
const activeLoading = ref(true)
const listLoading = ref(false)
const switching = ref(false)
const activeError = ref('')
const listError = ref('')
const providersLoaded = ref(false)
let activeRequestVersion = 0
let activationVersion = 0

const unavailable = computed(() => isUnavailable(FEATURE.providers))
const activeModelLabel = computed(() => {
  if (activeLoading.value) return '加载中…'
  if (activeError.value) return '重试模型'
  if (!activeProvider.value) return '未配置'
  return activeProvider.value.model || activeProvider.value.name
})

async function loadActiveProvider(): Promise<void> {
  const requestVersion = ++activeRequestVersion
  const activationAtStart = activationVersion
  activeLoading.value = true
  activeError.value = ''
  try {
    const active = await swallowNotImplemented(getActiveProvider())
    if (requestVersion !== activeRequestVersion || activationAtStart !== activationVersion) return
    if (active !== undefined) activeProvider.value = active
  } catch (error) {
    if (requestVersion === activeRequestVersion && activationAtStart === activationVersion) {
      activeError.value = error instanceof Error ? error.message : '模型加载失败'
    }
  } finally {
    if (requestVersion === activeRequestVersion) activeLoading.value = false
  }
}

async function loadProviders(): Promise<void> {
  if (providersLoaded.value || listLoading.value) return
  listLoading.value = true
  listError.value = ''
  try {
    const list = await swallowNotImplemented(listProviders())
    if (list !== undefined) {
      providers.value = list
      providersLoaded.value = true
    }
  } catch (error) {
    listError.value = error instanceof Error ? error.message : 'Provider 列表加载失败'
  } finally {
    listLoading.value = false
  }
}

async function onMenuShow(): Promise<void> {
  if (!unavailable.value) await loadProviders()
}

async function retryActive(): Promise<void> {
  if (!activeLoading.value) await loadActiveProvider()
}

async function retryProviders(): Promise<void> {
  providersLoaded.value = false
  await loadProviders()
}

async function pickProvider(provider: ProviderConfig): Promise<void> {
  if (provider.enabled || switching.value) return
  const requestVersion = ++activationVersion
  switching.value = true
  try {
    const activated = await swallowNotImplemented(activateProvider(provider.id))
    if (requestVersion !== activationVersion || activated === undefined) return
    activeProvider.value = activated
    activeError.value = ''
    providers.value = providers.value.map((item) => ({ ...item, enabled: item.id === activated.id }))
    menuVisible.value = false
    ElMessage.success(`已切换模型：${activated.model || activated.name}`)
  } catch (error) {
    if (requestVersion === activationVersion) ElMessage.error(error instanceof Error ? error.message : '模型切换失败，请重试')
  } finally {
    if (requestVersion === activationVersion) switching.value = false
  }
}

onMounted(() => {
  void loadActiveProvider()
})
</script>

<template>
  <el-popover
    v-if="!unavailable"
    v-model:visible="menuVisible"
    placement="top-start"
    :width="300"
    trigger="click"
    popper-class="model-picker"
    @show="onMenuShow"
  >
    <template #reference>
      <el-button class="model-btn" :icon="'Cpu'" aria-label="选择模型">
        <span class="model-btn-label">{{ activeModelLabel }}</span>
      </el-button>
    </template>
    <div v-loading="switching || activeLoading || listLoading" class="model-menu">
      <div v-if="activeError" class="model-menu-error" role="alert">
        <span>{{ activeError }}</span>
        <button type="button" class="model-retry" @click="retryActive">重试</button>
      </div>
      <div v-else-if="activeProvider" class="model-menu-hint">
        当前：{{ activeProvider.name }} · {{ activeProvider.model || '（未填模型名）' }}
      </div>
      <div v-else class="model-menu-hint">尚未配置 Provider（到 设置 → Provider 配置 添加）</div>
      <button
        v-for="provider in providers"
        :key="provider.id"
        type="button"
        class="model-item"
        :class="{ active: provider.enabled }"
        :disabled="switching"
        @click="pickProvider(provider)"
      >
        <span class="model-item-name">{{ provider.name }}</span>
        <span class="model-item-model">{{ provider.model }}</span>
        <el-tag v-if="provider.enabled" size="small" type="success">当前</el-tag>
      </button>
      <div v-if="listError" class="model-menu-error" role="alert">
        <span>{{ listError }}</span>
        <button type="button" class="model-retry" @click="retryProviders">重试列表</button>
      </div>
      <div v-else-if="!providers.length && !switching && !listLoading" class="model-menu-empty">暂无 Provider 配置</div>
    </div>
  </el-popover>
</template>

<style scoped>
.model-btn { color: var(--app-text-secondary); }
.model-btn-label {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 480px) {
  .model-btn-label { display: none; }
}
</style>

<style>
.model-picker .model-menu { min-height: 48px; }
.model-picker .model-menu-hint,
.model-picker .model-menu-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--app-border-light);
  color: var(--app-text-muted);
  font-size: 12px;
}
.model-picker .model-menu-error { color: var(--app-danger, #dc2626); }
.model-picker .model-retry {
  flex-shrink: 0;
  padding: 2px 6px;
  border: 1px solid currentColor;
  border-radius: var(--app-radius, 6px);
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.model-picker .model-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 36px;
  padding: 8px 10px;
  border: none;
  border-radius: var(--app-radius, 6px);
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  transition: background 0.15s;
}
.model-picker .model-item:hover:not(.active) { background: var(--app-border-light); }
.model-picker .model-item.active { cursor: default; background: color-mix(in srgb, var(--app-primary) 8%, transparent); }
.model-picker .model-item-name { font-weight: 600; color: var(--app-text-main); }
.model-picker .model-item-model {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-secondary);
}
.model-picker .model-menu-empty { padding: 12px 4px; text-align: center; color: var(--app-text-muted); font-size: 12px; }
@media (max-width: 480px) { .model-picker { max-width: calc(100vw - 24px) !important; } }
</style>

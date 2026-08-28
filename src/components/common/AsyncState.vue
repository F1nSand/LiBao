<script setup lang="ts">
import EmptyState from './EmptyState.vue'

export type AsyncStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error' | 'unavailable'

const props = withDefaults(
  defineProps<{
    status: AsyncStatus
    errorMessage?: string | null
    emptyText?: string
    unavailableText?: string
    loadingText?: string
    retryText?: string
  }>(),
  {
    errorMessage: null,
    emptyText: '暂无数据',
    unavailableText: '当前功能暂不可用',
    loadingText: '正在加载…',
    retryText: '重试',
  },
)

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="async-state">
    <div v-if="props.status === 'loading'" class="async-loading" role="status" aria-live="polite">
      <span class="async-spinner" aria-hidden="true" />
      <span>{{ props.loadingText }}</span>
    </div>
    <div v-else-if="props.status === 'error'" class="async-error" role="alert">
      <span>{{ props.errorMessage || '加载失败，请重试' }}</span>
      <el-button size="small" @click="emit('retry')">{{ props.retryText }}</el-button>
    </div>
    <EmptyState v-else-if="props.status === 'success-empty'" :text="props.emptyText" />
    <EmptyState v-else-if="props.status === 'unavailable'" :text="props.unavailableText" />
    <slot v-else />
  </div>
</template>

<style scoped>
.async-state {
  min-height: 72px;
  width: 100%;
}
.async-loading,
.async-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 96px;
  padding: 16px;
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-sm);
}
.async-error {
  flex-direction: column;
  color: var(--app-danger);
}
.async-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--app-border);
  border-top-color: var(--app-primary-fill);
  border-radius: 50%;
  animation: async-spin 0.8s linear infinite;
}
@keyframes async-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .async-spinner {
    animation: none;
  }
}
</style>

<script setup lang="ts">
defineProps<{ operationId: string }>()
const emit = defineEmits<{ undo: [] }>()
</script>

<template>
  <div class="rollback-undo-banner" role="status">
    <span>本次回滚已完成</span>
    <button type="button" @click="emit('undo')">撤销本次回滚</button>
  </div>
</template>

<style scoped>
.rollback-undo-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 16px;
  border-top: 1px solid color-mix(in srgb, var(--app-primary) 24%, var(--app-border));
  background: color-mix(in srgb, var(--app-primary) 6%, var(--app-content-bg));
  color: var(--app-text-secondary);
  font-size: 12px;
}
.rollback-undo-banner button {
  min-height: var(--app-control-sm);
  padding: 3px 10px;
  border: 1px solid var(--app-primary-fill);
  border-radius: var(--app-radius);
  background: transparent;
  color: var(--app-primary);
  cursor: pointer;
}
@media (max-width: 480px) { .rollback-undo-banner { padding: 7px 10px; } }
</style>

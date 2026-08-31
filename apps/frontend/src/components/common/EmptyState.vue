<script setup lang="ts">
const props = defineProps<{ text?: string; actionText?: string }>()
const emit = defineEmits<{ action: [] }>()
</script>

<template>
  <div class="empty-state" role="status">
    <el-icon :size="36" class="empty-icon"><Box /></el-icon>
    <p class="empty-text">{{ text ?? '暂无数据' }}</p>
    <el-button v-if="props.actionText" class="empty-action" size="small" @click="emit('action')">
      {{ props.actionText }}
    </el-button>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  color: var(--app-text-muted);
}
.empty-icon {
  margin-bottom: 8px;
}
.empty-text {
  margin: 0;
  font-size: var(--app-font-size-sm);
}
.empty-action {
  margin-top: 12px;
}
</style>

<script setup lang="ts">
defineProps<{ text?: string }>()
</script>

<template>
  <div class="empty-state">
    <el-icon :size="36" class="empty-icon"><Box /></el-icon>
    <p class="empty-text">{{ text ?? '暂无数据' }}</p>
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
</style>

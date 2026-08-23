<script setup lang="ts">
defineProps<{ active?: boolean }>()
</script>

<template>
  <div v-if="active" class="stream-skeleton" aria-hidden="true">
    <span class="bar" />
    <span class="bar" />
    <span class="bar short" />
  </div>
</template>

<style scoped>
.stream-skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 4px;
}
.bar {
  height: 12px;
  border-radius: var(--app-radius);
  background: linear-gradient(90deg, #ececfd 25%, #f4f4fe 50%, #ececfd 75%);
  background-size: 200% 100%;
  animation: breathe 1.4s ease-in-out infinite;
  width: 100%;
}
.bar.short {
  width: 60%;
}
@keyframes breathe {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>

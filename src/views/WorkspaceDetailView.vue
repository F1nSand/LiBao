<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import WorkspaceShell from '@/components/workspace/WorkspaceShell.vue'

/** 工作区内部页（M7-B，docs/02 §4）：WorkspaceShell = 左列（文件树 + 会话）+ 右对话区 */
const route = useRoute()
const workspaceId = computed(() => String(route.params.id ?? ''))
</script>

<template>
  <div class="workspace-detail">
    <WorkspaceShell :workspace-id="workspaceId" />
  </div>
</template>

<style scoped>
.workspace-detail {
  height: 100%;
  min-height: 0;
}
</style>

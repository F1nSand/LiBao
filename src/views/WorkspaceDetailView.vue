<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import ResourceManager from '@/components/workspace/ResourceManager.vue'
import WorkspaceChatPanel from '@/components/workspace/WorkspaceChatPanel.vue'

/** 工作区内部页（M7-B，docs/02 §4）：左文件树资源管理器 + 右工作区对话（会话/轨迹 + 引用文件） */
const route = useRoute()
const workspaceId = computed(() => String(route.params.id ?? ''))
</script>

<template>
  <div class="workspace-detail">
    <ResourceManager :workspace-id="workspaceId" class="ws-resource" />
    <WorkspaceChatPanel :workspace-id="workspaceId" class="ws-chat" />
  </div>
</template>

<style scoped>
.workspace-detail {
  display: flex;
  height: 100%;
  min-height: 0;
}
.ws-resource {
  width: 260px;
  flex-shrink: 0;
  border-right: 1px solid var(--app-border);
  background: var(--app-content-bg);
}
.ws-chat {
  flex: 1;
  min-width: 0;
}
</style>

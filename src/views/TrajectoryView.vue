<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getConversation } from '@/api/chat'
import TrajectoryPanel from '@/components/trajectory/TrajectoryPanel.vue'

/** 对话轨迹页（docs/02 §6.3）：独立页 = 返回/标题 + TrajectoryPanel（内嵌/独立共用） */
const route = useRoute()
const router = useRouter()

const conversationId = computed(() => route.params.conversationId as string)
const conversationTitle = ref('')

watch(
  conversationId,
  async (id) => {
    conversationTitle.value = ''
    if (!id) return
    try {
      const c = await getConversation(id)
      conversationTitle.value = c.title ?? ''
    } catch {
      /* 标题获取失败不阻塞轨迹展示 */
    }
  },
  { immediate: true },
)

function goBack() {
  router.push('/chat')
}
</script>

<template>
  <div class="app-page tj-page">
    <div class="tj-toolbar">
      <el-button size="small" :icon="'ArrowLeft'" @click="goBack">返回对话</el-button>
      <span class="tj-title">对话轨迹</span>
      <span class="tj-conv mono">{{ conversationTitle || conversationId }}</span>
    </div>
    <TrajectoryPanel
      :conversation-id="conversationId"
      :focus-tool-call-id="(route.query.focus as string)"
    />
  </div>
</template>

<style scoped>
.tj-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  height: 100%;
  min-height: 0;
}
.tj-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.tj-title {
  font-size: 14px;
  font-weight: 600;
}
.tj-conv {
  color: var(--app-text-muted);
  font-size: 12px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mono {
  font-family: var(--app-font-mono);
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'

/** 会话列表（docs/02 §6.2）：并入主侧边栏「对话」下方；深色样式、自包含 store/router */
const chat = useChatStore()
const router = useRouter()

onMounted(() => {
  void chat.loadConversations()
})

const keyword = ref('')
const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return chat.conversations
  return chat.conversations.filter((c) => c.title.toLowerCase().includes(k))
})

async function onSelect(id: string) {
  await chat.selectConversation(id)
  if (router.currentRoute.value.path !== '/chat') void router.push('/chat')
}

async function onCreate() {
  await chat.createConversation('新会话')
  if (router.currentRoute.value.path !== '/chat') void router.push('/chat')
}

async function onDelete(id: string) {
  await chat.deleteConversation(id)
}
</script>

<template>
  <div class="conv-list">
    <div class="conv-head">
      <span class="conv-title">会话</span>
      <el-button size="small" :icon="'Plus'" circle class="conv-add" title="新建会话" @click="onCreate" />
    </div>

    <el-input
      v-model="keyword"
      size="small"
      placeholder="搜索会话…"
      clearable
      :prefix-icon="'Search'"
      class="conv-search"
    />

    <div class="conv-items">
      <div
        v-for="c in filtered"
        :key="c.id"
        class="conv-item"
        :class="{ active: c.id === chat.currentId }"
        @click="onSelect(c.id)"
      >
        <span class="conv-item-title">{{ c.title || '新会话' }}</span>
        <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'del' && onDelete(c.id)">
          <span class="conv-item-more" @click.stop><el-icon><MoreFilled /></el-icon></span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="del" divided>删除</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div v-if="filtered.length === 0" class="conv-empty">暂无会话</div>
    </div>
  </div>
</template>

<style scoped>
.conv-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--app-sidebar-conv-bg);
  border: 1px solid var(--app-sidebar-border);
  border-radius: var(--app-radius-lg);
  margin: 0 8px 8px;
  overflow: hidden;
}
.conv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px 4px;
}
.conv-title {
  font-weight: 600;
  color: var(--app-sidebar-text);
  font-size: 12px;
}
.conv-search {
  padding: 0 8px 6px;
}
.conv-search :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.06);
  box-shadow: none;
  border-radius: var(--app-radius);
}
.conv-search :deep(.el-input__inner) {
  color: var(--app-sidebar-text-active);
}
.conv-search :deep(.el-input__inner::placeholder) {
  color: var(--app-sidebar-text);
}
.conv-items {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: none; /* 主侧边栏滚轮条隐藏（现代应用惯例），不显示明显灰条 */
  padding: 4px 6px;
}
.conv-items::-webkit-scrollbar {
  display: none;
}
.conv-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 12px;
  border-radius: var(--app-radius);
  cursor: pointer;
  margin-bottom: 2px;
  font-size: 13px;
  color: var(--app-sidebar-text);
}
.conv-item:hover {
  background: var(--app-sidebar-item-hover);
  color: var(--app-sidebar-text-active);
}
.conv-item.active {
  background: var(--app-sidebar-item-active-bg);
  color: var(--app-sidebar-text-active);
}
.conv-item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-item-more {
  color: var(--app-sidebar-text);
  display: flex;
  padding: 2px;
  border-radius: var(--app-radius-sm);
  opacity: 0.6;
}
.conv-item:hover .conv-item-more {
  opacity: 1;
  background: var(--app-sidebar-item-hover);
}
.conv-empty {
  text-align: center;
  color: var(--app-sidebar-text);
  font-size: 12px;
  padding: 16px 0;
}
</style>

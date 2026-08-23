<script setup lang="ts">
import type { Conversation } from '@/types'

/** 工作区会话列表（M7-B）：展示 + select/create/delete 事件；状态由 WorkspaceChatPanel 持有、api 直调 */
defineProps<{ items: Conversation[]; activeId: string | null; loading?: boolean; collapsed: boolean }>()
const emit = defineEmits<{
  select: [id: string]
  create: []
  delete: [id: string]
  toggle: []
}>()
</script>

<template>
  <div class="ws-conv-list">
    <div v-show="!collapsed" class="ws-conv-head">
      <div class="ws-conv-head-left">
        <el-button text class="ws-conv-toggle" title="折叠侧边栏" :icon="'PanelLeftClose'" @click="emit('toggle')" />
        <span class="ws-conv-title">会话</span>
      </div>
      <el-button size="small" :icon="'Plus'" circle class="ws-conv-add" title="新建工作区会话" @click="emit('create')" />
    </div>
    <div v-show="!collapsed" class="ws-conv-items">
      <div
        v-for="c in items"
        :key="c.id"
        class="ws-conv-item"
        :class="{ active: c.id === activeId }"
        @click="emit('select', c.id)"
      >
        <span class="ws-conv-item-title">{{ c.title || '新会话' }}</span>
        <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'del' && emit('delete', c.id)">
          <span class="ws-conv-item-more" @click.stop><el-icon><MoreFilled /></el-icon></span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="del" divided>删除</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div v-if="!loading && items.length === 0" class="ws-conv-empty">暂无会话，点 + 新建</div>
    </div>
  </div>
</template>

<style scoped>
.ws-conv-list {
  display: flex;
  flex-direction: column;
  min-height: 0;
  width: 100%;
  overflow: hidden;
  flex-shrink: 0;
}
.ws-conv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 6px;
}
.ws-conv-head-left {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.ws-conv-toggle {
  padding: 4px;
  color: var(--app-text-muted);
}
.ws-conv-toggle:hover {
  color: var(--app-primary);
}
.ws-conv-title {
  font-weight: 600;
  color: var(--app-text-main);
  font-size: 12px;
  white-space: nowrap;
}
.ws-conv-items {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px;
}
.ws-conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 12px;
  border-radius: var(--app-radius);
  cursor: pointer;
  margin-bottom: 2px;
  font-size: 13px;
  color: var(--app-text-main);
}
.ws-conv-item:hover {
  background: var(--app-bg);
}
.ws-conv-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--app-primary);
  font-weight: 500;
}
.ws-conv-item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ws-conv-item-more {
  color: var(--app-text-muted);
  display: flex;
  opacity: 0.6;
}
.ws-conv-item:hover .ws-conv-item-more {
  opacity: 1;
}
.ws-conv-empty {
  text-align: center;
  color: var(--app-text-muted);
  font-size: 12px;
  padding: 16px 0;
}
</style>

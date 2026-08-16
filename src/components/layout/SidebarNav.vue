<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { isSettingsRoute, menuItems, type MenuItem } from '@/router/routes'
import { canAccess } from '@/router/guard'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { NARROW_LAYOUT_MQ } from '@/constants/layout'
import ConversationList from '@/components/business/ConversationList.vue'

/**
 * 工作台侧边栏（docs/02 §4.1）：顶部 logo+折叠 → 对话 → 会话列表区 → 知识库/设置。
 * 设置按钮弹气泡卡片（设置/任务/工具/记忆/系统），点击跳转。
 */
const route = useRoute()
const auth = useAuthStore()
const userCollapsed = ref(false)
/** 设置气泡开关 */
const settingsOpen = ref(false)
const isNarrow = useMediaQuery(NARROW_LAYOUT_MQ)
/** 对话页窄屏不自动收起（会话列表在侧栏内需可用），其它页照常自动收起 */
const autoNarrow = computed(() => isNarrow.value && route.path !== '/chat')
const collapsed = computed(() => autoNarrow.value || userCollapsed.value)

function pick(path: string): MenuItem[] {
  const item = menuItems.find((i) => i.path === path)
  return item && canAccess({ requiresAuth: true, roles: item.roles }, auth.role) ? [item] : []
}

/** 顶部：对话 */
const topItems = computed(() => pick('/chat'))
/** 底部：知识库 */
const bottomItems = computed(() => pick('/kb'))
const settingsActive = computed(() => isSettingsRoute(route.path))
/** 设置气泡内容：设置组子项（按角色过滤） */
const settingsChildren = computed(() => {
  const s = menuItems.find((i) => i.path === '/settings')
  return (s?.children ?? []).filter((item) => canAccess({ requiresAuth: true, roles: item.roles }, auth.role))
})
</script>

<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-logo">
      <el-icon :size="20"><ChatDotRound /></el-icon>
      <span v-show="!collapsed" class="logo-text">Agent 工作台</span>
      <button
        v-if="!isNarrow || route.path === '/chat'"
        class="collapse-btn logo-collapse"
        type="button"
        :title="collapsed ? '展开' : '折叠'"
        @click="userCollapsed = !userCollapsed"
      >
        <el-icon><component :is="collapsed ? 'Expand' : 'Fold'" /></el-icon>
      </button>
    </div>

    <nav class="sidebar-nav sidebar-top">
      <router-link
        v-for="item in topItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: route.path === item.path }"
        :title="collapsed ? item.title : undefined"
      >
        <el-icon :size="18"><component :is="item.icon" /></el-icon>
        <span v-show="!collapsed" class="nav-text">{{ item.title }}</span>
      </router-link>
    </nav>

    <ConversationList v-show="!collapsed" class="sidebar-conv" />

    <nav class="sidebar-nav sidebar-bottom">
      <router-link
        v-for="item in bottomItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: route.path === item.path }"
        :title="collapsed ? item.title : undefined"
      >
        <el-icon :size="18"><component :is="item.icon" /></el-icon>
        <span v-show="!collapsed" class="nav-text">{{ item.title }}</span>
      </router-link>
      <el-popover v-model:visible="settingsOpen" trigger="click" placement="right-start" width="172" :show-arrow="false" popper-class="settings-popover">
        <template #reference>
          <button
            class="nav-item nav-item-btn settings-toggle"
            type="button"
            :class="{ active: settingsActive }"
            :title="collapsed ? '设置' : undefined"
          >
            <el-icon :size="18"><Setting /></el-icon>
            <span v-show="!collapsed" class="nav-text">设置</span>
          </button>
        </template>
        <div class="settings-popover-title">设置</div>
        <router-link
          v-for="item in settingsChildren"
          :key="item.path"
          :to="item.path"
          class="sub-item"
          :class="{ active: route.path === item.path }"
          @click="settingsOpen = false"
        >
          <el-icon :size="15"><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </router-link>
      </el-popover>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--app-sidebar-width);
  background: var(--app-sidebar-bg);
  border-right: 1px solid var(--app-sidebar-border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  overflow: hidden;
  flex-shrink: 0;
}
.sidebar.collapsed {
  width: 64px;
}
.sidebar-logo {
  height: var(--app-topbar-height);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  background: var(--app-sidebar-logo-bg);
  color: var(--app-sidebar-text-active);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}
.logo-collapse {
  margin-left: auto;
  width: 30px;
  height: 30px;
  padding: 0;
  flex-shrink: 0;
}
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 8px;
}
.sidebar-top {
  flex-shrink: 0;
}
.sidebar-conv {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.sidebar-bottom {
  flex-shrink: 0;
  border-top: 1px solid var(--app-sidebar-border);
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 12px;
  border-radius: var(--app-radius);
  color: var(--app-sidebar-text);
  text-decoration: none;
  white-space: nowrap;
  transition: background 0.15s;
}
.nav-item:hover {
  background: var(--app-sidebar-item-hover);
  color: var(--app-sidebar-text-active);
}
.nav-item.active {
  background: var(--app-sidebar-item-active-bg);
  color: var(--app-sidebar-text-active);
  font-weight: 500;
}
.nav-item-btn {
  width: 100%;
  font: inherit;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
}
.collapse-btn {
  display: flex;
  justify-content: center;
  align-items: center;
  background: transparent;
  border: none;
  color: var(--app-sidebar-text);
  cursor: pointer;
  border-radius: var(--app-radius);
}
.collapse-btn:hover {
  background: var(--app-sidebar-item-hover);
  color: var(--app-sidebar-text-active);
}
</style>

<!-- 设置气泡内容（el-popover 挂载到 body，需全局样式） -->
<style>
.settings-popover {
  padding: 4px;
}
.settings-popover-title {
  font-size: 11px;
  color: var(--app-text-muted);
  padding: 4px 8px 2px;
}
.settings-popover .sub-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: var(--app-radius);
  color: var(--app-text-main);
  text-decoration: none;
  font-size: 13px;
}
.settings-popover .sub-item:hover {
  background: var(--app-bg);
}
.settings-popover .sub-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--app-primary);
  font-weight: 500;
}
</style>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { isSettingsRoute, menuItems, type MenuItem } from '@/router/routes'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { MOBILE_LAYOUT_MQ, NARROW_LAYOUT_MQ } from '@/constants/layout'
import ConversationList from '@/components/business/ConversationList.vue'

/**
 * 工作台侧边栏（《02》前端设计 §4.1）：顶部 logo+折叠 → 工作区/对话 → 会话列表区 → 知识库/设置。
 * 设置按钮弹气泡卡片（设置/任务/工具/记忆/系统），点击跳转。
 */
const route = useRoute()
const userCollapsed = ref(false)
/** 设置气泡开关 */
const settingsOpen = ref(false)
const isNarrow = useMediaQuery(NARROW_LAYOUT_MQ)
const isMobile = useMediaQuery(MOBILE_LAYOUT_MQ)
const drawerOpen = ref(false)
const autoNarrow = computed(() => isNarrow.value && !isMobile.value)
const collapsed = computed(() => !isMobile.value && (autoNarrow.value || userCollapsed.value))
let returnFocus: HTMLElement | null = null

function openDrawer() {
  if (isMobile.value) {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    drawerOpen.value = true
  }
}

function closeDrawer() {
  const target = returnFocus
  drawerOpen.value = false
  returnFocus = null
  void nextTick(() => target?.focus())
}

defineExpose({ openDrawer, closeDrawer })

watch(
  () => route.fullPath,
  () => closeDrawer(),
)

function onWindowKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && drawerOpen.value) closeDrawer()
}

if (typeof window !== 'undefined') {
  window.addEventListener('keydown', onWindowKeydown)
  onBeforeUnmount(() => window.removeEventListener('keydown', onWindowKeydown))
}

function pick(paths: string[]): MenuItem[] {
  return paths.map((p) => menuItems.find((i) => i.path === p)).filter((i): i is MenuItem => !!i)
}

/** 菜单项高亮：/workspace/:id 命中「工作区」入口 */
function isActive(item: MenuItem): boolean {
  if (route.path === item.path) return true
  return item.path === '/workspace' && route.path.startsWith('/workspace/')
}

/** 顶部：工作区（对话上方）+ 对话 */
const topItems = computed(() => pick(['/workspace', '/chat']))
/** 底部：知识库 */
const bottomItems = computed(() => pick(['/kb']))
const settingsActive = computed(() => isSettingsRoute(route.path))
/** 设置气泡内容：设置组子项 */
const settingsChildren = computed(() => {
  const s = menuItems.find((i) => i.path === '/settings')
  return s?.children ?? []
})
</script>

<template>
  <aside class="sidebar" :class="{ collapsed, 'is-mobile': isMobile, 'drawer-open': drawerOpen }">
    <div class="sidebar-logo">
      <el-icon :size="20"><ChatDotRound /></el-icon>
      <span v-show="!collapsed" class="logo-text">Agent 工作台</span>
      <button
        v-if="isMobile"
        class="collapse-btn logo-collapse"
        type="button"
        aria-label="关闭导航菜单"
        title="关闭导航菜单"
        @click="closeDrawer"
      >
        <el-icon><PanelLeftClose /></el-icon>
      </button>
      <button
        v-else-if="!isNarrow"
        class="collapse-btn logo-collapse"
        type="button"
        :title="collapsed ? '展开' : '折叠'"
        @click="userCollapsed = !userCollapsed"
      >
        <el-icon><component :is="collapsed ? 'PanelLeftOpen' : 'PanelLeftClose'" /></el-icon>
      </button>
    </div>

    <nav class="sidebar-nav sidebar-top">
      <router-link
        v-for="item in topItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item) }"
        :title="collapsed ? item.title : undefined"
        :aria-current="isActive(item) ? 'page' : undefined"
      >
        <el-icon :size="18"><component :is="item.icon" /></el-icon>
        <span v-show="!collapsed" class="nav-text">{{ item.title }}</span>
      </router-link>
    </nav>

    <ConversationList v-show="!collapsed" class="sidebar-conv" @click="closeDrawer" />

    <nav class="sidebar-nav sidebar-bottom">
      <router-link
        v-for="item in bottomItems"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: isActive(item) }"
        :title="collapsed ? item.title : undefined"
        :aria-current="isActive(item) ? 'page' : undefined"
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
          :aria-current="route.path === item.path ? 'page' : undefined"
          @click="settingsOpen = false"
        >
          <el-icon :size="15"><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </router-link>
      </el-popover>
    </nav>
  </aside>
  <div v-if="isMobile && drawerOpen" class="sidebar-backdrop" aria-hidden="true" @click="closeDrawer" />
</template>

<style scoped>
.sidebar {
  width: var(--app-sidebar-width);
  background: var(--app-sidebar-bg);
  border-right: 1px solid var(--app-sidebar-border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s var(--ease-out), transform 0.2s var(--ease-out);
  overflow: hidden;
  flex-shrink: 0;
}
.sidebar.collapsed {
  width: var(--app-sidebar-collapsed-width);
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
  width: var(--app-control-sm);
  height: var(--app-control-sm);
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
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
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
.nav-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 20%;
  bottom: 20%;
  width: 3px;
  border-radius: 2px;
  background: var(--app-primary);
  transform: scaleY(0);
  transform-origin: center;
  transition: transform 180ms var(--ease-out);
}
.nav-item.active::before {
  transform: scaleY(1);
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

.sidebar-backdrop {
  position: fixed;
  z-index: calc(var(--app-z-dropdown) - 1);
  inset: 0;
  background: rgba(15, 23, 42, 0.42);
}

@media (max-width: 768px) {
  .sidebar.is-mobile {
    position: fixed;
    z-index: var(--app-z-dropdown);
    inset: 0 auto 0 0;
    width: min(var(--app-sidebar-width), calc(100vw - 48px));
    height: 100dvh;
    transform: translateX(-100%);
    box-shadow: 8px 0 24px rgba(15, 23, 42, 0.18);
  }
  .sidebar.is-mobile.drawer-open {
    transform: translateX(0);
  }
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
/* origin 微调（emil-design-eng）：popover 从触发点缩放而非中心——right-start 触发点在左侧，origin=left top */
.settings-popover.el-zoom-in-top-enter-active,
.settings-popover.el-zoom-in-top-leave-active {
  transform-origin: left top;
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

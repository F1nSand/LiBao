<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import SidebarNav from '@/components/layout/SidebarNav.vue'

const route = useRoute()
const sidebarRef = ref<InstanceType<typeof SidebarNav> | null>(null)
const mainRef = ref<HTMLElement | null>(null)

function focusMain() {
  void nextTick(() => mainRef.value?.focus())
}

watch(() => route.fullPath, focusMain, { immediate: true })
</script>

<template>
  <div class="app-shell">
    <SidebarNav ref="sidebarRef" />
    <main ref="mainRef" id="app-main" class="app-main" tabindex="-1" aria-label="主内容">
      <button class="mobile-menu-btn" type="button" aria-label="打开导航菜单" @click="sidebarRef?.openDrawer()">
        <el-icon><Menu /></el-icon>
        <span>菜单</span>
      </button>
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  height: 100%;
}
.app-main {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
.mobile-menu-btn {
  display: none;
}

@media (max-width: 768px) {
  .app-main {
    position: relative;
    padding-top: 48px;
  }
  .mobile-menu-btn {
    position: absolute;
    z-index: 1;
    top: 8px;
    left: 12px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 36px;
    padding: 0 10px;
    border: 1px solid var(--app-border);
    border-radius: var(--app-radius);
    color: var(--app-text-main);
    background: var(--app-content-bg);
    cursor: pointer;
  }
}

@media (max-width: 480px) {
  .mobile-menu-btn {
    min-height: var(--app-control-touch);
  }
}
</style>

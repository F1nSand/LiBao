<script setup lang="ts">
import NotificationBell from './NotificationBell.vue'
import ThemeSwitcher from './ThemeSwitcher.vue'
</script>

<template>
  <header class="topbar">
    <div class="topbar-left">
      <span class="provider-status">
        <span class="dot" />
        Provider 已连接
      </span>
    </div>

    <div class="topbar-right">
      <span class="local-mode">本地模式</span>
      <ThemeSwitcher />
      <NotificationBell />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: var(--app-topbar-height);
  background: var(--app-content-bg);
  border-bottom: 1px solid var(--app-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.provider-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--app-font-size-sm);
  color: var(--app-text-secondary);
}
.provider-status .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}
.local-mode {
  font-size: var(--app-font-size-sm);
  color: var(--app-text-muted);
}
</style>

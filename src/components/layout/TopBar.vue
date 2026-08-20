<script setup lang="ts">
import { computed } from 'vue'
import type { User } from '@/types'
import { ROLE_LABEL } from '@/constants/labels'
import NotificationBell from './NotificationBell.vue'
import ThemeSwitcher from './ThemeSwitcher.vue'

const props = defineProps<{ user: User | null }>()
const emit = defineEmits<{ logout: [] }>()

const roleLabel = computed(() => (props.user ? ROLE_LABEL[props.user.role] ?? props.user.role : ''))

function onCommand(cmd: string) {
  if (cmd === 'logout') emit('logout')
}
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
      <ThemeSwitcher />
      <NotificationBell />
      <el-dropdown trigger="click" @command="onCommand">
        <div class="user-chip">
          <el-avatar :size="26" class="user-avatar">{{ user?.name?.[0] ?? '?' }}</el-avatar>
          <div class="user-meta">
            <span class="user-name">{{ user?.name ?? '未登录' }}</span>
            <span class="user-role">{{ roleLabel }}<template v-if="user?.org_id"> · {{ user.org_name ?? user.org_id }}</template></span>
          </div>
          <el-icon><ArrowDown /></el-icon>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>已登录：{{ user?.name }}</el-dropdown-item>
            <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
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
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}
.user-avatar {
  background: var(--app-primary);
  color: #fff;
}
.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.user-name {
  font-size: var(--app-font-size-sm);
  font-weight: 500;
}
.user-role {
  font-size: 11px;
  color: var(--app-text-muted);
}
</style>

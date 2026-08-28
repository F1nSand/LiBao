<script setup lang="ts">
import { computed } from 'vue'
import { useNotifications } from '@/composables/useNotifications'
import { FEATURE, isUnavailable } from '@/api/availability'
import EmptyState from '@/components/common/EmptyState.vue'

/** 设置页「通知」pane（原 NotificationBell 悬浮层改专门窗口）：
 *  消费 useNotifications 模块级单例（state 共享，SSE 由 SettingsView 持有连接）。 */
const { items, unread, loading, markReadById } = useNotifications()
/** 后端未实现通知接口（列表 GET 404 打标）→ pane 内 EmptyState；不用 notificationsStream 标志（SSE 打的是 stream） */
const unavailable = computed(() => isUnavailable(FEATURE.notifications))
</script>

<template>
  <div class="notif-pane">
    <div class="notif-head">
      <span class="notif-title">通知</span>
      <span class="notif-count">{{ unread }} 未读</span>
    </div>
    <EmptyState v-if="unavailable" text="后端暂未实现通知接口" />
    <div v-else-if="loading" class="notif-empty">加载中…</div>
    <div v-else-if="items.length === 0" class="notif-empty">暂无通知</div>
    <ul v-else class="notif-list">
      <li v-for="n in items.slice(0, 20)" :key="n.id" class="notif-item-wrap">
        <button
          type="button"
          class="notif-item"
          :class="{ unread: !n.read }"
          :aria-label="n.body ? `${n.title}：${n.body}` : n.title"
          @click="markReadById(n.id)"
        >
          <span class="notif-dot" :class="n.level" aria-hidden="true" />
          <span class="notif-body">
            <span class="notif-text">{{ n.title }}</span>
            <span v-if="n.body" class="notif-sub">{{ n.body }}</span>
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.notif-pane {
  padding: 4px 0 0;
}
.notif-head {
  display: flex;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--app-border-light);
}
.notif-title {
  font-weight: 600;
}
.notif-count {
  font-size: var(--app-font-size-sm);
  color: var(--app-text-muted);
}
.notif-empty {
  padding: 20px 0;
  text-align: center;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-sm);
}
.notif-list {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  max-height: 420px;
  overflow-y: auto;
}
.notif-item-wrap {
  list-style: none;
}
.notif-item {
  display: flex;
  gap: 8px;
  width: 100%;
  padding: 8px 6px;
  border: none;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s var(--ease-out);
}
.notif-item:hover {
  background: var(--app-bg);
}
.notif-item.unread .notif-text {
  font-weight: 600;
}
.notif-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
  background: var(--app-border);
}
.notif-dot.info {
  background: var(--app-info);
}
.notif-dot.success {
  background: var(--app-success);
}
.notif-dot.warning {
  background: var(--app-warning);
}
.notif-dot.error {
  background: var(--app-danger);
}
.notif-body {
  display: block;
  min-width: 0;
}
.notif-text {
  display: block;
  font-size: var(--app-font-size-sm);
  line-height: 1.4;
}
.notif-sub {
  display: block;
  font-size: var(--app-font-size-xs);
  color: var(--app-text-muted);
}
</style>

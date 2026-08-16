<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listNotifications, markRead } from '@/api/notifications'
import { FEATURE, isUnavailable } from '@/api/availability'
import { useSSE } from '@/composables/useSSE'
import { getToken } from '@/utils/token'
import type { Notification } from '@/types'

const items = ref<Notification[]>([])
const unread = ref(0)
const loading = ref(false)
/** 后端未实现通知接口（HTTP 404 打标）→ 隐藏铃铛 */
const unavailable = computed(() => isUnavailable(FEATURE.notifications))

async function load() {
  loading.value = true
  try {
    const res = await listNotifications({ page: 1, page_size: 20 })
    items.value = res.items
    unread.value = res.items.filter((n) => !n.read).length
  } catch {
    // 通知加载失败静默
  } finally {
    loading.value = false
  }
}

const sse = useSSE(
  '/api/v1/notifications/stream',
  () => {
    const token = getToken()
    return {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    }
  },
  {
    onEvent: (ev) => {
      const n = ev.payload as Notification
      if (n && n.id) {
        items.value.unshift(n)
        if (items.value.length > 100) items.value.pop() // 有界增长，防长会话内存泄漏
        if (!n.read) unread.value++
      }
    },
  },
)

async function onClickItem(n: Notification) {
  if (!n.read) {
    try {
      await markRead(n.id)
      n.read = true
      unread.value = Math.max(0, unread.value - 1)
    } catch (e) {
      ElMessage.error('标记已读失败')
      console.error(e)
    }
  }
}

onMounted(() => {
  void load()
  if (!unavailable.value) sse.connect()
})
</script>

<template>
  <el-popover v-if="!unavailable" placement="bottom" :width="340" trigger="click">
    <template #reference>
      <div class="bell" role="button" aria-label="通知">
        <el-badge :value="unread" :hidden="unread === 0" :max="99">
          <el-icon :size="18"><Bell /></el-icon>
        </el-badge>
      </div>
    </template>

    <div class="notif-panel">
      <div class="notif-head">
        <span class="notif-title">通知</span>
        <span class="notif-count">{{ unread }} 未读</span>
      </div>
      <div v-if="loading" class="notif-empty">加载中…</div>
      <div v-else-if="items.length === 0" class="notif-empty">暂无通知</div>
      <ul v-else class="notif-list">
        <li
          v-for="n in items.slice(0, 20)"
          :key="n.id"
          class="notif-item"
          :class="{ unread: !n.read }"
          @click="onClickItem(n)"
        >
          <span class="notif-dot" :class="n.level" />
          <div class="notif-body">
            <div class="notif-text">{{ n.title }}</div>
            <div v-if="n.body" class="notif-sub">{{ n.body }}</div>
          </div>
        </li>
      </ul>
    </div>
  </el-popover>
</template>

<style scoped>
.bell {
  cursor: pointer;
  display: flex;
  align-items: center;
  color: var(--app-text-secondary);
}
.bell:hover {
  color: var(--app-primary);
}
.notif-panel {
  max-height: 420px;
  display: flex;
  flex-direction: column;
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
  overflow-y: auto;
}
.notif-item {
  display: flex;
  gap: 8px;
  padding: 8px 6px;
  border-radius: var(--app-radius-sm);
  cursor: pointer;
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
  background: #409eff;
}
.notif-dot.success {
  background: #22c55e;
}
.notif-dot.warning {
  background: #f59e0b;
}
.notif-dot.error {
  background: #ef4444;
}
.notif-body {
  min-width: 0;
}
.notif-text {
  font-size: var(--app-font-size-sm);
  line-height: 1.4;
}
.notif-sub {
  font-size: 12px;
  color: var(--app-text-muted);
}
</style>

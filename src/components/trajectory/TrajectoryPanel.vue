<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTrajectoryStore } from '@/stores/trajectory'
import { foldTrajectory, flatCells, type TrajectoryCell } from '@/utils/trajectory'
import { useMediaQuery } from '@/composables/useMediaQuery'
import TrajectoryTimeline from './TrajectoryTimeline.vue'
import TrajectoryLedger from './TrajectoryLedger.vue'
import TrajectoryDetailPanel from './TrajectoryDetailPanel.vue'
import EmptyState from '@/components/common/EmptyState.vue'

/** 轨迹工作区（docs/02 §6.3）：独立页 TrajectoryView 与 Chat「轨迹」模式共用；无页面级 back/title。
 * `live` = 会话流式活跃 → 轮询实时同步（docs 03 §5.2.1 / §5.8 逐轮落库后即现）。 */
const props = defineProps<{ conversationId: string | null; focusToolCallId?: string; live?: boolean }>()

const store = useTrajectoryStore()

const selectedIndex = ref<number | null>(null)
/** 聚焦区域集合（甘特拖选 → 框内内容不变、外部变灰透明，含甘特+台账）；selectedIndex 为单独「选中」的单元格 */
const focusSet = ref<Set<number>>(new Set())
const query = ref('')
const collapsedAll = ref(false)
/** 工具栏 toggle（选中=启用）：Duration=甘特按耗时；Turns=台账收起中间；Calls=隐藏 TOOL */
const durationOn = ref(false)
const turnsOn = ref(false)
const callsOn = ref(false)
const splitWidth = ref(480)
const mainRef = ref<HTMLElement | null>(null)
/** 窄屏（中窗口）下详情面板改为浮层覆盖台账 */
const detailOverlay = useMediaQuery('(max-width: 1100px)')

const turns = computed(() => (store.detail ? foldTrajectory(store.detail.nodes) : []))
const cells = computed(() => flatCells(turns.value))
const selectedCell = computed<TrajectoryCell | null>(
  () => cells.value.find((c) => c.index === selectedIndex.value) ?? null,
)

async function load() {
  const id = props.conversationId
  if (!id) {
    store.reset()
    selectedIndex.value = null
    focusSet.value = new Set()
    return
  }
  selectedIndex.value = null
  focusSet.value = new Set()
  query.value = ''
  collapsedAll.value = false
  await store.load(id)
  if (store.error) return
  // 跨视图定位：focus=<toolCallId> → 选中该工具记录
  if (props.focusToolCallId) {
    const c = cells.value.find((cell) => cell.toolCallId === props.focusToolCallId)
    if (c) {
      selectedIndex.value = c.index
      focusSet.value = new Set([c.index])
    }
  }
}

watch(() => props.conversationId, load, { immediate: true })

/* ---------- live 实时同步：流式活跃时轮询刷新（不重置选中/搜索/折叠，避免打断查看） ---------- */
const POLL_INTERVAL_MS = 2500
let pollTimer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  const id = props.conversationId
  if (id) await store.load(id)
}

function startPolling() {
  stopPolling()
  if (!props.conversationId || !props.live) return
  pollTimer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
}
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(
  () => props.conversationId,
  () => {
    void load()
    startPolling()
  },
  { immediate: true },
)

watch(
  () => props.live,
  (live) => {
    if (live) startPolling()
    else {
      stopPolling()
      void refresh() // 流式结束再刷一次收尾
    }
  },
)

/** 点击（甘特方块/台账行）→ 只「选中」该单元格，聚焦区域不变 */
function onCellSelect(index: number) {
  selectedIndex.value = index
}
/** 甘特拖选 → 设置「聚焦区域」（框内内容不变、外部变灰透明），首个为主选中 */
function onTimelineFocus(indices: number[]) {
  if (!indices.length) return
  focusSet.value = new Set(indices)
  selectedIndex.value = indices[0]
}
function onLedgerSelect(index: number) {
  onCellSelect(index)
}
function onResetSelection() {
  selectedIndex.value = null
  focusSet.value = new Set()
}
function onLoadEarlier() {
  if (props.conversationId) void store.loadEarlier(props.conversationId)
}
function onEsc(e: KeyboardEvent) {
  if (e.key === 'Escape') onResetSelection()
}
onMounted(() => window.addEventListener('keydown', onEsc))
onBeforeUnmount(() => {
  stopPolling()
  window.removeEventListener('keydown', onEsc)
})

function onSplitStart(e: MouseEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = splitWidth.value
  const onMove = (ev: MouseEvent) => {
    const containerW = mainRef.value?.clientWidth ?? 1200
    splitWidth.value = Math.min(Math.max(startW + (startX - ev.clientX), 240), containerW - 320)
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.userSelect = ''
  }
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
</script>

<template>
  <div class="tj-panel">
    <div class="tj-panel-toolbar">
      <!-- 按钮从左紧挨排（无间隔），左右各留一小段；切换高亮 = 前方图标（✓），不用改色 -->
      <el-button text class="tj-tool-btn" @click="collapsedAll = !collapsedAll">
        {{ collapsedAll ? '全部展开' : '全部折叠' }}
      </el-button>
      <el-button text class="tj-tool-btn" :class="{ active: durationOn }" @click="durationOn = !durationOn">
        <el-icon><Timer /></el-icon>Duration
      </el-button>
      <el-button text class="tj-tool-btn" @click="turnsOn = !turnsOn">
        <el-icon><component :is="turnsOn ? 'Fold' : 'Expand'" /></el-icon>Turns
      </el-button>
      <el-button text class="tj-tool-btn" @click="callsOn = !callsOn">
        <el-icon><component :is="callsOn ? 'Hide' : 'Tools'" /></el-icon>Calls
      </el-button>
      <div class="tj-toolbar-spacer" />
      <el-input v-model="query" size="small" placeholder="搜索…" clearable class="tj-search" />
    </div>

    <div class="tj-panel-body">
      <template v-if="!conversationId">
        <EmptyState text="请先选择会话" />
      </template>
      <template v-else-if="store.unavailable">
        <EmptyState text="后端暂未实现对话轨迹接口" />
      </template>
      <template v-else-if="store.error">
        <el-empty description="轨迹加载失败" :image-size="60" />
      </template>
      <template v-else-if="turns.length === 0">
        <EmptyState text="该会话暂无轨迹数据" />
      </template>
      <template v-else>
        <TrajectoryTimeline
          :turns="turns"
          :duration-on="durationOn"
          :selected-index="selectedIndex"
          :focus-set="focusSet"
          :query="query"
          :has-more="store.hasMore"
          @select="onCellSelect"
          @focus="onTimelineFocus"
          @reset="onResetSelection"
          @load-earlier="onLoadEarlier"
        />
        <div ref="mainRef" class="tj-main" :class="{ 'detail-overlay': detailOverlay }">
          <TrajectoryLedger
            :turns="turns"
            :query="query"
            :selected-index="selectedIndex"
            :focus-set="focusSet"
            :collapsed-all="collapsedAll"
            :turns-on="turnsOn"
            :calls-on="callsOn"
            @select="onLedgerSelect"
            class="tj-ledger"
          />
          <div class="tj-splitter" title="拖拽调宽" @mousedown="onSplitStart" />
          <TrajectoryDetailPanel
            v-show="!detailOverlay || !!selectedCell"
            :cell="selectedCell"
            class="tj-detail"
            :style="detailOverlay ? {} : { width: `${splitWidth}px` }"
            @close="selectedIndex = null"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tj-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tj-panel-toolbar {
  display: flex;
  align-items: center;
  min-height: 44px;
  gap: 0; /* 按钮紧挨着排，无间隔 */
  padding: 0 12px; /* 左右各留一小段（不顶格） */
  background: var(--app-content-bg);
  border-bottom: 1px solid var(--app-border-light);
  flex-shrink: 0;
}
.tj-tool-btn {
  margin: 0 !important; /* 去掉 el-button 相邻 margin，紧挨排 */
  height: 28px;
  border-radius: var(--app-radius);
}
.tj-tool-btn:hover {
  background: var(--app-bg);
}
.tj-tool-btn.active {
  background: var(--app-bg); /* Duration 选中：灰色高光底（不用图标区分） */
}
.tj-toolbar-spacer {
  flex: 1;
}
.tj-search {
  width: 180px;
}
.tj-panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tj-main {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
}
.tj-ledger {
  flex: 1;
  min-width: 320px;
}
.tj-splitter {
  width: 6px;
  cursor: col-resize;
  flex-shrink: 0;
}
.tj-splitter:hover {
  background: var(--el-color-primary-light-7);
}
.tj-detail {
  height: 100%;
  flex-shrink: 0;
}
/* 窄屏（中窗口）：详情面板浮层覆盖台账 */
.tj-main.detail-overlay .tj-detail {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(460px, 88%);
  z-index: 5;
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.1);
}
.tj-main.detail-overlay .tj-splitter {
  display: none;
}
</style>

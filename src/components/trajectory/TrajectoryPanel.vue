<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTrajectoryStore } from '@/stores/trajectory'
import { foldTrajectory, flatCells, type TrajectoryCell } from '@/utils/trajectory'
import { useMediaQuery } from '@/composables/useMediaQuery'
import TrajectoryTimeline from './TrajectoryTimeline.vue'
import TrajectoryLedger from './TrajectoryLedger.vue'
import TrajectoryDetailPanel from './TrajectoryDetailPanel.vue'
import EmptyState from '@/components/common/EmptyState.vue'

/** 轨迹工作区（docs/02 §6.3）：独立页 TrajectoryView 与 Chat「轨迹」模式共用；无页面级 back/title */
const props = defineProps<{ conversationId: string | null; focusToolCallId?: string }>()

const store = useTrajectoryStore()

const selectedIndex = ref<number | null>(null)
const query = ref('')
const collapsedAll = ref(false)
const projection = ref<'sequence' | 'duration' | 'time' | 'actual'>('sequence')
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
    return
  }
  selectedIndex.value = null
  query.value = ''
  collapsedAll.value = false
  await store.load(id)
  if (store.error) return
  // 跨视图定位：focus=<toolCallId> → 选中该工具记录
  if (props.focusToolCallId) {
    const c = cells.value.find((cell) => cell.toolCallId === props.focusToolCallId)
    if (c) selectedIndex.value = c.index
  }
}

watch(() => props.conversationId, load, { immediate: true })

function onSelect(index: number) {
  selectedIndex.value = index
}
function onResetSelection() {
  selectedIndex.value = null
}
function onLoadEarlier() {
  if (props.conversationId) void store.loadEarlier(props.conversationId)
}
function onEsc(e: KeyboardEvent) {
  if (e.key === 'Escape') selectedIndex.value = null
}
onMounted(() => window.addEventListener('keydown', onEsc))
onBeforeUnmount(() => window.removeEventListener('keydown', onEsc))

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
      <el-input v-model="query" size="small" placeholder="搜索…" clearable class="tj-search" />
      <el-button size="small" @click="collapsedAll = !collapsedAll">
        {{ collapsedAll ? '全部展开' : '全部折叠' }}
      </el-button>
      <el-radio-group v-model="projection" size="small">
        <el-radio-button value="sequence">顺序</el-radio-button>
        <el-radio-button value="duration">耗时</el-radio-button>
        <el-radio-button value="time">时间</el-radio-button>
        <el-radio-button value="actual">实际</el-radio-button>
      </el-radio-group>
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
          :projection="projection"
          :selected-index="selectedIndex"
          :query="query"
          :has-more="store.hasMore"
          @select="onSelect"
          @reset="onResetSelection"
          @load-earlier="onLoadEarlier"
        />
        <div ref="mainRef" class="tj-main" :class="{ 'detail-overlay': detailOverlay }">
          <TrajectoryLedger
            :turns="turns"
            :query="query"
            :selected-index="selectedIndex"
            :collapsed-all="collapsedAll"
            @select="onSelect"
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
  gap: 8px;
  flex-shrink: 0;
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

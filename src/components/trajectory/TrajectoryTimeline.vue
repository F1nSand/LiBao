<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TrajectoryTurn } from '@/utils/trajectory'
import { cellMatches, flatCells, kindColor, kindLabel, kindLane } from '@/utils/trajectory'
import { formatDuration, formatTime } from '@/utils/format'

/**
 * 顶部时间轴（docs/02 §6.3）：三条泳道 Input/Model/Tools。
 * 投影：durationOn=false=等宽(sequence)，true=按耗时定宽(duration)。
 * 交互：滚轮缩放（以鼠标为锚，panX 钳制两端不逃逸）、左键拖拽框选（聚焦区域，外部变灰）、
 *       点击选中单个单元格、双击/Esc 复位、搜索时暗化非命中；hasMore 时左侧「加载更早」。
 */
const props = defineProps<{
  turns: TrajectoryTurn[]
  durationOn: boolean
  selectedIndex: number | null
  focusSet: Set<number>
  query: string
  hasMore: boolean
}>()
const emit = defineEmits<{
  select: [index: number]
  empty: [index: number] // 点击空白：选中最近记录 + 取消聚焦（空白属未聚焦部分）
  focus: [indices: number[]]
  reset: []
  loadEarlier: []
}>()

const UNIT = 36
const GAP = 4
const LABEL_W = 44 // .tj-lane-label 列宽：时间轴坐标以 .tj-lane-body 为原点（label 右侧为 0），换算用
const LANES = [
  { name: 'Input', index: 0 },
  { name: 'Model', index: 1 },
  { name: 'Tools', index: 2 },
]

const scrollRef = ref<HTMLElement | null>(null)

const cells = computed(() => flatCells(props.turns))
const hasAnyDuration = computed(() => cells.value.some((c) => c.durationMs != null))

const scale = ref(1)
const panX = ref(0)
const boxDrag = ref<{ startX: number; curX: number; moved: boolean } | null>(null)

interface Layout {
  x: number
  width: number
}

function baseLayout(): Layout[] {
  const cs = cells.value
  // 默认 sequence 等宽；durationOn 且有耗时数据 → 按耗时定宽
  if (!props.durationOn || !hasAnyDuration.value) {
    let x = 0
    return cs.map(() => {
      const r = { x, width: UNIT }
      x += UNIT + GAP
      return r
    })
  }
  let x = 0
  return cs.map((c) => {
    const w = c.durationMs != null ? Math.max(UNIT, Math.round(c.durationMs / 4)) : UNIT
    const r = { x, width: w }
    x += w + GAP
    return r
  })
}

const spans = computed(() =>
  baseLayout().map((r, i) => {
    const c = cells.value[i]
    const lane = kindLane(c.kind)
    return {
      index: c.index,
      kind: c.kind,
      lane,
      x: r.x * scale.value + panX.value,
      width: Math.max(1, r.width * scale.value),
      color: kindColor(c.kind, c.isError),
      isError: !!c.isError,
      dimmed: !!props.query && !cellMatches(c, props.query),
      startedAt: c.startedAt,
      durationMs: c.durationMs,
      toolName: c.toolName,
      toolTip: `${kindLabel(c.kind)}${c.toolName ? ` · ${c.toolName}` : ''} · ${formatTime(c.startedAt)}${
        c.durationMs != null ? ` · ${formatDuration(c.durationMs)}` : ''
      }`,
      // 第二行：tool 单元格展示入参摘要（cell.text 已含工具名 + 截断入参）
      toolParams: c.kind === 'tool' && c.text ? c.text : undefined,
    }
  }),
)

/** 最小缩放 = 内容恰好铺满泳道可视区（起点在最左、终点在最右即极限，不继续缩小） */
function fitScale(): number {
  if (!cells.value.length) return 1
  const r = baseLayout()
  const minR = Math.min(...r.map((i) => i.x))
  const maxR = Math.max(...r.map((i) => i.x + i.width))
  const contentW = Math.max(1, maxR - minR)
  const bodyEl = scrollRef.value?.querySelector('.tj-lane-body')
  const viewW = bodyEl?.clientWidth || scrollRef.value?.clientWidth || 800
  return Math.min(1, Math.max(0.1, viewW / contentW))
}

const boxRect = computed(() => {
  if (!boxDrag.value) return null
  const b = boxDrag.value
  return { left: Math.min(b.startX, b.curX), width: Math.abs(b.curX - b.startX) }
})

function spansInLane(lane: number) {
  return spans.value.filter((s) => s.lane === lane)
}

function contentX(clientX: number): number {
  const el = scrollRef.value
  if (!el) return 0
  const rect = el.getBoundingClientRect()
  // 泳道坐标系（label 右侧为 0），与 span 的 left 对齐
  return clientX - rect.left - LABEL_W + el.scrollLeft
}

/**
 * 鼠标锚定缩放：光标处内容点不动 → 可在任意位置（含右侧）放大；
 * panX 钳制 → 左端不右移出视口左缘（可左移出屏）、右端不左移出视口右缘（不逃逸）；
 * 最小缩放 = 内容恰好铺满可视区（两端贴边即极限，不再缩小）。
 */
function onWheel(e: WheelEvent) {
  e.preventDefault()
  const bodyEl = scrollRef.value?.querySelector('.tj-lane-body') as HTMLElement | null
  const viewW = bodyEl?.clientWidth || scrollRef.value?.clientWidth || 800
  const rect = scrollRef.value?.getBoundingClientRect()
  const factor = e.deltaY < 0 ? 1.15 : 0.87
  const oldScale = scale.value
  const newScale = Math.min(8, Math.max(fitScale(), oldScale * factor))
  if (newScale === oldScale) return
  // 光标内容坐标（泳道坐标系，label 右侧为 0）
  const mouseX = rect ? e.clientX - rect.left - LABEL_W : viewW / 2
  const b = (mouseX - panX.value) / oldScale
  const r = baseLayout()
  const minR = Math.min(...r.map((i) => i.x))
  const maxR = Math.max(...r.map((i) => i.x + i.width))
  // panX ∈ [viewW - maxR·s, -minR·s]：左端 ≤ 视口左、右端 ≥ 视口右
  let newPan = panX.value + b * (oldScale - newScale)
  newPan = Math.min(-minR * newScale, Math.max(viewW - maxR * newScale, newPan))
  scale.value = newScale
  panX.value = newPan
}

function onMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  boxDrag.value = { startX: contentX(e.clientX), curX: contentX(e.clientX), moved: false }
  document.addEventListener('mousemove', onDocMove)
  document.addEventListener('mouseup', onDocUp)
}

function onDocMove(e: MouseEvent) {
  if (!boxDrag.value) return
  boxDrag.value.curX = contentX(e.clientX)
  if (Math.abs(boxDrag.value.curX - boxDrag.value.startX) > 3) boxDrag.value.moved = true
}

function onDocUp() {
  if (boxDrag.value) {
    const b = boxDrag.value
    boxDrag.value = null
    if (!b.moved) {
      // 点击空白：命中或选最近 span（单选）
      const hit = spans.value.find((s) => s.x <= b.startX && b.startX <= s.x + s.width)
      if (hit) {
        emit('select', hit.index)
      } else {
        let nearest: (typeof spans.value)[number] | null = null
        let best = Infinity
        for (const s of spans.value) {
          const d = Math.abs(s.x + s.width / 2 - b.startX)
          if (d < best) {
            best = d
            nearest = s
          }
        }
        // 点击空白：选中最近记录，并取消聚焦（空白属于「未聚焦部分」）
        if (nearest) emit('empty', nearest.index)
        else emit('reset')
      }
    } else {
      // 拖选：框内全部单元格 → 聚焦区域（框内不变、外部变灰透明），首个为主选中
      const lo = Math.min(b.startX, b.curX)
      const hi = Math.max(b.startX, b.curX)
      const hit = spans.value.filter((s) => s.x + s.width >= lo && s.x <= hi).map((s) => s.index)
      if (hit.length) emit('focus', hit)
      else emit('reset')
    }
  }
  document.removeEventListener('mousemove', onDocMove)
  document.removeEventListener('mouseup', onDocUp)
}

function onContextMenu(e: MouseEvent) {
  e.preventDefault()
}

function onDblClick() {
  emit('reset')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('reset')
}
</script>

<template>
  <div
    ref="scrollRef"
    class="tj-timeline"
    tabindex="0"
    @wheel="onWheel"
    @mousedown="onMouseDown"
    @contextmenu="onContextMenu"
    @dblclick="onDblClick"
    @keydown="onKeydown"
  >
    <div v-if="durationOn && !hasAnyDuration" class="tj-note">无耗时数据，已回退为顺序视图</div>
    <div class="tj-hint">
      <button v-if="hasMore" class="tj-load-more" type="button" @click="emit('loadEarlier')">… 加载更早</button>
    </div>
    <div class="tj-track">
      <div v-for="lane in LANES" :key="lane.name" class="tj-lane">
        <span class="tj-lane-label">{{ lane.name }}</span>
        <div class="tj-lane-body">
          <div
            v-for="s in spansInLane(lane.index)"
            :key="s.index"
            class="tj-span"
            :class="{ selected: selectedIndex === s.index, 'focus-dim': focusSet.size > 0 && !focusSet.has(s.index), error: s.isError, dimmed: s.dimmed }"
            :style="{ left: `${s.x}px`, width: `${s.width}px`, background: s.color }"
            role="button"
            :aria-label="s.toolTip"
            tabindex="0"
            @keydown.enter="emit('select', s.index)"
            @mousedown.stop
            @click.stop="emit('select', s.index)"
          >
            <el-tooltip placement="top" popper-class="tj-tip" :show-after="500">
              <div class="tj-span-fill" />
              <template #content>
                <div class="tj-tip-line">{{ s.toolTip }}</div>
                <div v-if="s.toolParams" class="tj-tip-line tj-tip-params">{{ s.toolParams }}</div>
              </template>
            </el-tooltip>
          </div>
        </div>
      </div>
      <div v-if="boxRect" class="tj-box" :style="{ left: `${LABEL_W + boxRect.left}px`, width: `${boxRect.width}px` }" />
    </div>
  </div>
</template>

<style scoped>
.tj-timeline {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  background: var(--app-content-bg);
  padding: 4px 6px 6px;
  overflow: hidden; /* 平移/缩放由 panX 控制，内容溢出裁剪，无滚轮条 */
  user-select: none; /* 拖拽/点选不触发浏览器搜索文本 */
  flex-shrink: 0;
  outline: none;
  box-shadow: var(--app-shadow-card);
}
.tj-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--app-text-muted);
  margin-bottom: 2px;
}
.tj-load-more {
  border: 1px solid var(--app-border);
  background: var(--app-bg);
  color: var(--app-primary);
  border-radius: var(--app-radius-sm);
  padding: 1px 8px;
  font-size: 11px;
  cursor: pointer;
}
.tj-load-more:hover {
  border-color: var(--app-primary);
}
.tj-note {
  font-size: 12px;
  color: var(--app-text-muted);
  margin-bottom: 2px;
}
.tj-track {
  position: relative;
}
.tj-lane {
  display: flex;
  align-items: center;
  height: 18px;
  margin: 1px 0;
}
.tj-lane-label {
  width: 44px;
  flex-shrink: 0;
  font-size: 10px;
  color: var(--app-text-muted);
}
.tj-lane-body {
  position: relative;
  flex: 1;
  height: 100%;
  z-index: 1;
  overflow: hidden; /* 方块超出可视区裁剪（左右端点贴边） */
}
.tj-span {
  position: absolute;
  top: 2px;
  bottom: 2px;
  border-radius: 3px;
  cursor: pointer;
  opacity: 0.85;
}
.tj-span:hover {
  opacity: 1;
}
.tj-span.selected {
  outline: 2px solid var(--app-primary);
  opacity: 1;
}
.tj-span.error {
  outline: 1px solid #ef4444;
}
.tj-span.dimmed {
  opacity: 0.15;
}
/* 聚焦区域外：变灰透明（聚焦内容本身不变） */
.tj-span.focus-dim {
  opacity: 0.35;
  filter: grayscale(0.7);
}
.tj-span-fill {
  width: 100%;
  height: 100%;
}
.tj-box {
  position: absolute;
  top: 0;
  bottom: 0;
  background: rgba(99, 102, 241, 0.12);
  border-left: 1px solid var(--app-primary);
  border-right: 1px solid var(--app-primary);
  pointer-events: none;
}
</style>

<!-- el-tooltip popper teleport 到 body，scoped 样式无效 → 非 scoped 块（popper-class="tj-tip"） -->
<style>
.tj-tip {
  line-height: 1.5;
}
.tj-tip-params {
  color: var(--app-text-secondary, #6b7280);
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

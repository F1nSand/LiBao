<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { TrajectoryCell, TrajectoryTurn } from '@/utils/trajectory'
import { cellMatches, kindBgColor, kindColor, kindLabel, turnStepsSummary } from '@/utils/trajectory'
import { formatDuration, formatTokens } from '@/utils/format'

/** 事件台账（docs/02 §6.3）：Turn → Group → Cell。
 * grid 对齐：左留白列(轮次徽标) + 标签列(右对齐到最长) + 文本列 + dur/tok；
 * 轮次徽标在 USER 行、左侧窄高光条（z 高于行底，hover/选中不遮挡）；
 * turnsOn 收起中间（省略行可单独展开）、callsOn 隐藏 TOOL；focusTurn 聚焦（其余变浅）。
 * 不渲染 Step/Message 分组横条。 */
const props = defineProps<{
  turns: TrajectoryTurn[]
  query: string
  selectedIndex: number | null
  collapsedAll: boolean
  turnsOn: boolean
  callsOn: boolean
  focusTurn: number | null
}>()
const emit = defineEmits<{ select: [index: number] }>()

const listRef = ref<HTMLElement | null>(null)
const collapsedGroups = ref(new Set<string>())
/** Turns 收起模式下被单独展开的 turn（点击省略行切换） */
const expandedTurnsFold = ref(new Set<number>())

/** 选中行滚动到可见区（跨视图定位 / 时间轴点击联动） */
watch(
  () => props.selectedIndex,
  (idx) => {
    if (idx == null) return
    void nextTick(() => {
      listRef.value?.querySelector('.tj-cell.selected')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
  },
)

watch(
  () => props.collapsedAll,
  (all) => {
    // 全部折叠/展开：控制分组折叠（轮次中间；无分组横条，仅整体折叠）
    collapsedGroups.value = all
      ? new Set(props.turns.flatMap((t) => t.groups.map((g) => `${t.index}:${g.step}`)))
      : new Set()
  },
)

const hasQuery = computed(() => props.query.trim().length > 0)

function cellMatchesQuery(c: TrajectoryCell): boolean {
  return cellMatches(c, props.query)
}

/** 搜索模式：仅返回命中 cell（去掉分组头），Turn 头保留 */
function searchResults(): Array<{ turn: TrajectoryTurn; cells: TrajectoryCell[] }> {
  if (!hasQuery.value) return []
  const out: Array<{ turn: TrajectoryTurn; cells: TrajectoryCell[] }> = []
  for (const t of props.turns) {
    const cells = [...(t.userCell ? [t.userCell] : []), ...t.contextCells, ...t.groups.flatMap((g) => g.cells)].filter(
      cellMatchesQuery,
    )
    if (cells.length) out.push({ turn: t, cells })
  }
  return out
}

function isGroupCollapsed(t: TrajectoryTurn, step: number): boolean {
  return collapsedGroups.value.has(`${t.index}:${step}`)
}

/** 标签 pill 内联样式：标签名用主色、标签框用浅色 */
function labelStyle(c: TrajectoryCell): Record<string, string> {
  return { color: kindColor(c.kind, c.isError), background: kindBgColor(c.kind) }
}

/** Calls 开启时隐藏 TOOL 行 */
function visibleGroupCells(g: TrajectoryTurn['groups'][number]): TrajectoryCell[] {
  return props.callsOn ? g.cells.filter((c) => c.kind !== 'tool') : g.cells
}

/** 该 turn 是否含选中 cell（高光条 / 徽标着色） */
function turnHasSelected(t: TrajectoryTurn): boolean {
  if (props.selectedIndex == null) return false
  if (t.userCell?.index === props.selectedIndex) return true
  if (t.contextCells.some((c) => c.index === props.selectedIndex)) return true
  return t.groups.some((g) => g.cells.some((c) => c.index === props.selectedIndex))
}

/** Turns 收起模式：该 turn 是否处于折叠（显示省略行） */
function isTurnFolded(t: TrajectoryTurn): boolean {
  return props.turnsOn && !expandedTurnsFold.value.has(t.index)
}
function toggleFold(index: number) {
  const s = new Set(expandedTurnsFold.value)
  if (s.has(index)) s.delete(index)
  else s.add(index)
  expandedTurnsFold.value = s
}
</script>

<template>
  <div ref="listRef" class="tj-ledger">
    <!-- 搜索模式：扁平命中行（Turn 头保留） -->
    <template v-if="hasQuery">
      <div v-for="{ turn, cells } in searchResults()" :key="`s-${turn.index}`" class="tj-turn">
        <div v-for="c in cells" :key="c.index" class="tj-cell" :class="{ selected: c.index === selectedIndex }" @click="emit('select', c.index)">
          <span v-if="c.index === turn.userCell?.index" class="tj-turn-badge">Turn {{ turn.index }}</span>
          <span v-else class="tj-cell-blank" />
          <span class="tj-cell-label" :style="labelStyle(c)">{{ kindLabel(c.kind) }}</span>
          <span class="tj-cell-text">{{ c.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(c.durationMs) }}</span>
          <span class="tj-cell-tok mono">{{ c.kind === 'message' ? formatTokens(c.tokenUsage) : '' }}</span>
        </div>
      </div>
      <div v-if="searchResults().length === 0" class="tj-empty">无匹配记录</div>
    </template>

    <!-- 普通模式：Turn →（USER/上下文）+（省略行 | 分组 cells） -->
    <template v-else>
      <div
        v-for="t in turns"
        :key="t.index"
        class="tj-turn"
        :class="{ focused: focusTurn === t.index, dimmed: focusTurn != null && focusTurn !== t.index }"
      >
        <!-- 左侧窄高光条（z 高于行底，hover/选中不遮挡） -->
        <span class="tj-turn-bar" :class="{ on: turnHasSelected(t) || focusTurn === t.index }" />

        <div v-if="t.userCell" class="tj-cell turn-user" :class="{ selected: t.userCell.index === selectedIndex }" @click="emit('select', t.userCell.index)">
          <span class="tj-turn-badge" :class="{ on: turnHasSelected(t) || focusTurn === t.index }">Turn {{ t.index }}</span>
          <span class="tj-cell-label" :style="labelStyle(t.userCell)">{{ kindLabel(t.userCell.kind) }}</span>
          <span class="tj-cell-text">{{ t.userCell.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(t.userCell.durationMs) }}</span>
          <span class="tj-cell-tok mono" />
        </div>

        <div v-for="cc in t.contextCells" :key="cc.index" class="tj-cell" :class="{ selected: cc.index === selectedIndex }" @click="emit('select', cc.index)">
          <span class="tj-cell-blank" />
          <span class="tj-cell-label" :style="labelStyle(cc)">{{ kindLabel(cc.kind) }}</span>
          <span class="tj-cell-text">{{ cc.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(cc.durationMs) }}</span>
          <span class="tj-cell-tok mono" />
        </div>

        <template v-if="isTurnFolded(t)">
          <div v-if="t.groups.length" class="tj-cell tj-fold" @click="toggleFold(t.index)">
            <span class="tj-cell-blank" />
            <span class="tj-cell-label tj-fold-label">…</span>
            <span class="tj-cell-fold">{{ turnStepsSummary(t) }}</span>
            <span class="tj-cell-dur mono" />
            <span class="tj-cell-tok mono" />
          </div>
        </template>
        <template v-else>
          <div v-for="g in t.groups" :key="`${t.index}-${g.step}`" class="tj-group">
            <template v-if="!isGroupCollapsed(t, g.step)">
              <div v-for="c in visibleGroupCells(g)" :key="c.index" class="tj-cell" :class="{ selected: c.index === selectedIndex }" @click="emit('select', c.index)">
                <span class="tj-cell-blank" />
                <span class="tj-cell-label" :style="labelStyle(c)">{{ kindLabel(c.kind) }}</span>
                <span class="tj-cell-text">{{ c.text }}</span>
                <span class="tj-cell-dur mono">{{ formatDuration(c.durationMs) }}</span>
                <span class="tj-cell-tok mono">{{ c.kind === 'message' ? formatTokens(c.tokenUsage) : '' }}</span>
              </div>
            </template>
          </div>
        </template>
      </div>
      <div v-if="turns.length === 0" class="tj-empty">暂无轨迹数据</div>
    </template>
  </div>
</template>

<style scoped>
.tj-ledger {
  --tj-label-w: 84px; /* 标签列宽（以最长标签右缘为标准） */
  overflow-y: auto;
  padding: 4px 8px 8px;
  background: var(--app-content-bg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: var(--app-shadow-card);
}
.tj-turn {
  position: relative;
  border-radius: var(--app-radius-sm);
  transition: opacity 0.15s;
}
.tj-turn.dimmed {
  opacity: 0.3;
}
.tj-turn-bar {
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: var(--tj-user);
  z-index: 2; /* 高于行 hover/selected 底，不被盖住 */
  display: none;
}
.tj-turn-bar.on {
  display: block;
}
/* 行：grid 对齐 —— 左留白列 + 标签列(右对齐到最长) + 文本列 + dur/tok */
.tj-cell {
  display: grid;
  grid-template-columns: 52px var(--tj-label-w) 1fr 64px 64px;
  align-items: center;
  gap: 8px;
  padding: 4px 8px 4px 10px;
  cursor: pointer;
  border-radius: var(--app-radius-sm);
  font-size: 12px;
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
.tj-cell:hover,
.tj-cell.selected {
  background: var(--app-bg); /* 选中行保持 hover 灰，高亮靠左侧高光条 */
}
.tj-turn-badge {
  justify-self: start;
  font-size: 10px;
  color: var(--app-text-muted);
  background: var(--app-bg);
  border-radius: var(--app-radius-sm);
  padding: 0 4px;
  line-height: 14px;
  white-space: nowrap;
}
.tj-turn-badge.on {
  color: var(--tj-user);
  background: var(--tj-user-bg);
}
.tj-cell-blank {
  content: '';
}
.tj-cell-label {
  justify-self: end; /* 右对齐到标签列右缘（最长标签标准） */
  width: max-content; /* 标签框按内容动态大小 */
  max-width: 100%;
  padding: 1px 8px;
  border-radius: var(--app-radius);
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
}
.tj-cell-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-main);
}
.tj-cell-dur,
.tj-cell-tok {
  text-align: right;
  color: var(--app-text-muted);
  font-size: 11px;
  white-space: nowrap;
}
/* Turns 收起省略行 */
.tj-fold {
  color: var(--app-text-muted);
}
.tj-fold-label {
  justify-self: end;
  background: transparent;
  color: var(--app-text-muted);
}
.tj-cell-fold {
  min-width: 0;
  font-size: 12px;
  color: var(--app-text-muted);
  opacity: 0.8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tj-empty {
  padding: 20px;
  text-align: center;
  color: var(--app-text-muted);
  font-size: 12px;
}
.mono {
  font-family: var(--app-font-mono);
}
/* 窄屏：所有标签收窄为同宽图标（彩色圆点），文本仍在标签右侧同起点 */
@media (max-width: 900px) {
  .tj-cell {
    grid-template-columns: 40px 20px 1fr 48px 48px;
  }
  .tj-cell-label,
  .tj-fold-label {
    justify-self: center;
    width: 16px;
    height: 16px;
    padding: 0;
    border-radius: 50%;
    font-size: 0;
  }
}
</style>

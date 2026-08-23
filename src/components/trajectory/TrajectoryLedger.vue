<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { TrajectoryCell, TrajectoryTurn } from '@/utils/trajectory'
import { cellMatches, kindBgColor, kindColor, kindLabel, turnStepsSummary } from '@/utils/trajectory'
import { formatDuration, formatTokens } from '@/utils/format'

/** 事件台账（docs/02 §6.3）：Turn → Group → Cell。
 * 标签左对齐列 + 文本列；轮次徽标在 USER 行左上、左侧窄高光条；
 * turnsOn 收起中间（省略行可单独展开）、callsOn 隐藏 TOOL；focusTurn 聚焦（其余变浅）。 */
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
    // 全部折叠/展开：控制分组折叠（轮次中间）
    collapsedGroups.value = all ? new Set(props.turns.flatMap((t) => t.groups.map((g) => `${t.index}:${g.step}`))) : new Set()
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
    const cells = [
      ...(t.userCell ? [t.userCell] : []),
      ...t.contextCells,
      ...t.groups.flatMap((g) => g.cells),
    ].filter(cellMatchesQuery)
    if (cells.length) out.push({ turn: t, cells })
  }
  return out
}

function isGroupCollapsed(t: TrajectoryTurn, step: number): boolean {
  return collapsedGroups.value.has(`${t.index}:${step}`)
}
function toggleGroup(t: TrajectoryTurn, step: number) {
  const key = `${t.index}:${step}`
  const s = new Set(collapsedGroups.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  collapsedGroups.value = s
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
          <span class="tj-cell-label" :style="labelStyle(c)">{{ kindLabel(c.kind) }}</span>
          <span class="tj-cell-text">{{ c.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(c.durationMs) }}</span>
          <span class="tj-cell-tok mono">{{ c.kind === 'message' ? formatTokens(c.tokenUsage) : '' }}</span>
        </div>
      </div>
      <div v-if="searchResults().length === 0" class="tj-empty">无匹配记录</div>
    </template>

    <!-- 普通模式：Turn →（USER/上下文）+（省略行 | 分组） -->
    <template v-else>
      <div
        v-for="t in turns"
        :key="t.index"
        class="tj-turn"
        :class="{ focused: focusTurn === t.index, dimmed: focusTurn != null && focusTurn !== t.index }"
      >
        <!-- 左侧窄高光条（选中/聚焦的 turn 显示，颜色随 USER） -->
        <span class="tj-turn-bar" :class="{ on: turnHasSelected(t) || focusTurn === t.index }" />

        <!-- USER 行：左上角 Turn N 徽标 -->
        <div v-if="t.userCell" class="tj-cell turn-user" :class="{ selected: t.userCell.index === selectedIndex }" @click="emit('select', t.userCell.index)">
          <span class="tj-turn-badge" :class="{ on: turnHasSelected(t) || focusTurn === t.index }">Turn {{ t.index }}</span>
          <span class="tj-cell-label" :style="labelStyle(t.userCell)">{{ kindLabel(t.userCell.kind) }}</span>
          <span class="tj-cell-text">{{ t.userCell.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(t.userCell.durationMs) }}</span>
          <span class="tj-cell-tok mono" />
        </div>

        <!-- CONTEXT 行 -->
        <div v-for="cc in t.contextCells" :key="cc.index" class="tj-cell" :class="{ selected: cc.index === selectedIndex }" @click="emit('select', cc.index)">
          <span class="tj-cell-label" :style="labelStyle(cc)">{{ kindLabel(cc.kind) }}</span>
          <span class="tj-cell-text">{{ cc.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(cc.durationMs) }}</span>
          <span class="tj-cell-tok mono" />
        </div>

        <!-- 中间：Turns 收起 → 省略行（可单独展开该 turn）；否则渲染分组 -->
        <template v-if="isTurnFolded(t)">
          <div v-if="t.groups.length" class="tj-cell tj-fold" @click="toggleFold(t.index)">
            <span class="tj-cell-label tj-fold-label">…</span>
            <span class="tj-cell-fold">{{ turnStepsSummary(t) }}</span>
            <span class="tj-cell-dur mono" />
            <span class="tj-cell-tok mono" />
          </div>
        </template>
        <template v-else>
          <div v-for="g in t.groups" :key="`${t.index}-${g.step}`" class="tj-group">
            <div class="tj-group-head" @click="toggleGroup(t, g.step)">
              <span class="tj-group-title">{{ g.title }}</span>
              <span class="tj-group-summary">{{ g.summary }}</span>
              <span class="tj-chevron mono">{{ isGroupCollapsed(t, g.step) ? '▸' : '▾' }}</span>
            </div>
            <template v-if="!isGroupCollapsed(t, g.step)">
              <div v-for="c in visibleGroupCells(g)" :key="c.index" class="tj-cell" :class="{ selected: c.index === selectedIndex }" @click="emit('select', c.index)">
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
  overflow-y: auto;
  padding: 4px 8px 8px;
  background: var(--app-content-bg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: var(--app-shadow-card);
}
/* 轮次容器：左侧窄高光条 + 聚焦时其余变浅 */
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
  background: var(--app-border);
  display: none;
}
.tj-turn-bar.on {
  display: block;
  background: var(--tj-user);
}
.tj-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 8px;
  cursor: pointer;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.tj-group-head:hover {
  background: var(--app-bg);
}
.tj-group-title {
  font-weight: 500;
}
.tj-group-summary {
  color: var(--app-text-muted);
  font-size: 11px;
}
.tj-chevron {
  margin-left: auto;
  color: var(--app-text-muted);
}
/* 行：标签列（固定宽左对齐）+ 文本列（右侧，间隔 8px）+ dur/tok */
.tj-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  cursor: pointer;
  border-radius: var(--app-radius-sm);
  font-size: 12px;
  /* 浏览器原生跳过屏外渲染（长台账），未渲染时按 ~36px 估算 */
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
.tj-cell:hover {
  background: var(--app-bg);
}
.tj-cell.selected {
  background: var(--app-bg); /* 选中行背景保持 hover 灰，高亮靠左侧高光条 */
}
.tj-turn-badge {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--app-text-muted);
  background: var(--app-bg);
  border-radius: var(--app-radius-sm);
  padding: 0 4px;
  line-height: 14px;
}
.tj-turn-badge.on {
  color: var(--tj-user);
  background: var(--tj-user-bg);
}
.tj-cell-label {
  width: 88px;
  flex-shrink: 0;
  text-align: left;
  padding: 1px 8px;
  border-radius: var(--app-radius);
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.tj-cell-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-main);
}
.tj-cell-dur,
.tj-cell-tok {
  width: 72px;
  flex-shrink: 0;
  text-align: right;
  color: var(--app-text-muted);
  font-size: 11px;
}
/* Turns 收起省略行：色号比标签浅 */
.tj-fold {
  color: var(--app-text-muted);
}
.tj-fold-label {
  width: 88px;
  background: transparent;
}
.tj-fold .tj-cell-fold {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: var(--app-text-muted);
  opacity: 0.8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
</style>

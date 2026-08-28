<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { TrajectoryCell, TrajectoryTurn } from '@/utils/trajectory'
import { cellMatches, kindBgColor, kindColor, kindLabel, turnStepsSummary } from '@/utils/trajectory'
import { formatDuration, formatTokens } from '@/utils/format'

/** 事件台账（docs/02 §6.3）：Turn → Group → Cell。
 * grid 对齐：左留白列(轮次徽标) + 标签列(右对齐到最长) + 文本列 + dur/tok；
 * 轮次徽标在 USER 行、左侧窄高光条（z 高于行底，hover/选中不遮挡）；
 * turnsOn 收起中间（省略行可单独展开）、callsOn 隐藏 TOOL；focusSet 聚焦区域（框内不变、外部变灰透明）、selectedIndex 单独选中（行高亮 + 轮次高光条）。
 * 不渲染 Step/Message 分组横条。 */
const props = defineProps<{
  turns: TrajectoryTurn[]
  query: string
  selectedIndex: number | null
  focusSet: Set<number>
  collapsedAll: boolean
  turnsOn: boolean
  callsOn: boolean
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

function kindShort(kind: TrajectoryCell['kind']): string {
  return { user: 'U', steering: 'S', context: 'C', message: 'A', tool: 'T', compacted: '∷' }[kind]
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

/** 该 turn 是否含「选中」cell（高光条 / 徽标着色）——按主选中判 */
function turnHasSelected(t: TrajectoryTurn): boolean {
  if (props.selectedIndex == null) return false
  if (t.userCell?.index === props.selectedIndex) return true
  if (t.contextCells.some((c) => c.index === props.selectedIndex)) return true
  return t.groups.some((g) => g.cells.some((c) => c.index === props.selectedIndex))
}

/** 该 turn 是否含「聚焦」cell（聚焦区域内 turn 的省略行不暗化） */
function turnHasFocus(t: TrajectoryTurn): boolean {
  if (props.focusSet.size === 0) return true
  if (t.userCell && props.focusSet.has(t.userCell.index)) return true
  if (t.contextCells.some((c) => props.focusSet.has(c.index))) return true
  return t.groups.some((g) => g.cells.some((c) => props.focusSet.has(c.index)))
}

/** cell 是否在聚焦区域外（聚焦时外部变灰透明） */
function isCellDimmed(index: number): boolean {
  return props.focusSet.size > 0 && !props.focusSet.has(index)
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

function onCellKeydown(e: KeyboardEvent) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  const current = e.currentTarget as HTMLElement
  const rows = Array.from(listRef.value?.querySelectorAll<HTMLButtonElement>('button.tj-cell') ?? [])
  const currentPosition = rows.indexOf(current as HTMLButtonElement)
  if (currentPosition < 0) return
  const nextPosition = currentPosition + (e.key === 'ArrowDown' ? 1 : -1)
  const next = rows[nextPosition]
  if (!next) return
  e.preventDefault()
  next.focus()
  const nextIndex = next.dataset.cellIndex
  if (nextIndex) emit('select', Number(nextIndex))
}
</script>

<template>
  <div ref="listRef" class="tj-ledger">
    <!-- 搜索模式：扁平命中行（Turn 头保留） -->
    <template v-if="hasQuery">
      <div v-for="{ turn, cells } in searchResults()" :key="`s-${turn.index}`" class="tj-turn">
        <button
          v-for="c in cells"
          :key="c.index"
          type="button"
          class="tj-cell"
          :class="{ selected: selectedIndex === c.index, 'focus-dim': isCellDimmed(c.index) }"
          :data-cell-index="c.index"
          :aria-current="selectedIndex === c.index ? 'true' : undefined"
          :aria-pressed="selectedIndex === c.index"
          @click="emit('select', c.index)"
          @keydown="onCellKeydown"
        >
          <span v-if="c.index === turn.userCell?.index" class="tj-turn-badge">Turn {{ turn.index }}</span>
          <span v-else class="tj-cell-blank" />
          <span class="tj-cell-label" :style="labelStyle(c)">
            <span class="tj-cell-label-full">{{ kindLabel(c.kind) }}</span>
            <span class="tj-cell-label-short" aria-hidden="true">{{ kindShort(c.kind) }}</span>
          </span>
          <span class="tj-cell-text">{{ c.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(c.durationMs) }}</span>
          <span class="tj-cell-tok mono">{{ c.kind === 'message' ? formatTokens(c.tokenUsage) : '' }}</span>
        </button>
      </div>
      <div v-if="searchResults().length === 0" class="tj-empty">无匹配记录</div>
    </template>

    <!-- 普通模式：Turn →（USER/上下文）+（省略行 | 分组 cells） -->
    <template v-else>
      <div v-for="t in turns" :key="t.index" class="tj-turn">
        <!-- 左侧窄高光条（z 高于行底，hover/选中不遮挡）；含选中 cell 即亮 -->
        <span class="tj-turn-bar" :class="{ on: turnHasSelected(t) }" />

        <button
          v-if="t.userCell"
          type="button"
          class="tj-cell turn-user"
          :class="{ selected: selectedIndex === t.userCell.index, 'focus-dim': isCellDimmed(t.userCell.index) }"
          :data-cell-index="t.userCell.index"
          :aria-current="selectedIndex === t.userCell.index ? 'true' : undefined"
          :aria-pressed="selectedIndex === t.userCell.index"
          @click="emit('select', t.userCell.index)"
          @keydown="onCellKeydown"
        >
          <span class="tj-turn-badge" :class="{ on: turnHasSelected(t) }">Turn {{ t.index }}</span>
          <span class="tj-cell-label" :style="labelStyle(t.userCell)">
            <span class="tj-cell-label-full">{{ kindLabel(t.userCell.kind) }}</span>
            <span class="tj-cell-label-short" aria-hidden="true">{{ kindShort(t.userCell.kind) }}</span>
          </span>
          <span class="tj-cell-text">{{ t.userCell.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(t.userCell.durationMs) }}</span>
          <span class="tj-cell-tok mono" />
        </button>

        <button
          v-for="cc in t.contextCells"
          :key="cc.index"
          type="button"
          class="tj-cell"
          :class="{ selected: selectedIndex === cc.index, 'focus-dim': isCellDimmed(cc.index) }"
          :data-cell-index="cc.index"
          :aria-current="selectedIndex === cc.index ? 'true' : undefined"
          :aria-pressed="selectedIndex === cc.index"
          @click="emit('select', cc.index)"
          @keydown="onCellKeydown"
        >
          <span class="tj-cell-blank" />
          <span class="tj-cell-label" :style="labelStyle(cc)">
            <span class="tj-cell-label-full">{{ kindLabel(cc.kind) }}</span>
            <span class="tj-cell-label-short" aria-hidden="true">{{ kindShort(cc.kind) }}</span>
          </span>
          <span class="tj-cell-text">{{ cc.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(cc.durationMs) }}</span>
          <span class="tj-cell-tok mono" />
        </button>

        <template v-if="isTurnFolded(t)">
          <button
            v-if="t.groups.length"
            type="button"
            class="tj-cell tj-fold"
            :class="{ 'focus-dim': !turnHasFocus(t) }"
            :aria-expanded="!isTurnFolded(t)"
            @click="toggleFold(t.index)"
            @keydown="onCellKeydown"
          >
            <span class="tj-cell-blank" />
            <span class="tj-cell-label tj-fold-label">…</span>
            <span class="tj-cell-fold">{{ turnStepsSummary(t) }}</span>
            <span class="tj-cell-dur mono" />
            <span class="tj-cell-tok mono" />
          </button>
        </template>
        <template v-else>
          <div v-for="g in t.groups" :key="`${t.index}-${g.step}`" class="tj-group">
            <template v-if="!isGroupCollapsed(t, g.step)">
              <button
                v-for="c in visibleGroupCells(g)"
                :key="c.index"
                type="button"
                class="tj-cell"
                :class="{ selected: selectedIndex === c.index, 'focus-dim': isCellDimmed(c.index) }"
                :data-cell-index="c.index"
                :aria-current="selectedIndex === c.index ? 'true' : undefined"
                :aria-pressed="selectedIndex === c.index"
                @click="emit('select', c.index)"
                @keydown="onCellKeydown"
              >
                <span class="tj-cell-blank" />
                <span class="tj-cell-label" :style="labelStyle(c)">
                  <span class="tj-cell-label-full">{{ kindLabel(c.kind) }}</span>
                  <span class="tj-cell-label-short" aria-hidden="true">{{ kindShort(c.kind) }}</span>
                </span>
                <span class="tj-cell-text">{{ c.text }}</span>
                <span class="tj-cell-dur mono">{{ formatDuration(c.durationMs) }}</span>
                <span class="tj-cell-tok mono">{{ c.kind === 'message' ? formatTokens(c.tokenUsage) : '' }}</span>
              </button>
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
  width: 100%;
  min-width: 0;
  cursor: pointer;
  border-radius: var(--app-radius-sm);
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: var(--app-font-size-sm);
  text-align: left;
  line-height: 1.35;
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
.tj-cell:hover,
.tj-cell.selected {
  background: var(--app-bg); /* 选中行保持 hover 灰，高亮靠左侧高光条 */
}
.tj-cell:focus-visible {
  position: relative;
  z-index: 3;
  outline: 2px solid var(--app-focus-ring);
  outline-offset: -2px;
}
/* 聚焦区域外：变灰透明（聚焦内容本身不变） */
.tj-cell.focus-dim {
  opacity: 0.35;
  filter: grayscale(0.7);
}
.tj-turn-badge {
  justify-self: start;
  font-size: var(--app-font-size-xs);
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
  font-size: var(--app-font-size-xs);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
}
.tj-cell-label-short {
  display: none;
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
  font-size: var(--app-font-size-xs);
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
  font-size: var(--app-font-size-sm);
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
  font-size: var(--app-font-size-sm);
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
  .tj-cell-label-short {
    display: inline;
    font-size: 11px;
    line-height: 16px;
    text-align: center;
  }
  .tj-cell-label-full {
    display: none;
  }
}
</style>

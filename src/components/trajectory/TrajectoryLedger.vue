<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { TokenUsage } from '@/types'
import type { TrajectoryCell, TrajectoryTurn } from '@/utils/trajectory'
import { cellMatches, kindColor, kindLabel } from '@/utils/trajectory'
import { formatDuration } from '@/utils/format'

/** 事件台账（docs/02 §6.3）：Turn → Group → Cell；折叠 / 搜索 / 行选中 */
const props = defineProps<{
  turns: TrajectoryTurn[]
  query: string
  selectedIndex: number | null
  collapsedAll: boolean
}>()
const emit = defineEmits<{ select: [index: number] }>()

const listRef = ref<HTMLElement | null>(null)
const collapsedTurns = ref(new Set<number>())
const collapsedGroups = ref(new Set<string>())

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
    if (all) {
      collapsedTurns.value = new Set(props.turns.map((t) => t.index))
      collapsedGroups.value = new Set(props.turns.flatMap((t) => t.groups.map((g) => `${t.index}:${g.step}`)))
    } else {
      collapsedTurns.value = new Set()
      collapsedGroups.value = new Set()
    }
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

function isTurnCollapsed(t: TrajectoryTurn): boolean {
  return collapsedTurns.value.has(t.index)
}
function isGroupCollapsed(t: TrajectoryTurn, step: number): boolean {
  return collapsedGroups.value.has(`${t.index}:${step}`)
}
function toggleTurn(t: TrajectoryTurn) {
  const s = new Set(collapsedTurns.value)
  if (s.has(t.index)) s.delete(t.index)
  else s.add(t.index)
  collapsedTurns.value = s
}
function toggleGroup(t: TrajectoryTurn, step: number) {
  const key = `${t.index}:${step}`
  const s = new Set(collapsedGroups.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  collapsedGroups.value = s
}

function formatTokens(u: TokenUsage | undefined): string {
  if (!u) return ''
  if (u.total_tokens != null) return `${u.total_tokens} tok`
  const p = u.prompt_tokens ?? 0
  const c = u.completion_tokens ?? 0
  return `${p}/${c} tok`
}
</script>

<template>
  <div ref="listRef" class="tj-ledger">
    <!-- 搜索模式：扁平命中行 -->
    <template v-if="hasQuery">
      <div v-for="{ turn, cells } in searchResults()" :key="`s-${turn.index}`" class="tj-turn">
        <div class="tj-turn-head">
          <span class="tj-turn-title">Turn {{ turn.index }}</span>
          <span class="tj-turn-summary">{{ turn.summary }}</span>
        </div>
        <div
          v-for="c in cells"
          :key="c.index"
          class="tj-cell"
          :class="{ selected: c.index === selectedIndex }"
          @click="emit('select', c.index)"
        >
          <span class="tj-cell-idx mono">#{{ c.index }}</span>
          <span class="tj-cell-pill" :style="{ background: kindColor(c.kind, c.isError) }">{{ kindLabel(c.kind) }}</span>
          <span class="tj-cell-text">{{ c.text }}</span>
          <span class="tj-cell-dur mono">{{ formatDuration(c.durationMs) }}</span>
          <span class="tj-cell-tok mono">{{ c.kind === 'message' ? formatTokens(c.tokenUsage) : '' }}</span>
        </div>
      </div>
      <div v-if="searchResults().length === 0" class="tj-empty">无匹配记录</div>
    </template>

    <!-- 普通模式：分组 + 折叠 -->
    <template v-else>
      <div v-for="t in turns" :key="t.index" class="tj-turn">
        <div class="tj-turn-head" @click="toggleTurn(t)">
          <span class="tj-turn-title">Turn {{ t.index }}</span>
          <span class="tj-turn-summary">{{ t.summary }}</span>
          <span class="tj-cols">耗时 · Tokens</span>
        </div>
        <template v-if="!isTurnCollapsed(t)">
          <div v-if="t.userCell" class="tj-cell" :class="{ selected: t.userCell.index === selectedIndex }" @click="emit('select', t.userCell.index)">
            <span class="tj-cell-idx mono">#{{ t.userCell.index }}</span>
            <span class="tj-cell-pill" :style="{ background: kindColor(t.userCell.kind, t.userCell.isError) }">{{ kindLabel(t.userCell.kind) }}</span>
            <span class="tj-cell-text">{{ t.userCell.text }}</span>
            <span class="tj-cell-dur mono">{{ formatDuration(t.userCell.durationMs) }}</span>
            <span class="tj-cell-tok mono" />
          </div>
          <div
            v-for="cc in t.contextCells"
            :key="cc.index"
            class="tj-cell"
            :class="{ selected: cc.index === selectedIndex }"
            @click="emit('select', cc.index)"
          >
            <span class="tj-cell-idx mono">#{{ cc.index }}</span>
            <span class="tj-cell-pill" :style="{ background: kindColor(cc.kind, cc.isError) }">{{ kindLabel(cc.kind) }}</span>
            <span class="tj-cell-text">{{ cc.text }}</span>
            <span class="tj-cell-dur mono">{{ formatDuration(cc.durationMs) }}</span>
            <span class="tj-cell-tok mono" />
          </div>
          <div v-for="g in t.groups" :key="`${t.index}-${g.step}`" class="tj-group">
            <div class="tj-group-head" @click="toggleGroup(t, g.step)">
              <span class="tj-group-title">{{ g.title }}</span>
              <span class="tj-group-summary">{{ g.summary }}</span>
              <span class="tj-chevron mono">{{ isGroupCollapsed(t, g.step) ? '▸' : '▾' }}</span>
            </div>
            <template v-if="!isGroupCollapsed(t, g.step)">
              <div
                v-for="c in g.cells"
                :key="c.index"
                class="tj-cell"
                :class="{ selected: c.index === selectedIndex }"
                @click="emit('select', c.index)"
              >
                <span class="tj-cell-idx mono">#{{ c.index }}</span>
                <span class="tj-cell-pill" :style="{ background: kindColor(c.kind, c.isError) }">{{ kindLabel(c.kind) }}</span>
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
}
.tj-turn-head {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--app-bg);
  border-bottom: 1px solid var(--app-border-light);
  cursor: pointer;
  font-size: 12px;
}
.tj-turn-title {
  font-weight: 600;
  color: var(--app-text-main);
}
.tj-turn-summary {
  color: var(--app-text-muted);
  font-size: 11px;
}
.tj-cols {
  margin-left: auto;
  color: var(--app-text-muted);
  font-size: 11px;
}
.tj-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
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
.tj-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 12px;
  /* 浏览器原生跳过屏外渲染（长台账），未渲染时按 ~36px 估算 */
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
.tj-cell:hover {
  background: var(--app-bg);
}
.tj-cell.selected {
  background: var(--el-color-primary-light-9);
}
.tj-cell-idx {
  width: 34px;
  flex-shrink: 0;
  color: var(--app-text-muted);
  text-align: right;
}
.tj-cell-pill {
  flex-shrink: 0;
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  min-width: 40px;
  text-align: center;
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

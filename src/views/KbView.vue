<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useKbStore } from '@/stores/kb'
import { formatBytes } from '@/utils/format'
import type { KbDocumentStatusDetail, KbSearchHit } from '@/types'
import KbUpload from '@/components/business/KbUpload.vue'
import ChunkStatus from '@/components/business/ChunkStatus.vue'
import AsyncState from '@/components/common/AsyncState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ResponsiveDialog from '@/components/common/ResponsiveDialog.vue'

/** 知识库管理（《02》前端设计 §4 / 《02》接口契约 §5.6）：集合管理 + 上传 + 分块/索引状态 + 检索测试 */
const kb = useKbStore()

const createVisible = ref(false)
const createName = ref('')
const searchVisible = ref(false)
const searchForm = reactive({ query: '', top_k: 5, hybrid: { semantic: 0.7, bm25: 0.3 } })
const searchResults = ref<KbSearchHit[]>([])
const searchLoading = ref(false)
const searchExecuted = ref(false)
const createSubmitting = ref(false)
const semanticWeight = computed({
  get: () => searchForm.hybrid.semantic,
  set: (value: number) => {
    searchForm.hybrid.semantic = value
    searchForm.hybrid.bm25 = Number((1 - value).toFixed(2))
  },
})

onMounted(() => void kb.listCollections())

async function onCreate() {
  if (!createName.value.trim()) return
  createSubmitting.value = true
  try {
    await kb.create(createName.value.trim())
    createName.value = ''
    createVisible.value = false
    ElMessage.success('集合已创建')
  } finally {
    createSubmitting.value = false
  }
}

async function onDeleteCollection(id: string) {
  await ElMessageBox.confirm('删除集合将级联删除其下文档，确认？', '删除确认', { type: 'warning' })
  await kb.remove(id)
}

async function runSearch() {
  if (!searchForm.query.trim() || !kb.currentCollectionId) return
  searchLoading.value = true
  searchExecuted.value = false
  try {
    searchResults.value = await kb.search({
      collection_ids: [kb.currentCollectionId],
      query: searchForm.query.trim(),
      top_k: searchForm.top_k,
      hybrid: searchForm.hybrid,
    })
    searchExecuted.value = true
  } finally {
    searchLoading.value = false
  }
}

function selectCollection(id: string) {
  void kb.select(id)
}

function onCollectionKeydown(e: KeyboardEvent, id: string) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    selectCollection(id)
    return
  }
  if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(e.key)) return
  const current = e.currentTarget as HTMLElement
  const items = Array.from(current.parentElement?.querySelectorAll<HTMLElement>('.kb-col-item') ?? [])
  const position = items.indexOf(current)
  const nextPosition = position + (e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : -1)
  const next = items[nextPosition]
  if (!next) return
  e.preventDefault()
  next.focus()
  const nextId = next.dataset.collectionId
  if (nextId) selectCollection(nextId)
}

/** ChunkStatus 轮询回传：合并 live 状态进 store 行（状态/分块数/操作按钮同源实时收敛） */
function onStatusChange(p: { id: string } & Partial<KbDocumentStatusDetail>) {
  const { id, ...patch } = p
  kb.patchDocument(id, patch)
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">知识库</h2>
        <p class="app-page-subtitle">集合管理 / 文档上传 / 分块索引 / 混合检索</p>
      </div>
      <div class="header-actions">
        <el-button :icon="'Search'" :disabled="!kb.currentCollectionId" @click="searchVisible = true">检索测试</el-button>
        <el-button type="primary" :icon="'FolderAdd'" @click="createVisible = true">新建集合</el-button>
      </div>
    </div>

    <div class="kb-layout">
      <!-- 集合树 -->
      <div class="kb-collections app-card" :aria-busy="kb.listStatus === 'loading'">
        <div v-if="kb.listStatus === 'loading' && !kb.collections.length" class="kb-list-loading" role="status">正在加载集合…</div>
        <div
          v-for="c in kb.collections"
          :key="c.id"
          class="kb-col-item"
          :class="{ active: c.id === kb.currentCollectionId }"
          role="button"
          tabindex="0"
          :data-collection-id="c.id"
          :aria-current="c.id === kb.currentCollectionId ? 'page' : undefined"
          @click="selectCollection(c.id)"
          @keydown="onCollectionKeydown($event, c.id)"
        >
          <el-icon><FolderOpened /></el-icon>
          <span class="kb-col-name">{{ c.name }}</span>
          <span class="kb-col-count">{{ c.document_count ?? 0 }}</span>
          <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'del' && onDeleteCollection(c.id)">
            <button type="button" class="kb-col-more" :aria-label="`集合 ${c.name} 更多操作`" @click.stop><el-icon><MoreFilled /></el-icon></button>
            <template #dropdown>
              <el-dropdown-menu><el-dropdown-item command="del">删除集合</el-dropdown-item></el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <EmptyState v-if="kb.listStatus !== 'loading' && kb.collections.length === 0" text="暂无集合" action-text="新建集合" @action="createVisible = true" />
      </div>

      <!-- 文档表 -->
      <div class="kb-docs app-card">
        <KbUpload :collection-id="kb.currentCollectionId ?? ''" @uploaded="() => kb.currentCollectionId && kb.listDocuments(kb.currentCollectionId)" />
        <AsyncState
          :status="kb.listStatus"
          :error-message="kb.errorMessage"
          :empty-text="kb.currentCollectionId ? '该集合暂无文档' : '请先新建或选择集合'"
          @retry="kb.retry"
        >
          <div class="app-table-wrap kb-table-wrap">
            <el-table :data="kb.documents" row-key="id" class="kb-table" size="small">
          <el-table-column prop="name" label="文档" min-width="180" />
          <el-table-column label="大小" width="90">
            <template #default="{ row }">{{ row.size ? formatBytes(row.size) : '-' }}</template>
          </el-table-column>
          <el-table-column label="分块/索引" width="200">
            <template #default="{ row }"><ChunkStatus :document="row" @status-change="onStatusChange" /></template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'indexed'"
                size="small"
                text
                type="primary"
                @click="kb.reindex(row.id)"
              >重索引</el-button>
              <el-button
                v-if="row.status === 'indexed'"
                size="small"
                text
                type="warning"
                @click="kb.archive(row.id)"
              >下线</el-button>
              <el-button size="small" text type="danger" @click="kb.removeDocument(row.id)">删除</el-button>
            </template>
          </el-table-column>
            </el-table>
          </div>
        </AsyncState>
      </div>
    </div>

    <ResponsiveDialog v-model="createVisible" title="新建集合" width="400px">
      <el-input v-model="createName" placeholder="集合名称" @keyup.enter="onCreate" />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" :disabled="createSubmitting" @click="onCreate">创建</el-button>
      </template>
    </ResponsiveDialog>

    <ResponsiveDialog v-model="searchVisible" title="混合检索测试" width="560px">
      <el-form label-width="80px">
        <el-form-item label="查询"><el-input v-model="searchForm.query" @keyup.enter="runSearch" /></el-form-item>
        <el-form-item label="Top K">
          <el-input-number v-model="searchForm.top_k" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="混合权重">
          <div class="hybrid">
            <span>语义 {{ Math.round(searchForm.hybrid.semantic * 100) }}%</span>
            <el-slider v-model="semanticWeight" :min="0" :max="1" :step="0.1" class="hybrid-slider" />
            <span>BM25 {{ Math.round(searchForm.hybrid.bm25 * 100) }}%</span>
          </div>
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="searchLoading" @click="runSearch">检索</el-button>
      <el-table v-if="searchResults.length" :data="searchResults" size="small" class="search-table">
        <el-table-column prop="text" label="片段" min-width="240" show-overflow-tooltip />
        <el-table-column prop="score" label="score" width="80" />
        <el-table-column prop="rerank_score" label="rerank" width="80" />
      </el-table>
      <el-empty v-else-if="searchVisible && !searchLoading" :description="searchExecuted ? '暂无匹配结果' : '执行检索查看结果'" :image-size="60" />
      <template #footer>
        <el-button @click="searchVisible = false">关闭</el-button>
      </template>
    </ResponsiveDialog>
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  gap: 8px;
}
.kb-layout {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 16px;
}
.kb-collections {
  width: 220px;
  flex-shrink: 0;
  padding: 8px;
  overflow-y: auto;
}
.kb-list-loading {
  padding: 12px 10px;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-sm);
}
.kb-col-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--app-radius);
  cursor: pointer;
  font-size: 13px;
}
.kb-col-item:focus-visible {
  outline: 2px solid var(--app-focus-ring);
  outline-offset: -2px;
}
.kb-col-item:hover {
  background: var(--app-bg);
}
.kb-col-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--app-primary);
  font-weight: 500;
}
.kb-col-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kb-col-count {
  color: var(--app-text-muted);
  font-size: 12px;
}
.kb-col-more {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--app-control-sm);
  height: var(--app-control-sm);
  padding: 0;
  border: 0;
  border-radius: var(--app-radius);
  background: transparent;
  cursor: pointer;
  color: var(--app-text-muted);
}
.kb-col-more:hover {
  background: var(--app-border-light);
  color: var(--app-text-main);
}
.kb-empty {
  text-align: center;
  color: var(--app-text-muted);
  padding: 20px 0;
  font-size: var(--app-font-size-sm);
}
.kb-docs {
  flex: 1;
  min-width: 0;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.kb-table {
  flex: 1;
}
.kb-table-wrap {
  min-height: 0;
}
.hybrid {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.hybrid-slider {
  flex: 1;
}
.search-table {
  margin-top: 12px;
}
@media (max-width: 768px) {
  .kb-layout {
    flex-direction: column;
    gap: 12px;
  }
  .kb-collections {
    width: 100%;
    max-height: 152px;
    display: flex;
    flex-wrap: wrap;
    align-content: flex-start;
    gap: 4px;
  }
  .kb-col-item {
    flex: 1 1 180px;
    min-width: 0;
  }
  .kb-docs {
    padding: 12px;
  }
}
@media (max-width: 480px) {
  .kb-col-item {
    flex-basis: 100%;
  }
  .kb-docs {
    padding: 8px;
  }
}
</style>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useKbStore } from '@/stores/kb'
import { formatBytes } from '@/utils/format'
import type { KbDocumentStatusDetail, KbSearchHit } from '@/types'
import KbUpload from '@/components/business/KbUpload.vue'
import ChunkStatus from '@/components/business/ChunkStatus.vue'

/** 知识库管理（docs/02 §4 / docs/03 §5.6）：集合管理 + 上传 + 分块/索引状态 + 检索测试 */
const kb = useKbStore()

const createVisible = ref(false)
const createName = ref('')
const searchVisible = ref(false)
const searchForm = reactive({ query: '', top_k: 5, hybrid: { semantic: 0.7, bm25: 0.3 } })
const searchResults = ref<KbSearchHit[]>([])
const searchLoading = ref(false)

onMounted(() => void kb.listCollections())

async function onCreate() {
  if (!createName.value.trim()) return
  await kb.create(createName.value.trim())
  createName.value = ''
  createVisible.value = false
  ElMessage.success('集合已创建')
}

async function onDeleteCollection(id: string) {
  await ElMessageBox.confirm('删除集合将级联删除其下文档，确认？', '删除确认', { type: 'warning' })
  await kb.remove(id)
}

async function runSearch() {
  if (!searchForm.query.trim() || !kb.currentCollectionId) return
  searchLoading.value = true
  try {
    searchResults.value = await kb.search({
      collection_ids: [kb.currentCollectionId],
      query: searchForm.query.trim(),
      top_k: searchForm.top_k,
      hybrid: searchForm.hybrid,
    })
  } finally {
    searchLoading.value = false
  }
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
      <div class="kb-collections app-card">
        <div
          v-for="c in kb.collections"
          :key="c.id"
          class="kb-col-item"
          :class="{ active: c.id === kb.currentCollectionId }"
          @click="kb.select(c.id)"
        >
          <el-icon><FolderOpened /></el-icon>
          <span class="kb-col-name">{{ c.name }}</span>
          <span class="kb-col-count">{{ c.document_count ?? 0 }}</span>
          <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'del' && onDeleteCollection(c.id)">
            <span class="kb-col-more" @click.stop><el-icon><MoreFilled /></el-icon></span>
            <template #dropdown>
              <el-dropdown-menu><el-dropdown-item command="del">删除集合</el-dropdown-item></el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div v-if="kb.collections.length === 0" class="kb-empty">暂无集合</div>
      </div>

      <!-- 文档表 -->
      <div class="kb-docs app-card">
        <KbUpload :collection-id="kb.currentCollectionId ?? ''" @uploaded="() => kb.currentCollectionId && kb.listDocuments(kb.currentCollectionId)" />
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
    </div>

    <el-dialog :model-value="createVisible" title="新建集合" width="400px" @close="createVisible = false">
      <el-input v-model="createName" placeholder="集合名称" @keyup.enter="onCreate" />
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="searchVisible" title="混合检索测试" width="560px" @close="searchVisible = false">
      <el-form label-width="80px">
        <el-form-item label="查询"><el-input v-model="searchForm.query" @keyup.enter="runSearch" /></el-form-item>
        <el-form-item label="Top K">
          <el-input-number v-model="searchForm.top_k" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="混合权重">
          <div class="hybrid">
            <span>语义 {{ Math.round(searchForm.hybrid.semantic * 100) }}%</span>
            <el-slider v-model="searchForm.hybrid.semantic" :min="0" :max="1" :step="0.1" class="hybrid-slider" />
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
      <el-empty v-else-if="searchVisible && !searchLoading" description="执行检索查看结果" :image-size="60" />
      <template #footer>
        <el-button @click="searchVisible = false">关闭</el-button>
      </template>
    </el-dialog>
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
  gap: 12px;
}
.kb-collections {
  width: 220px;
  flex-shrink: 0;
  padding: 8px;
  overflow-y: auto;
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
  display: flex;
  color: var(--app-text-muted);
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
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.kb-table {
  flex: 1;
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
</style>

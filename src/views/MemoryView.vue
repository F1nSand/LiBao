<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useMemoryStore } from '@/stores/memory'
import MemoryCardList from '@/components/business/MemoryCardList.vue'
import { listWorkspaces } from '@/api/workspace'
import { listProjectMemory } from '@/api/memory'
import { readWorkspaceFile } from '@/api/workspace'
import type { ProjectMemoryFile, Workspace } from '@/types'
import ResponsiveDialog from '@/components/common/ResponsiveDialog.vue'

/** 记忆管理（docs/02 §4 / docs/03 §5.7）：长期记忆卡片（RAG）+ 项目记忆文件（P5） */
const store = useMemoryStore()
const tab = ref('longterm')
const maintenanceLoading = ref(false)

// 项目记忆（P5：工作区 .agent/memory/*.md 索引；正文按需读取）
const workspaces = ref<Workspace[]>([])
const wsId = ref('')
const projectFiles = ref<ProjectMemoryFile[]>([])
const projectLoading = ref(false)
const fileContent = ref<{ title: string; content: string } | null>(null)
const dialogVisible = ref(false)
const contentLoading = ref(false)

onMounted(() => {
  void store.listLongterm()
})

watch(tab, (v) => {
  if (v === 'project' && workspaces.value.length === 0) {
    void loadWorkspaces()
  }
})

async function loadWorkspaces() {
  try {
    const res = await listWorkspaces({ page: 1, page_size: 100 })
    workspaces.value = res.items ?? []
    if (workspaces.value.length > 0) {
      wsId.value = workspaces.value[0].id
      void loadProjectMemory()
    }
  } catch {
    ElMessage.error('工作区列表加载失败')
  }
}

async function loadProjectMemory() {
  if (!wsId.value) return
  projectLoading.value = true
  try {
    projectFiles.value = await listProjectMemory(wsId.value)
  } catch {
    ElMessage.error('项目记忆加载失败')
  } finally {
    projectLoading.value = false
  }
}

watch(wsId, () => void loadProjectMemory())

async function onViewFile(file: ProjectMemoryFile) {
  contentLoading.value = true
  try {
    const res = await readWorkspaceFile(wsId.value, file.path)
    fileContent.value = { title: file.title, content: res.content ?? '' }
    dialogVisible.value = true
  } catch {
    ElMessage.error('文件读取失败')
  } finally {
    contentLoading.value = false
  }
}

async function onMaintenance() {
  maintenanceLoading.value = true
  try {
    const res = await store.maintenance()
    ElMessage.success(res.summary)
  } finally {
    maintenanceLoading.value = false
  }
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">记忆</h2>
        <p class="app-page-subtitle">长期记忆（RAG 检索）与项目记忆（md 文件）</p>
      </div>
      <el-button
        v-if="tab === 'longterm'"
        :icon="'MagicStick'"
        :loading="maintenanceLoading"
        @click="onMaintenance"
      >
        触发整理
      </el-button>
    </div>

    <el-tabs v-model="tab" class="memory-tabs">
      <el-tab-pane label="长期记忆" name="longterm">
        <MemoryCardList />
      </el-tab-pane>
      <el-tab-pane label="项目记忆" name="project">
        <div class="project-header">
          <el-select v-model="wsId" placeholder="选择工作区" style="width: 280px" :loading="projectLoading">
            <el-option v-for="ws in workspaces" :key="ws.id" :label="ws.name" :value="ws.id" />
          </el-select>
          <el-button :icon="'Refresh'" :loading="projectLoading" @click="loadProjectMemory">刷新</el-button>
        </div>
        <el-empty v-if="!projectLoading && projectFiles.length === 0" description="暂无项目记忆（对话中沉淀的项目决策/迭代细节会出现在这里）" />
        <div v-else class="project-list">
          <el-card v-for="f in projectFiles" :key="f.path" class="project-card" shadow="never">
            <template #header>
              <div class="project-card-header">
                <span class="project-title">{{ f.title }}</span>
                <el-tag size="small" type="info">{{ f.type }}</el-tag>
              </div>
            </template>
            <p class="project-summary">{{ f.summary }}</p>
            <div class="project-meta">
              <span v-if="f.tags.length" class="mono">tags: {{ f.tags.join(', ') }}</span>
              <span v-if="f.updated_at" class="mono">更新: {{ f.updated_at }}</span>
              <el-button link type="primary" size="small" @click="onViewFile(f)">查看全文</el-button>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <ResponsiveDialog v-model="dialogVisible" :title="fileContent?.title ?? ''" width="640px">
      <pre class="file-content">{{ fileContent?.content }}</pre>
    </ResponsiveDialog>
  </div>
</template>

<style scoped>
.memory-tabs {
  flex: 1;
  min-height: 0;
}
.project-header {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.project-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.project-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.project-title {
  font-weight: 600;
}
.project-summary {
  margin: 0 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.project-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.file-content {
  margin: 0;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  font-family: var(--app-font-mono);
  font-size: 13px;
  line-height: 1.6;
}
@media (max-width: 480px) {
  .project-header :deep(.el-select) {
    width: 100% !important;
  }
  .project-header :deep(.el-button) {
    min-height: var(--app-control-touch);
  }
}
</style>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore } from '@/stores/workspace'
import WorkspaceCard from '@/components/workspace/WorkspaceCard.vue'
import AsyncState from '@/components/common/AsyncState.vue'
import ResponsiveDialog from '@/components/common/ResponsiveDialog.vue'

/** 工作区气泡网格（M7-B，《02》前端设计 §4）：一泡一个工作区 + 新建/编辑气泡内容/进入 */
const store = useWorkspaceStore()
const createVisible = ref(false)
const createSubmitting = ref(false)
const form = reactive({ name: '', description: '' })

onMounted(() => void store.list())

async function onCreate() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入工作区名称')
    return
  }
  createSubmitting.value = true
  try {
    await store.create({ name: form.name.trim(), description: form.description.trim() || undefined })
    createVisible.value = false
    Object.assign(form, { name: '', description: '' })
    ElMessage.success('工作区已创建')
  } finally {
    createSubmitting.value = false
  }
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">工作区</h2>
        <p class="app-page-subtitle">本地文件夹 + 项目级 Agent 增量 · 文件资源管理器 / 工作区对话（M7-B）</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" :icon="'Plus'" @click="createVisible = true">新建工作区</el-button>
      </div>
    </div>

    <AsyncState
      :status="store.unavailable ? 'unavailable' : store.status"
      :error-message="store.errorMessage"
      empty-text="暂无工作区，点击右上角新建"
      empty-action-text="新建工作区"
      unavailable-text="后端暂未实现工作区接口（M7-B 契约已发交接板）"
      @retry="store.retry"
      @action="createVisible = true"
    >
      <div>
        <TransitionGroup name="ws-card" tag="div" class="ws-grid">
          <WorkspaceCard v-for="w in store.workspaces" :key="w.id" :workspace="w" />
        </TransitionGroup>
      </div>
    </AsyncState>

    <ResponsiveDialog v-model="createVisible" title="新建工作区" width="440px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如 产品文档" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="气泡显示内容（可编辑）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" :disabled="createSubmitting" @click="onCreate">创建</el-button>
      </template>
    </ResponsiveDialog>
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  gap: 8px;
}
.ws-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  align-content: start;
}
@media (max-width: 480px) {
  .ws-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }
}
/* 卡片增删过渡（emil：enter scale+fade 0.18s ease-out，leave 快 0.15s；频繁增删用 transition 可中断） */
.ws-card-enter-active {
  transition: opacity 0.18s var(--ease-out), transform 0.18s var(--ease-out);
}
.ws-card-enter-from {
  opacity: 0;
  transform: scale(0.96) translateY(4px);
}
.ws-card-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.ws-card-leave-to {
  opacity: 0;
  transform: scale(0.96);
}
.ws-card-move {
  transition: transform 0.18s var(--ease-out);
}
</style>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore } from '@/stores/workspace'
import EmptyState from '@/components/common/EmptyState.vue'
import WorkspaceCard from '@/components/workspace/WorkspaceCard.vue'

/** 工作区气泡网格（M7-B，docs/02 §4）：一泡一个工作区 + 新建/编辑气泡内容/进入 */
const store = useWorkspaceStore()
const createVisible = ref(false)
const form = reactive({ name: '', description: '' })

onMounted(() => void store.list())

async function onCreate() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入工作区名称')
    return
  }
  await store.create({ name: form.name.trim(), description: form.description.trim() || undefined })
  createVisible.value = false
  Object.assign(form, { name: '', description: '' })
  ElMessage.success('工作区已创建')
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

    <template v-if="!store.unavailable">
      <div v-loading="store.loading" class="ws-grid">
        <WorkspaceCard v-for="w in store.workspaces" :key="w.id" :workspace="w" />
      </div>
      <el-empty
        v-if="!store.loading && store.workspaces.length === 0"
        description="暂无工作区，点击右上角新建"
        :image-size="60"
      />
    </template>
    <EmptyState v-else text="后端暂未实现工作区接口（M7-B 契约已发交接板）" />

    <el-dialog :model-value="createVisible" title="新建工作区" width="440px" @close="createVisible = false">
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
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
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
</style>

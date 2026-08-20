<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listWorkspaceFiles,
  readWorkspaceFile,
  writeWorkspaceFile,
  deleteWorkspaceFile,
} from '@/api/workspace'
import type { WorkspaceFile } from '@/types'

/** 工作区资源管理器（M7-B）：el-tree 懒加载文件树 + 预览/编辑/保存 + 新建/删除（path 相对 root） */
const props = defineProps<{ workspaceId: string }>()

const treeRef = ref()
const previewVisible = ref(false)
const previewPath = ref('')
const previewContent = ref('')
const newVisible = ref(false)
const newForm = reactive({ path: '', content: '' })

async function loadNode(node: { level: number; data?: WorkspaceFile }, resolve: (data: WorkspaceFile[]) => void) {
  const path = node.level === 0 ? '' : node.data!.path
  try {
    resolve(await listWorkspaceFiles(props.workspaceId, path))
  } catch {
    resolve([])
  }
}

async function onFileClick(data: WorkspaceFile) {
  if (data.is_dir) return // 目录只负责展开
  const res = await readWorkspaceFile(props.workspaceId, data.path)
  previewPath.value = data.path
  previewContent.value = res.content
  previewVisible.value = true
}

async function saveFile() {
  await writeWorkspaceFile(props.workspaceId, { path: previewPath.value, content: previewContent.value })
  previewVisible.value = false
  ElMessage.success('已保存')
}

async function onDelete(data: WorkspaceFile) {
  await ElMessageBox.confirm(`删除文件「${data.path}」？`, '删除确认', { type: 'warning' })
  await deleteWorkspaceFile(props.workspaceId, data.path)
  treeRef.value?.remove(data.path)
  ElMessage.success('已删除')
}

async function createFile() {
  const path = newForm.path.trim()
  if (!path) {
    ElMessage.warning('请输入文件路径')
    return
  }
  await writeWorkspaceFile(props.workspaceId, { path, content: newForm.content })
  newVisible.value = false
  Object.assign(newForm, { path: '', content: '' })
  treeRef.value?.reload()
  ElMessage.success('已创建')
}
</script>

<template>
  <div class="rm-root">
    <div class="rm-head">
      <span class="rm-title">文件</span>
      <el-button size="small" :icon="'DocumentAdd'" title="新建文件" @click="newVisible = true">新建</el-button>
    </div>
    <div class="rm-tree-wrap">
      <el-tree
        ref="treeRef"
        lazy
        node-key="path"
        :props="{ label: 'name', isLeaf: (d: WorkspaceFile) => !d.is_dir }"
        :load="loadNode"
        :expand-on-click-node="false"
        @node-click="onFileClick"
      >
        <template #default="{ data }">
          <span class="rm-node">
            <el-icon :size="14"><component :is="data.is_dir ? 'Folder' : 'Document'" /></el-icon>
            <span class="rm-node-name">{{ data.name }}</span>
            <el-button
              v-if="!data.is_dir"
              size="small"
              text
              type="danger"
              class="rm-del"
              @click.stop="onDelete(data)"
            >删</el-button>
          </span>
        </template>
      </el-tree>
    </div>

    <!-- 文件预览/编辑 -->
    <el-dialog :model-value="previewVisible" :title="`预览 / 编辑：${previewPath}`" width="560px" @close="previewVisible = false">
      <el-input
        v-model="previewContent"
        type="textarea"
        :rows="12"
        class="mono"
        placeholder="文件内容"
      />
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
        <el-button type="primary" @click="saveFile">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建文件 -->
    <el-dialog :model-value="newVisible" title="新建文件" width="520px" @close="newVisible = false">
      <el-form label-width="80px">
        <el-form-item label="路径" required>
          <el-input v-model="newForm.path" placeholder="如 docs/新文档.md（相对工作区根目录）" class="mono" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="newForm.content" type="textarea" :rows="6" placeholder="文件内容" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newVisible = false">取消</el-button>
        <el-button type="primary" @click="createFile">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.rm-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.rm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 6px;
  flex-shrink: 0;
}
.rm-title {
  font-weight: 600;
  color: var(--app-text-main);
  font-size: 12px;
}
.rm-tree-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 8px 12px;
}
.rm-node {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  width: 100%;
}
.rm-node-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rm-del {
  opacity: 0;
  flex-shrink: 0;
}
.rm-node:hover .rm-del {
  opacity: 1;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { listWorkspaceFiles } from '@/api/workspace'
import type { FileRef, WorkspaceFile } from '@/types'

/** 引用工作区文件选择器（M7-B）：mini el-tree 懒加载多选，确认后 emit 叶子文件的 FileRef[] */
const props = defineProps<{ visible: boolean; workspaceId: string }>()
const emit = defineEmits<{
  'update:visible': [v: boolean]
  confirm: [refs: FileRef[]]
}>()

const treeRef = ref()

async function loadNode(node: { level: number; data?: WorkspaceFile }, resolve: (data: WorkspaceFile[]) => void) {
  const path = node.level === 0 ? '' : node.data!.path
  try {
    resolve(await listWorkspaceFiles(props.workspaceId, path))
  } catch {
    resolve([])
  }
}

function confirm() {
  // 只取叶子文件（目录不是引用对象）
  const leaves = (treeRef.value?.getCheckedNodes(true) ?? []) as WorkspaceFile[]
  emit('confirm', leaves.filter((f) => !f.is_dir).map((f) => ({ path: f.path })))
  close()
}

function clearSelection() {
  treeRef.value?.setCheckedKeys?.([])
}

function close() {
  clearSelection()
  emit('update:visible', false)
}

watch(() => props.visible, (visible) => {
  if (!visible) clearSelection()
})
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="引用工作区文件"
    width="460px"
    @close="close"
  >
    <el-tree
      ref="treeRef"
      lazy
      show-checkbox
      node-key="path"
      :props="{ label: 'name', isLeaf: (d: WorkspaceFile) => !d.is_dir }"
      :load="loadNode"
      class="ws-ref-tree"
    >
      <template #default="{ data }">
        <span class="ws-ref-node">
          <el-icon :size="14"><component :is="data.is_dir ? 'Folder' : 'Document'" /></el-icon>
          <span>{{ data.name }}</span>
        </span>
      </template>
    </el-tree>
    <div class="ws-ref-hint">勾选要引用的文件（目录不参与引用），随消息发送给工作区 Agent 读取内容</div>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" @click="confirm">引用</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.ws-ref-tree {
  max-height: 320px;
  overflow-y: auto;
}
.ws-ref-node {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
}
.ws-ref-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--app-text-muted);
}
</style>

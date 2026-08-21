<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listWorkspaceFiles,
  readWorkspaceFile,
  writeWorkspaceFile,
  deleteWorkspaceFile,
  getWorkspace,
  revealWorkspace,
} from '@/api/workspace'
import { isNotImplementedError } from '@/utils/http-envelope'
import { useTaskPoll } from '@/composables/useTaskPoll'
import { refreshExpandedTree } from '@/utils/workspace-tree'
import type { WorkspaceFile } from '@/types'

/**
 * 工作区资源管理器（M7-B，docs/02 §4）：el-tree 懒加载文件树 + 预览/编辑/保存 + 新建/删除（path 相对 root）。
 * 增强（2026-08-21）：可折叠（窄条保留）＋定时轮询文件树（外部更新同步可见，折叠时暂停）＋打开本地文件夹（reveal，后端未实现降级复制路径）。
 */
const props = defineProps<{ workspaceId: string }>()

const treeRef = ref()
const previewVisible = ref(false)
const previewPath = ref('')
const previewContent = ref('')
const newVisible = ref(false)
const newForm = reactive({ path: '', content: '' })

/** 折叠（窄条保留，VS Code 风格）：折叠成 28px 竖条，暂停文件树轮询 */
const collapsed = ref(false)
/** 预览编辑防覆盖：用户正在输入/聚焦时不轮询重读 */
const previewDirty = ref(false)
const previewFocused = ref(false)

/** 本地根路径（打开文件夹按钮 title + 降级复制用；后端未实现 reveal 时兜底展示） */
const rootPath = ref<string | undefined>()

onMounted(() => {
  void getWorkspace(props.workspaceId)
    .then((w) => (rootPath.value = w.root_path))
    .catch(() => undefined) // 预取失败不阻塞（降级路径再查）
})

/** 轮询刷新：保展开文件树 + 预览安全重读（e2e fast 模式缩短间隔，见 .env.e2e） */
async function refreshAll() {
  const tree = treeRef.value
  if (!tree) return
  await refreshExpandedTree(tree)
  if (previewVisible.value && !previewDirty.value && !previewFocused.value && previewPath.value) {
    try {
      const res = await readWorkspaceFile(props.workspaceId, previewPath.value)
      previewContent.value = res.content
    } catch {
      // 文件被外部删除等情况：静默，保持当前内容
    }
  }
}

const FAST = import.meta.env.VITE_MOCK_FAST === '1'
useTaskPoll(refreshAll, {
  intervalMs: FAST ? 500 : 3000,
  enabled: computed(() => !collapsed.value),
})

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
  previewDirty.value = false
  previewVisible.value = true
}

async function saveFile() {
  await writeWorkspaceFile(props.workspaceId, { path: previewPath.value, content: previewContent.value })
  previewVisible.value = false
  previewDirty.value = false
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
  await refreshExpandedTree(treeRef.value) // 修复 el-tree 无 reload() 的静默 no-op，立即刷新
  ElMessage.success('已创建')
}

/** 打开本地文件夹：reveal 成功；后端未实现（404）→ 降级复制 root_path */
async function onReveal() {
  try {
    await revealWorkspace(props.workspaceId)
    ElMessage.success('已请求在本地打开文件夹')
  } catch (e) {
    if (isNotImplementedError(e)) {
      const w = rootPath.value ? { root_path: rootPath.value } : await getWorkspace(props.workspaceId).catch(() => null)
      const rp = w?.root_path
      if (rp) {
        try {
          if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(rp)
          ElMessage.info(`后端未实现本地打开，已复制路径：${rp}`)
        } catch {
          ElMessage.info(`后端未实现本地打开，路径：${rp}`)
        }
      } else {
        ElMessage.warning('该工作区无本地路径，无法打开')
      }
    } else {
      throw e
    }
  }
}
</script>

<template>
  <div class="rm-root" :class="{ collapsed }">
    <div v-show="!collapsed" class="rm-head">
      <div class="rm-head-left">
        <el-button text class="rm-toggle" title="折叠文件面板" :icon="'Fold'" @click="collapsed = true" />
        <span class="rm-title">文件</span>
      </div>
      <div class="rm-head-right">
        <el-button size="small" :icon="'DocumentAdd'" title="新建文件" @click="newVisible = true">新建</el-button>
        <el-button
          size="small"
          :icon="'FolderOpened'"
          :title="`打开本地文件夹${rootPath ? '：' + rootPath : ''}`"
          @click="onReveal"
        />
      </div>
    </div>

    <div v-show="!collapsed" class="rm-tree-wrap">
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

    <button v-show="collapsed" class="rm-strip" type="button" title="展开文件面板" @click="collapsed = false">
      <el-icon :size="18"><Expand /></el-icon>
    </button>

    <!-- 文件预览/编辑 -->
    <el-dialog :model-value="previewVisible" :title="`预览 / 编辑：${previewPath}`" width="560px" @close="previewVisible = false; previewDirty = false">
      <el-input
        v-model="previewContent"
        type="textarea"
        :rows="12"
        class="mono"
        placeholder="文件内容"
        @input="previewDirty = true"
        @focus="previewFocused = true"
        @blur="previewFocused = false"
      />
      <template #footer>
        <el-button @click="previewVisible = false; previewDirty = false">关闭</el-button>
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
  width: 260px;
  transition: width 0.2s ease;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.rm-root.collapsed {
  width: 28px;
}
.rm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 6px;
  flex-shrink: 0;
}
.rm-head-left,
.rm-head-right {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.rm-title {
  font-weight: 600;
  color: var(--app-text-main);
  font-size: 12px;
  white-space: nowrap;
}
.rm-toggle {
  padding: 4px;
  color: var(--app-text-muted);
}
.rm-toggle:hover {
  color: var(--app-primary);
}
.rm-tree-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 8px 12px;
}
.rm-strip {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--app-text-muted);
}
.rm-strip:hover {
  color: var(--app-primary);
  background: var(--app-bg);
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

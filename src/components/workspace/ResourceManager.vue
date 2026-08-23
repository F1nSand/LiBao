<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listWorkspaceFiles,
  readWorkspaceFile,
  writeWorkspaceFile,
  deleteWorkspaceFile,
  renameWorkspaceFile,
  createWorkspaceDir,
  getWorkspace,
  revealWorkspace,
} from '@/api/workspace'
import { isNotImplementedError } from '@/utils/http-envelope'
import { useTaskPoll } from '@/composables/useTaskPoll'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { NARROW_LAYOUT_MQ } from '@/constants/layout'
import { collectLoadedPaths, refreshExpandedTree, signatureOf } from '@/utils/workspace-tree'
import type { WorkspaceFile } from '@/types'

/**
 * 工作区资源管理器（M7-B，docs/02 §4）：el-tree 懒加载文件树 + 预览/编辑/保存。
 * 增强（2026-08-21）：折叠（窄条保留）+ 轮询同步（签名对比防闪烁）+ 打开本地文件夹 + 行尾「三个点」菜单
 * （重命名/删除；文件夹额外：新建文件/新建文件夹）+ 顶部新建文件/文件夹 + 新建文件默认 .txt。
 */
const props = defineProps<{ workspaceId: string }>()

const treeRef = ref()
const previewVisible = ref(false)
const previewPath = ref('')
const previewContent = ref('')
const previewDirty = ref(false)
const previewFocused = ref(false)

/** 折叠（窄条保留，VS Code 风格）：折叠成 28px 竖条，暂停文件树轮询。
 * 窗口变窄（≤960px）自动收起；变宽自动展开——用户手动点汉堡收起过的不自动展开。 */
const userCollapsed = ref(false)
const isNarrow = useMediaQuery(NARROW_LAYOUT_MQ)
const collapsed = computed(() => isNarrow.value || userCollapsed.value)
/** 本地根路径（打开文件夹按钮 title + 降级复制用） */
const rootPath = ref<string | undefined>()

/** 新建文件/文件夹/重命名 弹窗 */
const newFileVisible = ref(false)
const newFileForm = reactive({ name: '', content: '' })
const newFileDir = ref('') // 目标父目录（菜单新建 → 当前文件夹；顶部新建 → 根）
const newDirVisible = ref(false)
const newDirForm = reactive({ name: '' })
const newDirTarget = ref('')
const renameVisible = ref(false)
const renameForm = reactive({ oldPath: '', name: '' })

onMounted(() => {
  void getWorkspace(props.workspaceId)
    .then((w) => (rootPath.value = w.root_path))
    .catch(() => undefined)
})

/** 数据变化检测缓存：各可见层签名（对比通过则跳过刷新，消除无谓重建闪烁） */
const layerSignatures = new Map<string, string>()
let cacheInitialized = false

async function refreshAll() {
  const tree = treeRef.value
  if (!tree) return
  let changed = false
  for (const path of collectLoadedPaths(tree)) {
    const files = await listWorkspaceFiles(props.workspaceId, path).catch(() => null)
    if (!files) continue
    const sig = signatureOf(files)
    if (!cacheInitialized) layerSignatures.set(path, sig)
    else if (layerSignatures.has(path) && layerSignatures.get(path) !== sig) {
      layerSignatures.set(path, sig)
      changed = true
    } else if (!layerSignatures.has(path)) {
      layerSignatures.set(path, sig)
    }
  }
  cacheInitialized = true
  if (changed) await refreshExpandedTree(tree)
  if (previewVisible.value && !previewDirty.value && !previewFocused.value && previewPath.value) {
    try {
      const res = await readWorkspaceFile(props.workspaceId, previewPath.value)
      previewContent.value = res.content
    } catch {
      // 文件被外部删除：静默保持当前内容
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
  if (data.is_dir) return
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

/** 行尾菜单（三连）分派：重命名/删除/文件夹内新建文件/文件夹 */
async function onMenu(cmd: string, data: WorkspaceFile) {
  if (cmd === 'rename') openRename(data)
  else if (cmd === 'new-file') openNewFile(data.path)
  else if (cmd === 'new-dir') openNewDir(data.path)
  else if (cmd === 'delete') await onDelete(data)
}

/** 顶部「新建」dropdown：文件/文件夹 */
function onTopCreate(cmd: string) {
  if (cmd === 'file') openNewFile('')
  else if (cmd === 'dir') openNewDir('')
}

function parentOf(path: string): string {
  const i = path.lastIndexOf('/')
  return i === -1 ? '' : path.slice(0, i)
}

/** 新建文件（默认 .txt：无后缀自动补） */
function openNewFile(dir: string) {
  newFileDir.value = dir
  Object.assign(newFileForm, { name: '', content: '' })
  newFileVisible.value = true
}
async function createFile() {
  let name = newFileForm.name.trim()
  if (!name) {
    ElMessage.warning('请输入文件名')
    return
  }
  if (!/\.\w+$/.test(name)) name += '.txt'
  const path = newFileDir.value ? `${newFileDir.value}/${name}` : name
  await writeWorkspaceFile(props.workspaceId, { path, content: newFileForm.content })
  newFileVisible.value = false
  await refreshExpandedTree(treeRef.value)
  ElMessage.success('已创建')
}

/** 新建文件夹（默认当前目录下子目录） */
function openNewDir(dir: string) {
  newDirTarget.value = dir
  newDirForm.name = ''
  newDirVisible.value = true
}
async function createDir() {
  const name = newDirForm.name.trim()
  if (!name) {
    ElMessage.warning('请输入文件夹名')
    return
  }
  const path = newDirTarget.value ? `${newDirTarget.value}/${name}` : name
  try {
    await createWorkspaceDir(props.workspaceId, path)
    newDirVisible.value = false
    await refreshExpandedTree(treeRef.value)
    ElMessage.success('已创建文件夹')
  } catch (e) {
    if (isNotImplementedError(e)) {
      ElMessage.warning('后端未实现新建文件夹接口')
      newDirVisible.value = false
    } else {
      throw e
    }
  }
}

/** 重命名文件/文件夹 */
function openRename(data: WorkspaceFile) {
  renameForm.oldPath = data.path
  renameForm.name = data.name
  renameVisible.value = true
}
async function renameFile() {
  const newName = renameForm.name.trim()
  if (!newName) {
    ElMessage.warning('请输入新名称')
    return
  }
  const parent = parentOf(renameForm.oldPath)
  const newPath = parent ? `${parent}/${newName}` : newName
  if (newPath === renameForm.oldPath) {
    renameVisible.value = false
    return
  }
  try {
    await renameWorkspaceFile(props.workspaceId, { old_path: renameForm.oldPath, new_path: newPath })
    renameVisible.value = false
    await refreshExpandedTree(treeRef.value)
    ElMessage.success('已重命名')
  } catch (e) {
    if (isNotImplementedError(e)) {
      ElMessage.warning('后端未实现重命名接口')
      renameVisible.value = false
    } else {
      throw e
    }
  }
}

/** 删除文件/目录（目录递归；强确认弹窗） */
async function onDelete(data: WorkspaceFile) {
  if (data.is_dir) {
    await ElMessageBox.confirm(`删除目录「${data.path}」及其全部内容？不可恢复。`, '删除目录', { type: 'warning' })
  } else {
    await ElMessageBox.confirm(`删除文件「${data.path}」？`, '删除确认', { type: 'warning' })
  }
  try {
    await deleteWorkspaceFile(props.workspaceId, data.path)
    treeRef.value?.remove(data.path)
    ElMessage.success('已删除')
  } catch (e) {
    if (isNotImplementedError(e)) {
      ElMessage.warning('后端未实现删除接口')
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
        <el-button text class="rm-toggle" title="折叠文件面板" :icon="'Fold'" @click="userCollapsed = true" />
        <span class="rm-title">文件</span>
      </div>
      <div class="rm-head-right">
        <el-dropdown trigger="click" @command="onTopCreate">
          <el-button size="small" :icon="'Plus'">新建</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="file">新建文件</el-dropdown-item>
              <el-dropdown-item command="dir">新建文件夹</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
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
            <el-dropdown trigger="click" @command="(cmd: string) => onMenu(cmd, data)">
              <span class="rm-more" title="更多操作" @click.stop><el-icon :size="14"><MoreFilled /></el-icon></span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item v-if="data.is_dir" command="new-file">新建文件</el-dropdown-item>
                  <el-dropdown-item v-if="data.is_dir" command="new-dir">新建文件夹</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </span>
        </template>
      </el-tree>
    </div>

    <button v-show="collapsed" class="rm-strip" type="button" title="展开文件面板" @click="userCollapsed = false">
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

    <!-- 新建文件（默认 .txt） -->
    <el-dialog :model-value="newFileVisible" :title="`新建文件${newFileDir ? ' 于 ' + newFileDir : ''}`" width="480px" @close="newFileVisible = false">
      <el-form label-width="80px">
        <el-form-item label="文件名" required>
          <el-input v-model="newFileForm.name" placeholder="如 入门指南（无后缀默认 .txt）" class="mono" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="newFileForm.content" type="textarea" :rows="6" placeholder="文件内容" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newFileVisible = false">取消</el-button>
        <el-button type="primary" @click="createFile">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新建文件夹（默认当前目录下子目录） -->
    <el-dialog :model-value="newDirVisible" :title="`新建文件夹${newDirTarget ? ' 于 ' + newDirTarget : ''}`" width="400px" @close="newDirVisible = false">
      <el-form label-width="80px">
        <el-form-item label="文件夹名" required>
          <el-input v-model="newDirForm.name" placeholder="如 assets" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newDirVisible = false">取消</el-button>
        <el-button type="primary" @click="createDir">创建</el-button>
      </template>
    </el-dialog>

    <!-- 重命名文件/文件夹 -->
    <el-dialog :model-value="renameVisible" :title="`重命名：${renameForm.oldPath}`" width="400px" @close="renameVisible = false">
      <el-form label-width="80px">
        <el-form-item label="新名称" required>
          <el-input v-model="renameForm.name" placeholder="新名称" class="mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" @click="renameFile">保存</el-button>
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
.rm-more {
  opacity: 0;
  flex-shrink: 0;
  display: inline-flex;
  color: var(--app-text-muted);
  cursor: pointer;
}
.rm-node:hover .rm-more {
  opacity: 1;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

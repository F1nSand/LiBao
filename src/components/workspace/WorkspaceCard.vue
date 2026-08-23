<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWorkspaceStore } from '@/stores/workspace'
import type { Workspace } from '@/types'

/** 工作区气泡卡片（M7-B，docs/02 §4）：name/description 就地编辑 + 进入 + 删除（强确认输入名称） */
const props = defineProps<{ workspace: Workspace }>()
const store = useWorkspaceStore()
const router = useRouter()

const editing = ref(false)
const name = ref(props.workspace.name)
const desc = ref(props.workspace.description ?? '')

function startEdit() {
  name.value = props.workspace.name
  desc.value = props.workspace.description ?? ''
  editing.value = true
}

async function save() {
  await store.update(props.workspace.id, {
    name: name.value.trim() || props.workspace.name,
    description: desc.value.trim() || undefined,
  })
  editing.value = false
  ElMessage.success('已保存')
}

async function onDelete() {
  // 强确认：输入工作区名称防误删（删除 = 本地目录 + 对话/记忆/文件全删，不可恢复）
  const { value } = await ElMessageBox.prompt(
    `删除工作区「${props.workspace.name}」？将删除本地目录、对话、记忆与文件，不可恢复。输入工作区名称确认：`,
    '删除工作区',
    {
      type: 'warning',
      inputPlaceholder: props.workspace.name,
      confirmButtonText: '删除',
      confirmButtonClass: 'el-button--danger',
    },
  ).catch(() => ({ value: '' }))
  if (value.trim() !== props.workspace.name) {
    ElMessage.warning('名称不匹配，已取消删除')
    return
  }
  await store.remove(props.workspace.id)
  ElMessage.success('已删除')
}

function enter() {
  void router.push(`/workspace/${props.workspace.id}`)
}
</script>

<template>
  <el-card shadow="hover" class="ws-card">
    <template #header>
      <div v-if="!editing" class="ws-card-head">
        <span class="ws-card-name" :title="workspace.name">{{ workspace.name }}</span>
        <div class="ws-card-ops">
          <el-button size="small" text @click="startEdit">编辑</el-button>
          <el-button size="small" text type="danger" @click="onDelete">删除</el-button>
        </div>
      </div>
      <el-input v-else v-model="name" size="small" placeholder="工作区名称" class="mono" @keyup.enter="save" />
    </template>

    <div v-if="!editing" class="ws-card-desc" @click="enter">
      {{ workspace.description || '暂无描述' }}
    </div>
    <div v-else class="ws-card-edit">
      <el-input v-model="desc" size="small" type="textarea" :rows="2" placeholder="描述（气泡显示内容）" />
      <div class="ws-card-edit-ops">
        <el-button size="small" type="primary" @click="save">保存</el-button>
        <el-button size="small" @click="editing = false">取消</el-button>
      </div>
    </div>

    <template #footer>
      <el-button type="primary" size="small" plain @click="enter">进入工作区</el-button>
    </template>
  </el-card>
</template>

<style scoped>
.ws-card {
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-card);
}
.ws-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ws-card-name {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ws-card-ops {
  display: flex;
  flex-shrink: 0;
}
.ws-card-desc {
  font-size: 13px;
  color: var(--app-text-muted);
  min-height: 44px;
  cursor: pointer;
  border-radius: var(--app-radius);
  padding: 4px 8px;
  margin: -4px -8px;
  transition: background 0.15s;
}
.ws-card-desc:hover {
  background: var(--app-bg);
}
.ws-card-edit-ops {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.mono {
  font-family: var(--app-font-mono);
}
</style>

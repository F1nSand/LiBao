<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMemoryStore } from '@/stores/memory'
import { formatDate } from '@/utils/format'
import type { CreateLongTermMemoryRequest, LongTermMemory, LongTermMemoryVersion } from '@/types'
import JsonViewer from '@/components/common/JsonViewer.vue'

/** 长期记忆卡片（docs/02 §6.2 / docs/03 §5.7）：只读展示 + 版本历史 + 新增/改写（只增） */
const store = useMemoryStore()

const addVisible = ref(false)
const versionsVisible = ref(false)
const versionsOf = ref<LongTermMemory | null>(null)
const versions = ref<LongTermMemoryVersion[]>([])

const form = reactive<CreateLongTermMemoryRequest>({
  card_type: 'note',
  title: '',
  body: '',
  tags: [],
})
const tagInput = ref('')

function openAdd() {
  Object.assign(form, { card_type: 'note', title: '', body: '', tags: [] })
  tagInput.value = ''
  addVisible.value = true
}

async function save() {
  if (!form.title.trim()) {
    ElMessage.warning('请输入标题')
    return
  }
  const body = form.card_type === 'json_card' ? safeParse(form.body as string) : { content: form.body }
  await store.create({ ...form, body })
  addVisible.value = false
  ElMessage.success('已写入（只增版本化）')
}

function safeParse(s: string): unknown {
  try {
    return JSON.parse(s)
  } catch {
    return s
  }
}

function addTag() {
  const t = tagInput.value.trim()
  if (t && !form.tags?.includes(t)) form.tags?.push(t)
  tagInput.value = ''
}

function removeTag(t: string) {
  form.tags = form.tags?.filter((x) => x !== t) ?? []
}

function noteText(m: LongTermMemory): string {
  if (m.card_type === 'note' && typeof m.body === 'object' && m.body !== null) {
    const content = (m.body as { content?: string }).content
    if (content !== undefined) return content
  }
  return String(m.body)
}

async function showVersions(m: LongTermMemory) {
  versionsOf.value = m
  versions.value = await store.versions(m.id)
  versionsVisible.value = true
}

async function onDelete(m: LongTermMemory) {
  await ElMessageBox.confirm(`软删除记忆「${m.title}」？（保留历史版本）`, '删除确认', { type: 'warning' })
  await store.remove(m.id)
  ElMessage.success('已删除')
}
</script>

<template>
  <div class="memory-cards">
    <div class="memory-toolbar">
      <el-button type="primary" :icon="'Plus'" @click="openAdd">新增记忆</el-button>
    </div>

    <div class="memory-grid">
      <el-card v-for="m in store.longterm" :key="m.id" shadow="hover" class="memory-card">
        <template #header>
          <div class="memory-head">
            <span class="memory-title">{{ m.title }}</span>
            <div class="memory-stars">
              <el-icon v-for="i in 5" :key="i" :class="{ lit: i <= (m.importance ?? 0) }"><StarFilled /></el-icon>
            </div>
          </div>
        </template>
        <div class="memory-body">
          <JsonViewer v-if="m.card_type === 'json_card'" :data="m.body" />
          <p v-else class="memory-note">{{ noteText(m) }}</p>
        </div>
        <div class="memory-tags">
          <el-tag v-for="t in m.tags ?? []" :key="t" size="small" type="info" disable-transitions>{{ t }}</el-tag>
        </div>
        <template #footer>
          <div class="memory-actions">
            <el-button size="small" text type="primary" @click="showVersions(m)">版本历史</el-button>
            <el-button size="small" text type="danger" @click="onDelete(m)">删除</el-button>
          </div>
        </template>
      </el-card>
      <el-empty v-if="store.longterm.length === 0" description="暂无长期记忆" />
    </div>

    <el-dialog :model-value="addVisible" title="新增/改写记忆（只增版本化）" width="520px" @close="addVisible = false">
      <el-form label-width="80px">
        <el-form-item label="类型">
          <el-radio-group v-model="form.card_type">
            <el-radio-button value="note">笔记</el-radio-button>
            <el-radio-button value="json_card">结构化卡片</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item v-if="form.card_type === 'json_card'" label="正文">
          <el-input v-model="form.body" type="textarea" :rows="5" placeholder='{"backstory":"…","person":{"name":"…"}}' />
        </el-form-item>
        <el-form-item v-else label="正文">
          <el-input v-model="form.body" type="textarea" :rows="4" placeholder="记忆内容" />
        </el-form-item>
        <el-form-item label="标签">
          <div class="tag-input">
            <el-input v-model="tagInput" size="small" placeholder="输入后回车" @keyup.enter="addTag" />
            <el-button size="small" @click="addTag">添加</el-button>
          </div>
          <el-tag v-for="t in form.tags ?? []" :key="t" size="small" closable @close="removeTag(t)">{{ t }}</el-tag>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" @click="save">写入</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="versionsVisible" :title="`版本历史：${versionsOf?.title ?? ''}`" width="520px" @close="versionsVisible = false">
      <div v-for="v in versions" :key="v.id" class="version-item">
        <div class="version-head">
          <span class="version-no">v{{ v.version }}</span>
          <span class="version-time">{{ formatDate(v.created_at) }}</span>
        </div>
        <JsonViewer :data="v.body" />
      </div>
      <el-empty v-if="versions.length === 0" description="暂无历史版本" :image-size="60" />
    </el-dialog>
  </div>
</template>

<style scoped>
.memory-toolbar {
  margin-bottom: 8px;
}
.memory-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  overflow-y: auto;
  padding-bottom: 20px;
}
.memory-card {
  box-shadow: var(--app-shadow-card);
}
.memory-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.memory-title {
  font-weight: 600;
}
.memory-stars .el-icon {
  color: var(--app-border);
}
.memory-stars .el-icon.lit {
  color: #f59e0b;
}
.memory-body {
  max-height: 180px;
  overflow: auto;
  font-size: 13px;
}
.memory-note {
  margin: 0;
  white-space: pre-wrap;
}
.memory-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}
.memory-actions {
  display: flex;
  gap: 4px;
}
.tag-input {
  display: flex;
  gap: 8px;
  width: 100%;
  margin-bottom: 6px;
}
.version-item {
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  padding: 8px;
  margin-bottom: 8px;
}
.version-head {
  display: flex;
  gap: 10px;
  margin-bottom: 4px;
}
.version-no {
  font-weight: 600;
  font-family: var(--app-font-mono);
}
.version-time {
  color: var(--app-text-muted);
  font-size: 12px;
}
</style>

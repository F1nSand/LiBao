<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSkillStore } from '@/stores/skill'
import EmptyState from '@/components/common/EmptyState.vue'
import type { Skill } from '@/types'

/** Skills 管理（docs/02 §4 · 设置组子项，M7-A 交接板 2026-08-20 契约）：手动创建 / git 导入 / 启用开关 / 删除；主 Agent 自动使用 enabled 技能 */
const store = useSkillStore()

const createVisible = ref(false)
const importVisible = ref(false)
const createForm = reactive({ name: '', description: '', body: '' })
const importForm = reactive({ url: '' })

onMounted(() => void store.list())

async function onCreate() {
  if (!createForm.name.trim() || !createForm.body.trim()) {
    ElMessage.warning('请填写技能名称与正文')
    return
  }
  await store.create({
    name: createForm.name.trim(),
    description: createForm.description.trim() || undefined,
    body: createForm.body,
  })
  createVisible.value = false
  Object.assign(createForm, { name: '', description: '', body: '' })
  ElMessage.success('技能已创建')
}

async function onImport() {
  if (!importForm.url.trim()) {
    ElMessage.warning('请输入 git 仓库地址')
    return
  }
  await store.importFromGit(importForm.url.trim())
  importVisible.value = false
  importForm.url = ''
  ElMessage.success('技能已导入')
}

async function onToggle(s: Skill, enabled: boolean) {
  if (enabled) {
    await ElMessageBox.confirm(
      `启用技能「${s.name}」？遵循默认关闭原则，主 Agent 将把其路由描述注入上下文，请确认内容可信。`,
      '启用确认',
      { type: 'warning', confirmButtonText: '启用', cancelButtonText: '取消' },
    )
  }
  await store.toggle(s.id, enabled)
  ElMessage.success(enabled ? '已启用' : '已停用')
}

async function onDelete(s: Skill) {
  await ElMessageBox.confirm(`确认删除技能「${s.name}」？（软删）`, '删除确认', { type: 'warning' })
  await store.remove(s.id)
  ElMessage.success('已删除')
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">技能</h2>
        <p class="app-page-subtitle">Skills 管理 · 手动创建 / git 导入 / 启用开关（主 Agent 自动使用）</p>
      </div>
      <div class="header-actions">
        <el-button :icon="'Link'" @click="importVisible = true">导入 git 技能</el-button>
        <el-button type="primary" :icon="'Plus'" @click="createVisible = true">创建技能</el-button>
      </div>
    </div>

    <template v-if="!store.unavailable">
      <el-table v-loading="store.loading" :data="store.skills" class="skill-table">
        <el-table-column prop="name" label="名称" min-width="150">
          <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column label="来源" width="96">
          <template #default="{ row }">
            <el-tag :type="row.source === 'git' ? 'warning' : 'info'" size="small" disable-transitions>
              {{ row.source === 'git' ? 'git 导入' : '手动' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="路由描述" min-width="240" show-overflow-tooltip />
        <el-table-column label="正文" width="86">
          <template #default="{ row }"><span class="mono">{{ row.body.length }} 字</span></template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" size="small" @change="(v: boolean) => onToggle(row, v)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
    <EmptyState v-else text="后端暂未实现 Skills 接口（M7-A 契约已发交接板）" />

    <!-- 创建技能 -->
    <el-dialog :model-value="createVisible" title="创建技能" width="540px" @close="createVisible = false">
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="如 python-代码审查" />
        </el-form-item>
        <el-form-item label="路由描述">
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="2"
            placeholder="何时用 / 何时别用（进 system_prompt 前缀，主 Agent 据此路由）"
          />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input v-model="createForm.body" type="textarea" :rows="6" placeholder="SKILL.md 正文：步骤 / 示例 / 注意事项" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- git 导入 -->
    <el-dialog :model-value="importVisible" title="导入 git 技能" width="500px" @close="importVisible = false">
      <el-form label-width="90px">
        <el-form-item label="仓库地址" required>
          <el-input v-model="importForm.url" placeholder="https://github.com/org/skill-repo.git" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" @click="onImport">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  gap: 8px;
}
.skill-table {
  flex: 1;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

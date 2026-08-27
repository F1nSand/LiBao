<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSkillStore } from '@/stores/skill'
import { useWorkspaceStore } from '@/stores/workspace'
import EmptyState from '@/components/common/EmptyState.vue'

/** Skills 目录展示（M7-A 简化 2026-08-25）：全局 ~/.LiBao/skills + 工作区 .agent/skills，只读 */
const store = useSkillStore()
const wsStore = useWorkspaceStore()

const selectedWs = ref('')

onMounted(() => {
  void store.listGlobal()
  void wsStore.list()
})

async function onSelectWs(id: string) {
  selectedWs.value = id
  if (id) await store.listWorkspace(id)
  else store.workspace = []
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">技能</h2>
        <p class="app-page-subtitle">
          Skills 目录 · 放 SKILL.md 到 ~/.LiBao/skills 或工作区 .agent/skills 即自动识别；agent 可用 install_skill 下载
        </p>
      </div>
    </div>

    <template v-if="!store.unavailable">
      <section>
        <h3 class="section-title">全局 Skills（~/.LiBao/skills）</h3>
        <el-table v-loading="store.loading" :data="store.global" class="skill-table">
          <el-table-column prop="name" label="名称" min-width="150">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column prop="description" label="路由描述" min-width="260" show-overflow-tooltip />
          <el-table-column prop="path" label="位置" min-width="200" show-overflow-tooltip />
        </el-table>
      </section>

      <section style="margin-top: 24px">
        <div class="section-header">
          <h3 class="section-title">工作区 Skills（.agent/skills）</h3>
          <el-select
            v-model="selectedWs"
            placeholder="选择工作区"
            clearable
            style="width: 240px"
            @change="onSelectWs"
          >
            <el-option v-for="w in wsStore.workspaces" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </div>
        <el-table v-loading="store.loading" :data="store.workspace" class="skill-table">
          <el-table-column prop="name" label="名称" min-width="150">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column prop="description" label="路由描述" min-width="260" show-overflow-tooltip />
          <el-table-column prop="path" label="位置" min-width="200" show-overflow-tooltip />
        </el-table>
        <el-empty
          v-if="!store.workspace.length && selectedWs"
          description="该工作区暂无 skills（放 .agent/skills/<name>/SKILL.md 即自动识别）"
          :image-size="60"
        />
      </section>
    </template>
    <EmptyState v-else text="后端暂未实现 Skills 接口" />
  </div>
</template>

<style scoped>
.section-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.skill-table {
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-card);
  overflow: hidden;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

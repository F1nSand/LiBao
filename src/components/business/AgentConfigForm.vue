<script setup lang="ts">
import { onMounted, reactive, watch } from 'vue'
import { useToolStore } from '@/stores/tool'
import type { AgentConfigInput, GraphTemplate } from '@/types'

/** Agent 配置表单（docs/02 §6.2）：模型/提示词/技能/工具/模板/最大步数 */
const props = defineProps<{ model: AgentConfigInput }>()
const emit = defineEmits<{ 'update:model': [v: AgentConfigInput] }>()

const toolStore = useToolStore()
const form = reactive<AgentConfigInput>({ ...props.model })

watch(
  () => props.model,
  (m) => Object.assign(form, m),
)

function sync() {
  emit('update:model', { ...form })
}

const templates: Array<{ value: GraphTemplate; label: string }> = [
  { value: 'single', label: '单 Agent' },
  { value: 'proposer_reviewer', label: '提议者-审核者' },
  { value: 'manager_worker', label: '管理者-工人' },
]

onMounted(() => {
  if (toolStore.tools.length === 0) void toolStore.list()
})
</script>

<template>
  <el-form :model="form" label-width="100px">
    <el-form-item label="名称" required>
      <el-input v-model="form.name" placeholder="Agent 名称" @input="sync" />
    </el-form-item>
    <el-form-item label="模型" required>
      <el-input v-model="form.model" placeholder="如 gpt-4o / deepseek-chat" @input="sync" />
    </el-form-item>
    <el-form-item label="系统提示词">
      <el-input v-model="form.system_prompt" type="textarea" :rows="4" placeholder="Agent 角色与行为约束" @input="sync" />
    </el-form-item>
    <el-form-item label="编排模板">
      <el-select v-model="form.graph_template" @change="sync">
        <el-option v-for="t in templates" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
    </el-form-item>
    <el-form-item label="技能">
      <el-select v-model="form.skills" multiple allow-create filterable default-first-option placeholder="添加技能" @change="sync">
        <el-option v-for="s in form.skills ?? []" :key="s" :label="s" :value="s" />
      </el-select>
    </el-form-item>
    <el-form-item label="工具">
      <el-select v-model="form.tools" multiple filterable placeholder="选择可用工具" @change="sync">
        <el-option v-for="t in toolStore.tools" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>
    </el-form-item>
    <el-form-item label="最大步数">
      <el-input-number v-model="form.max_steps" :min="1" :max="200" @change="sync" />
    </el-form-item>
  </el-form>
</template>

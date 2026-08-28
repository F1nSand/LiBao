<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useToolStore } from '@/stores/tool'
import type { ToolDefinition } from '@/types'
import JsonViewer from '@/components/common/JsonViewer.vue'
import ResponsiveDialog from '@/components/common/ResponsiveDialog.vue'

/** 沙盒测试弹窗（docs/02 §6.2）：按 params_schema 动态生成表单 → POST /tools/{id}/test */
const props = defineProps<{ visible: boolean; tool: ToolDefinition | null }>()
const emit = defineEmits<{ close: [] }>()

const store = useToolStore()
const values = reactive<Record<string, unknown>>({})
const result = ref<{ ok: boolean; output?: unknown; duration_ms?: number; error?: string } | null>(null)
const loading = ref(false)

const properties = computed(() => {
  const schema = props.tool?.params_schema as {
    properties?: Record<string, { type?: string; description?: string; required?: boolean; default?: unknown; enum?: unknown[]; minimum?: number; maximum?: number }>
  } | undefined
  return schema?.properties ?? {}
})

function init() {
  result.value = null
  Object.keys(values).forEach((k) => delete values[k])
  Object.entries(properties.value).forEach(([key, prop]) => {
    values[key] = prop.default ?? (prop.type === 'boolean' ? false : prop.type === 'number' ? null : '')
  })
}

async function run() {
  if (!props.tool) return
  loading.value = true
  try {
    const res = await store.test(props.tool.id, { ...values })
    result.value = res
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <ResponsiveDialog
    :model-value="visible"
    :title="`沙盒测试：${tool?.name ?? ''}`"
    width="520px"
    @open="init"
    @close="emit('close')"
  >
    <el-form label-width="100px" v-if="tool">
      <template v-if="Object.keys(properties).length">
        <el-form-item
          v-for="(prop, key) in properties"
          :key="key"
          :label="prop.description || key"
          :required="!!prop.required"
        >
          <el-switch v-if="prop.type === 'boolean'" v-model="values[key]" />
          <el-input-number
            v-else-if="prop.type === 'number' || prop.type === 'integer'"
            v-model="values[key]"
            :min="prop.minimum"
            :max="prop.maximum"
            controls-position="right"
          />
          <el-select v-else-if="prop.enum?.length" v-model="values[key]" clearable class="test-field-control">
            <el-option v-for="option in prop.enum" :key="String(option)" :label="String(option)" :value="option" />
          </el-select>
          <el-input v-else v-model="values[key]" :placeholder="prop.type ?? 'value'" clearable />
        </el-form-item>
      </template>
      <el-form-item v-else label="参数">
        <el-input v-model="values['params']" type="textarea" :rows="3" placeholder="JSON 参数" />
      </el-form-item>
    </el-form>

    <div v-if="result" class="test-result" :class="{ ok: result.ok }">
      <div class="test-status">{{ result.ok ? '执行成功' : '执行失败' }}</div>
      <div v-if="result.duration_ms != null" class="test-duration">{{ result.duration_ms }}ms</div>
      <div v-if="result.output !== undefined" class="test-output"><JsonViewer :data="result.output" /></div>
      <div v-if="result.error" class="test-error">{{ result.error }}</div>
    </div>

    <template #footer>
      <el-button @click="emit('close')">关闭</el-button>
      <el-button type="primary" :loading="loading" @click="run">执行测试</el-button>
    </template>
  </ResponsiveDialog>
</template>

<style scoped>
.test-result {
  margin-top: 12px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  padding: 10px;
  background: var(--app-bg);
}
.test-result.ok {
  border-color: rgba(34, 197, 94, 0.4);
}
.test-status {
  font-weight: 600;
  font-size: 13px;
}
.test-duration {
  font-size: 12px;
  color: var(--app-text-muted);
  font-family: var(--app-font-mono);
  margin-top: 2px;
}
.test-output {
  margin-top: 6px;
  max-height: 180px;
  overflow: auto;
  background: #fff;
  border-radius: var(--app-radius-sm);
  padding: 6px;
}
.test-error {
  color: var(--app-danger);
  font-size: 12px;
  margin-top: 6px;
}
.test-field-control {
  width: 100%;
}
</style>

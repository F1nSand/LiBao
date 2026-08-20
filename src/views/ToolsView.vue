<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useToolStore } from '@/stores/tool'
import type { ToolDefinition } from '@/types'
import ToolTestModal from '@/components/business/ToolTestModal.vue'
import ToolSearchBar from '@/components/business/ToolSearchBar.vue'

/** 工具管理（docs/02 §4 / docs/03 §5.5）：注册/启用开关/沙盒测试/MCP 源；元工具（tool_search 等发现层）与常规工具区分 */
const store = useToolStore()

const activeTool = ref<ToolDefinition | null>(null)
const testVisible = ref(false)
const createVisible = ref(false)
const mcpVisible = ref(false)

/** 类别筛选：全部 / 元工具（平台发现层，tool_search 等常驻）/ 常规工具（经 tool_search 发现） */
const metaFilter = ref<'all' | 'meta' | 'regular'>('all')
const filteredTools = computed(() => {
  const list = store.tools.filter((t) =>
    metaFilter.value === 'all' ? true : metaFilter.value === 'meta' ? !!t.meta : !t.meta,
  )
  if (metaFilter.value === 'all') list.sort((a, b) => Number(!!b.meta) - Number(!!a.meta))
  return list
})

const form = reactive({
  name: '',
  description: '',
  tool_type: 'execution' as ToolDefinition['tool_type'],
  require_confirm: false,
  params_schema: '',
})
const mcpForm = reactive({ url_or_command: '', enable: true })

const TYPE_LABEL: Record<string, string> = {
  perception: '感知',
  execution: '执行',
  collaboration: '协作',
  user_comms: '用户通信',
  event: '事件',
  agent_control: 'Agent 控制',
}

onMounted(() => void store.list())

function openTest(t: ToolDefinition) {
  activeTool.value = t
  testVisible.value = true
}

async function onToggle(t: ToolDefinition, enabled: boolean) {
  if (enabled) {
    await ElMessageBox.confirm(
      `启用工具「${t.name}」？遵循默认关闭原则，请确认其安全性。`,
      '启用确认',
      { type: 'warning', confirmButtonText: '启用', cancelButtonText: '取消' },
    )
  }
  await store.toggle(t.id, enabled)
  ElMessage.success(enabled ? '已启用' : '已停用')
}

async function createTool() {
  if (!form.name) {
    ElMessage.warning('请输入工具名称')
    return
  }
  let paramsSchema: Record<string, unknown> | undefined
  if (form.params_schema.trim()) {
    try {
      paramsSchema = JSON.parse(form.params_schema)
    } catch {
      ElMessage.error('参数 schema 不是合法 JSON')
      return
    }
  }
  await store.create({
    name: form.name,
    description: form.description,
    tool_type: form.tool_type,
    require_confirm: form.require_confirm,
    params_schema: paramsSchema,
  })
  createVisible.value = false
  Object.assign(form, { name: '', description: '', tool_type: 'execution', require_confirm: false, params_schema: '' })
  ElMessage.success('工具已注册')
}

async function registerMcp() {
  if (!mcpForm.url_or_command) {
    ElMessage.warning('请输入 MCP 源地址或命令')
    return
  }
  await store.registerMcp(mcpForm.url_or_command)
  mcpVisible.value = false
  mcpForm.url_or_command = ''
  ElMessage.success('MCP 源已注册')
}

async function onDelete(t: ToolDefinition) {
  await ElMessageBox.confirm(`确认删除工具「${t.name}」？（软删）`, '删除确认', { type: 'warning' })
  await store.remove(t.id)
  ElMessage.success('已删除')
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">工具</h2>
        <p class="app-page-subtitle">工具注册 / 启用开关 / 沙盒测试 / MCP 源</p>
      </div>
      <div class="header-actions">
        <el-button :icon="'Link'" @click="mcpVisible = true">注册 MCP</el-button>
        <el-button type="primary" :icon="'Plus'" @click="createVisible = true">注册工具</el-button>
      </div>
    </div>

    <div class="tool-search-wrap">
      <ToolSearchBar />
      <el-radio-group v-model="metaFilter" size="small">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="meta">元工具</el-radio-button>
        <el-radio-button value="regular">常规工具</el-radio-button>
      </el-radio-group>
    </div>

    <el-table v-loading="store.loading" :data="filteredTools" class="tool-table">
      <el-table-column prop="name" label="名称" min-width="140">
        <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
      </el-table-column>
      <el-table-column label="类别" width="100">
        <template #default="{ row }">
          <el-tag :type="row.meta ? 'warning' : 'info'" size="small" disable-transitions>{{ row.meta ? '元工具' : '常规工具' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="{ row }"><el-tag size="small">{{ TYPE_LABEL[row.tool_type] ?? row.tool_type }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
      <el-table-column label="确认" width="90">
        <template #default="{ row }">{{ row.require_confirm ? '是' : '否' }}</template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" size="small" @change="(v: boolean) => onToggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openTest(row)">测试</el-button>
          <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 注册工具 -->
    <el-dialog :model-value="createVisible" title="注册工具" width="520px" @close="createVisible = false">
      <el-form label-width="120px">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如 stock_query" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.tool_type">
            <el-option v-for="(label, val) in TYPE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>
        <el-form-item label="需确认"><el-switch v-model="form.require_confirm" /></el-form-item>
        <el-form-item label="参数 schema">
          <el-input v-model="form.params_schema" type="textarea" :rows="4" placeholder='{"type":"object","properties":{}}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="createTool">注册</el-button>
      </template>
    </el-dialog>

    <!-- 注册 MCP -->
    <el-dialog :model-value="mcpVisible" title="注册 MCP 源" width="480px" @close="mcpVisible = false">
      <el-form label-width="140px">
        <el-form-item label="地址/命令" required>
          <el-input v-model="mcpForm.url_or_command" placeholder="npx @modelcontextprotocol/server-xxx 或 http://…" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="mcpForm.enable" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mcpVisible = false">取消</el-button>
        <el-button type="primary" @click="registerMcp">注册</el-button>
      </template>
    </el-dialog>

    <ToolTestModal :visible="testVisible" :tool="activeTool" @close="testVisible = false; activeTool = null" />
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  gap: 8px;
}
.tool-search-wrap {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.tool-table {
  flex: 1;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

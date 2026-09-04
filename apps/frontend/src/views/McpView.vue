<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMcpStore } from '@/stores/mcp'
import { useToolStore } from '@/stores/tool'
import type { McpRegisterRequest } from '@/types'
import AsyncState from '@/components/common/AsyncState.vue'
import ResponsiveDialog from '@/components/common/ResponsiveDialog.vue'

const store = useMcpStore()
const toolStore = useToolStore()
const createVisible = ref(false)

interface HeaderRow {
  key: string
  value: string
}

const form = reactive({
  name: '',
  url_or_command: '',
  enable: true,
  headers: [{ key: '', value: '' }] as HeaderRow[],
})

onMounted(() => void store.list())

function resetForm() {
  Object.assign(form, { name: '', url_or_command: '', enable: true })
  form.headers = [{ key: '', value: '' }]
}

function addHeader() {
  form.headers.push({ key: '', value: '' })
}

function removeHeader(index: number) {
  if (form.headers.length === 1) {
    form.headers[0] = { key: '', value: '' }
    return
  }
  form.headers.splice(index, 1)
}

function buildHeaders(): Record<string, string> | undefined {
  const entries = form.headers
    .map(({ key, value }) => [key.trim(), value.trim()] as const)
    .filter(([key, value]) => key && value)
  return entries.length ? Object.fromEntries(entries) : undefined
}

async function registerServer() {
  const urlOrCommand = form.url_or_command.trim()
  if (!urlOrCommand) {
    ElMessage.warning('请输入 MCP 源地址或命令')
    return
  }
  const body: McpRegisterRequest = {
    name: form.name.trim() || undefined,
    url_or_command: urlOrCommand,
    headers: buildHeaders(),
    enable: form.enable,
  }
  await store.register(body)
  await toolStore.list()
  createVisible.value = false
  resetForm()
  ElMessage.success('MCP 源已注册')
}

async function removeServer(id: string, name: string) {
  await ElMessageBox.confirm(`确认删除 MCP 源「${name}」？关联工具也会被移除。`, '删除确认', {
    type: 'warning',
  })
  await store.remove(id)
  await toolStore.list()
  ElMessage.success('MCP 源已删除')
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">MCP</h2>
        <p class="app-page-subtitle">管理外部 MCP 服务源；注册后发现的工具会出现在工具页面。</p>
      </div>
      <el-button type="primary" :icon="'Plus'" :disabled="store.submitting" @click="createVisible = true">
        注册 MCP
      </el-button>
    </div>

    <AsyncState
      :status="store.status"
      :error-message="store.errorMessage"
      empty-text="暂无已注册 MCP 服务"
      empty-action-text="注册 MCP"
      @retry="store.retry"
      @action="createVisible = true"
    >
      <div class="app-table-wrap">
        <el-table :data="store.servers" row-key="id" class="mcp-table">
          <el-table-column prop="name" label="名称" min-width="150">
            <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column label="传输" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.transport === 'http' ? 'success' : 'info'">
                {{ row.transport === 'http' ? 'HTTP' : 'stdio' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="url_or_command" label="地址 / 命令" min-width="260" show-overflow-tooltip />
          <el-table-column label="请求头" min-width="160">
            <template #default="{ row }">
              <span v-if="row.header_names.length" class="header-names">{{ row.header_names.join(' · ') }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="工具数" width="90">
            <template #default="{ row }">{{ row.tool_count }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '已停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="danger" size="small" :disabled="store.submitting" @click="removeServer(row.id, row.name)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </AsyncState>

    <ResponsiveDialog v-model="createVisible" title="注册 MCP 源" width="560px">
      <el-form label-width="110px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="可选，留空则根据地址/命令生成" />
        </el-form-item>
        <el-form-item label="地址 / 命令" required>
          <el-input v-model="form.url_or_command" placeholder="http://…/mcp 或 npx @modelcontextprotocol/server-xxx" />
        </el-form-item>
        <el-form-item label="请求头">
          <div class="headers-editor">
            <div v-for="(header, index) in form.headers" :key="index" class="header-row">
              <el-input v-model="header.key" placeholder="名称" />
              <el-input v-model="header.value" type="password" show-password placeholder="值" />
              <el-button link type="danger" :aria-label="`删除请求头 ${index + 1}`" @click="removeHeader(index)">
                删除
              </el-button>
            </div>
            <el-button link type="primary" :icon="'Plus'" @click="addHeader">新增请求头</el-button>
          </div>
        </el-form-item>
        <el-form-item label="注册后启用">
          <el-switch v-model="form.enable" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.submitting" :disabled="store.submitting" @click="registerServer">
          注册
        </el-button>
      </template>
    </ResponsiveDialog>
  </div>
</template>

<style scoped>
.mcp-table {
  min-width: 900px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-card);
  overflow: hidden;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
.header-names {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.muted {
  color: var(--app-text-muted);
}
.headers-editor {
  width: 100%;
}
.header-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr) auto;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
@media (max-width: 600px) {
  .header-row {
    grid-template-columns: 1fr 1fr;
  }
  .header-row :deep(.el-button) {
    grid-column: 1 / -1;
    justify-self: start;
  }
}
</style>

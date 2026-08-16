<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listUsers,
  createUser,
  patchUserRole,
  patchUserStatus,
  deleteUser,
} from '@/api/users'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
import EmptyState from '@/components/common/EmptyState.vue'
import { ROLE_LABEL } from '@/constants/labels'
import type { Role, User } from '@/types'

/** 设置（docs/02 §4 / docs/03 §5.1）：用户与权限 + Provider 配置（MVP 静态表单） */
const tab = ref('users')

const users = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
/** 后端未实现 /users（HTTP 404 打标）→ 用户 tab 显示空态 */
const usersUnavailable = computed(() => isUnavailable(FEATURE.users))

const createVisible = ref(false)
const createForm = reactive({ username: '', password: '', name: '', role: 'viewer' as Role })

const providerForm = reactive({ provider: 'openai', base_url: '', api_key: '' })

async function load(pageNo = 1) {
  loading.value = true
  try {
    // 后端未实现 /users → 返回 undefined（已打标），页面显示空态；其余错误照常抛
    const res = await swallowNotImplemented(listUsers({ page: pageNo, page_size: pageSize }))
    if (res) {
      users.value = res.items
      total.value = res.total
      page.value = res.page
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())

async function onCreate() {
  if (!createForm.username || !createForm.password) {
    ElMessage.warning('请填写用户名与密码')
    return
  }
  // 后端未实现写操作 → 返回 undefined（已打标，tab 折叠空态），不弹错不崩
  const created = await swallowNotImplemented(
    createUser({ ...createForm, name: createForm.name || createForm.username }),
  )
  if (created === undefined) return
  createVisible.value = false
  Object.assign(createForm, { username: '', password: '', name: '', role: 'viewer' })
  ElMessage.success('用户已创建')
  await load()
}

async function onChangeRole(u: User, role: Role) {
  const ok = await swallowNotImplemented(patchUserRole(u.id, role))
  if (ok === undefined) return
  u.role = role
  ElMessage.success('角色已更新')
}

async function onChangeStatus(u: User, enabled: boolean) {
  if (!enabled) {
    await ElMessageBox.confirm(`禁用用户「${u.name}」将立即踢下线，确认？`, '禁用确认', { type: 'warning' })
  }
  const ok = await swallowNotImplemented(patchUserStatus(u.id, enabled))
  if (ok === undefined) return
  u.enabled = enabled
  ElMessage.success(enabled ? '已启用' : '已禁用')
}

async function onDelete(u: User) {
  await ElMessageBox.confirm(`确认删除用户「${u.name}」？（软删，保留历史）`, '删除确认', { type: 'warning' })
  const ok = await swallowNotImplemented(deleteUser(u.id))
  if (ok === undefined) return
  ElMessage.success('已删除')
  await load()
}

function saveProvider() {
  if (!providerForm.provider) {
    ElMessage.warning('请选择 Provider')
    return
  }
  ElMessage.success('Provider 配置已保存（MVP 本地表单，后端契约待接入）')
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">设置</h2>
        <p class="app-page-subtitle">模型 Provider / 用户与权限</p>
      </div>
    </div>

    <el-tabs v-model="tab" class="settings-tabs">
      <el-tab-pane label="用户与权限" name="users">
        <template v-if="!usersUnavailable">
          <div class="users-toolbar">
            <el-button type="primary" :icon="'Plus'" @click="createVisible = true">新建用户</el-button>
          </div>
          <el-table :data="users" v-loading="loading" size="small">
            <el-table-column prop="username" label="用户名" width="140" />
            <el-table-column prop="name" label="姓名" width="140" />
            <el-table-column label="角色" width="160">
              <template #default="{ row }">
                <el-select :model-value="row.role" size="small" @change="(r: Role) => onChangeRole(row, r)">
                  <el-option v-for="(label, val) in ROLE_LABEL" :key="val" :label="label" :value="val" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  size="small"
                  @change="(v: boolean) => onChangeStatus(row, v)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="danger" @click="onDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <EmptyState v-else text="后端暂未实现用户与权限接口" />
      </el-tab-pane>

      <el-tab-pane label="Provider 配置" name="provider">
        <div class="provider-form app-card">
          <el-form label-width="120px" style="max-width: 480px">
            <el-form-item label="Provider">
              <el-select v-model="providerForm.provider">
                <el-option label="OpenAI" value="openai" />
                <el-option label="DeepSeek" value="deepseek" />
                <el-option label="Qwen" value="qwen" />
                <el-option label="Kimi" value="kimi" />
                <el-option label="Ollama" value="ollama" />
              </el-select>
            </el-form-item>
            <el-form-item label="Base URL">
              <el-input v-model="providerForm.base_url" placeholder="https://api.openai.com/v1" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="providerForm.api_key" type="password" show-password placeholder="凭证走密钥管理，不进代码" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveProvider">保存</el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog :model-value="createVisible" title="新建用户" width="440px" @close="createVisible = false">
      <el-form label-width="80px">
        <el-form-item label="用户名"><el-input v-model="createForm.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="createForm.password" type="password" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role">
            <el-option v-for="(label, val) in ROLE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="onCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.users-toolbar {
  margin-bottom: 10px;
}
.provider-form {
  padding: 20px;
  max-width: 640px;
}
</style>

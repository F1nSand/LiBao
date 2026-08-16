<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/http'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    const redirect = (route.query.redirect as string) || '/chat'
    router.replace(redirect)
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.code === 40101) ElMessage.error('用户名或密码错误')
      else ElMessage.error(e.message)
    } else {
      ElMessage.error('登录失败，请稍后重试')
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <el-icon :size="30" color="#fff"><ChatDotRound /></el-icon>
        <h1 class="login-title">Agent 工作台</h1>
        <p class="login-sub">通用 Agent 平台 · 管理控制台</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        @keyup.enter="onSubmit"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="请输入用户名" :prefix-icon="'User'" autofocus />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="请输入密码"
            :prefix-icon="'Lock'"
          />
        </el-form-item>
        <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

      <div class="login-hint">
        <p>演示账号（Mock 环境）：</p>
        <p>admin / admin123 · dev / dev123 · viewer / viewer123</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e1e2f 0%, #3730a3 100%);
  padding: 20px;
}
.login-card {
  width: 380px;
  background: var(--app-content-bg);
  border-radius: var(--app-radius-lg);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.25);
  padding: 32px;
}
.login-brand {
  text-align: center;
  margin-bottom: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.login-title {
  margin: 10px 0 4px;
  font-size: 22px;
}
.login-sub {
  margin: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-sm);
}
.login-btn {
  width: 100%;
  margin-top: 8px;
}
.login-hint {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px dashed var(--app-border);
  font-size: 12px;
  color: var(--app-text-muted);
  text-align: center;
  line-height: 1.6;
}
</style>

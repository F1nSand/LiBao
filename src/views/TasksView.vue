<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import { useAgentStore } from '@/stores/agent'
import TaskList from '@/components/business/TaskList.vue'
import TaskDetail from '@/components/business/TaskDetail.vue'

/** 任务管理（docs/02 §4 / docs/03 §5.3）：提交 / 进度 / 事件回放 / 取消恢复 */
const store = useTaskStore()
const agentStore = useAgentStore()

const submitVisible = ref(false)
const detailId = ref<string | null>(null)
const form = reactive({ agent_id: '', input: '' })

onMounted(() => {
  void store.list()
  void agentStore.list()
})

async function submit() {
  if (!form.agent_id) {
    ElMessage.warning('请选择 Agent')
    return
  }
  if (!form.input.trim()) {
    ElMessage.warning('请输入任务输入')
    return
  }
  const taskId = await store.submit({
    agent_id: form.agent_id,
    input: form.input.trim(),
  })
  submitVisible.value = false
  form.input = ''
  ElMessage.success(`任务已提交：${taskId}`)
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">任务</h2>
        <p class="app-page-subtitle">异步任务提交 / 进度 / 日志回放</p>
      </div>
      <el-button type="primary" :icon="'Plus'" @click="submitVisible = true">提交任务</el-button>
    </div>

    <div class="tasks-layout">
      <div class="tasks-left">
        <TaskList @detail="(id: string) => (detailId = id)" />
      </div>
      <div class="tasks-right app-card">
        <TaskDetail :task-id="detailId" />
      </div>
    </div>

    <el-dialog :model-value="submitVisible" title="提交任务" width="480px" @close="submitVisible = false">
      <el-form label-width="80px">
        <el-form-item label="Agent">
          <el-select v-model="form.agent_id" placeholder="选择 Agent">
            <el-option v-for="a in agentStore.agents" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="输入">
          <el-input v-model="form.input" type="textarea" :rows="4" placeholder="任务指令或 JSON" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="submitVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tasks-layout {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
}
.tasks-left {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}
.tasks-right {
  width: 400px;
  flex-shrink: 0;
  padding: 14px;
  overflow-y: auto;
}
</style>

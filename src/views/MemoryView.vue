<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useMemoryStore } from '@/stores/memory'
import MemoryCardList from '@/components/business/MemoryCardList.vue'

/** 记忆管理（docs/02 §4 / docs/03 §5.7）：长期记忆卡片 + maintenance 整理 */
const store = useMemoryStore()
const tab = ref('longterm')
const maintenanceLoading = ref(false)

onMounted(() => {
  void store.listLongterm()
})

async function onMaintenance() {
  maintenanceLoading.value = true
  try {
    const res = await store.maintenance()
    ElMessage.success(res.summary)
  } finally {
    maintenanceLoading.value = false
  }
}
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">记忆</h2>
        <p class="app-page-subtitle">长期记忆（只增版本化）</p>
      </div>
      <el-button :icon="'MagicStick'" :loading="maintenanceLoading" @click="onMaintenance">触发整理</el-button>
    </div>

    <el-tabs v-model="tab" class="memory-tabs">
      <el-tab-pane label="长期记忆" name="longterm">
        <MemoryCardList />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.memory-tabs {
  flex: 1;
  min-height: 0;
}
.mono {
  font-family: var(--app-font-mono);
  font-size: 12px;
}
</style>

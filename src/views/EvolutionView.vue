<script setup lang="ts">
import { useEvolutionStore } from '@/stores/evolution'
import EmptyState from '@/components/common/EmptyState.vue'
import EvolutionManage from '@/components/system/EvolutionManage.vue'

/** 经验候选区（docs/06 §5 契约，设置组子项，admin）：候选 → 验证 → 批准 → 发布 → 回滚 */
const store = useEvolutionStore()
</script>

<template>
  <div class="app-page">
    <div class="app-page-header">
      <div>
        <h2 class="app-page-title">候选区</h2>
        <p class="app-page-subtitle">经验候选 → 验证 → 批准 → 发布 → 回滚（发布写入 Agent 配置）</p>
      </div>
    </div>

    <template v-if="!store.unavailable">
      <EvolutionManage />
    </template>
    <EmptyState v-else text="后端暂未实现候选区接口" />
  </div>
</template>

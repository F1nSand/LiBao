<script setup lang="ts">
const props = defineProps<{ total: number; page: number; page_size: number }>()
const emit = defineEmits<{ change: [page: number, pageSize: number] }>()
</script>

<template>
  <div class="pagination-panel">
    <el-pagination
      :total="props.total"
      :current-page="props.page"
      :page-size="props.page_size"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      background
      @update:current-page="(p: number) => emit('change', p, props.page_size)"
      @update:page-size="(s: number) => emit('change', 1, s)"
    />
  </div>
</template>

<style scoped>
.pagination-panel {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
}
</style>

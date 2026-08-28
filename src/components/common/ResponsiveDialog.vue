<script setup lang="ts">
import { computed } from 'vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    width?: string | number
  }>(),
  { title: '', width: '520px' },
)
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; close: [] }>()

const desktopWidth = computed(() => (typeof props.width === 'number' ? `${props.width}px` : props.width))
const responsiveWidth = computed(() => `min(${desktopWidth.value}, calc(100vw - 24px))`)

function onUpdate(value: boolean) {
  emit('update:modelValue', value)
}
function onClose() {
  emit('update:modelValue', false)
  emit('close')
}
</script>

<template>
  <el-dialog
    v-bind="$attrs"
    :model-value="props.modelValue"
    :title="props.title"
    :width="responsiveWidth"
    @update:model-value="onUpdate"
    @close="onClose"
  >
    <slot />
    <template #footer>
      <slot name="footer" />
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{ data: unknown }>()

const isObj = computed(() => props.data !== null && typeof props.data === 'object')
const isArr = computed(() => Array.isArray(props.data))
const entries = computed(() =>
  isObj.value ? Object.entries(props.data as Record<string, unknown>) : [],
)
const expanded = ref(true)

function typeOf(v: unknown): string {
  if (v === null) return 'null'
  if (Array.isArray(v)) return 'array'
  if (typeof v === 'object') return 'object'
  return typeof v
}
</script>

<template>
  <div class="json-viewer">
    <template v-if="isObj">
      <button class="json-toggle" type="button" @click="expanded = !expanded">
        <span class="json-brace">{{ isArr ? '[' : '{' }}</span>
        <span v-if="!expanded" class="json-ellipsis"> … </span>
        <span class="json-close-brace">{{ isArr ? ']' : '}' }}</span>
      </button>
      <div v-show="expanded" class="json-children">
        <div v-for="(entry, i) in entries" :key="entry[0]" class="json-row">
          <span class="json-key">{{ entry[0] }}</span>
          <span class="json-colon">: </span>
          <JsonViewer v-if="typeof entry[1] === 'object' && entry[1] !== null" :data="entry[1]" />
          <span v-else class="json-value" :class="`t-${typeOf(entry[1])}`">
            {{ entry[1] === null ? 'null' : typeof entry[1] === 'string' ? `"${entry[1]}"` : String(entry[1]) }}
          </span>
          <span v-if="i < entries.length - 1" class="json-comma">,</span>
        </div>
      </div>
    </template>
    <template v-else>
      <span class="json-value" :class="`t-${typeOf(data)}`">
        {{ data === null ? 'null' : typeof data === 'string' ? `"${data}"` : String(data) }}
      </span>
    </template>
  </div>
</template>

<style scoped>
.json-viewer {
  font-family: var(--app-font-mono);
  font-size: 12px;
  line-height: 1.6;
}
.json-toggle {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
  font-size: inherit;
}
.json-brace,
.json-close-brace {
  color: #9ca3af;
}
.json-ellipsis {
  color: #6b7280;
}
.json-children {
  padding-left: 14px;
}
.json-row {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
.json-key {
  color: #2563eb;
}
.json-colon,
.json-comma {
  color: #9ca3af;
}
.json-value.t-string {
  color: #16a34a;
}
.json-value.t-number {
  color: #f59e0b;
}
.json-value.t-boolean {
  color: #9333ea;
}
.json-value.t-null {
  color: #9ca3af;
  font-style: italic;
}
</style>

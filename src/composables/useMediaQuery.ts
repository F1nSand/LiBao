import { onBeforeUnmount, ref } from 'vue'

/** 响应式媒体查询：匹配状态变化时自动更新 isActive；无 matchMedia 时安全降级 false */
export function useMediaQuery(query: string) {
  const isActive = ref(false)
  if (typeof window !== 'undefined' && 'matchMedia' in window) {
    const mql = window.matchMedia(query)
    isActive.value = mql.matches
    const onChange = () => {
      isActive.value = mql.matches
    }
    mql.addEventListener('change', onChange)
    onBeforeUnmount(() => mql.removeEventListener('change', onChange))
  }
  return isActive
}

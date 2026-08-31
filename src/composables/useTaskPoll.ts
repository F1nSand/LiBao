import { onScopeDispose, ref, watch, type Ref } from 'vue'

/**
 * 任务/状态轮询（《02》前端设计 §5.1 FD-6 简单场景）：组件卸载自动 stop。
 */
export function useTaskPoll<T>(
  fetcher: () => Promise<T>,
  opts: { intervalMs?: number; enabled?: boolean | Ref<boolean> } = {},
) {
  const { intervalMs = 3000, enabled = true } = opts
  const data = ref<T | null>(null) as Ref<T | null>
  const error = ref<Error | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      data.value = await fetcher()
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e : new Error(String(e))
    } finally {
      loading.value = false
    }
  }

  function start(): void {
    if (timer) return
    void refresh()
    timer = setInterval(() => void refresh(), intervalMs)
  }

  function stop(): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  watch(
    () => (typeof enabled === 'boolean' ? enabled : enabled.value),
    (v) => (v ? start() : stop()),
    { immediate: true },
  )

  onScopeDispose(stop)

  return { data, error, loading, refresh, start, stop }
}

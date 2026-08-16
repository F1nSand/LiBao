import { defineStore } from 'pinia'
import { submitTask, listTasks, getTask, cancelTask, resumeTask } from '@/api/task'
import type { SubmitTaskRequest, Task } from '@/types'

/** 任务 store（docs/02 §7）：列表 + 状态过滤；详情页组件内自取数据 + SSE 订阅 */
export const useTaskStore = defineStore('task', {
  state: () => ({
    tasks: [] as Task[],
    total: 0,
    page: 1,
    pageSize: 20,
    statusFilter: '' as string,
    loading: false,
  }),
  actions: {
    async list(page?: number) {
      this.loading = true
      try {
        const res = await listTasks({
          page: page ?? this.page,
          page_size: this.pageSize,
          status: this.statusFilter || undefined,
        })
        this.tasks = res.items
        this.total = res.total
        this.page = res.page
      } finally {
        this.loading = false
      }
    },
    async submit(body: SubmitTaskRequest): Promise<string> {
      const res = await submitTask(body)
      await this.list()
      return res.task_id
    },
    async get(id: string): Promise<Task> {
      return getTask(id)
    },
    async cancel(id: string) {
      await cancelTask(id)
      await this.list()
    },
    async resume(id: string, confirm: Record<string, unknown> | null) {
      await resumeTask(id, confirm)
      await this.list()
    },
    setStatusFilter(status: string) {
      this.statusFilter = status
      void this.list(1)
    },
  },
})

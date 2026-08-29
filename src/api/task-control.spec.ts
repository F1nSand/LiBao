import { describe, it, expect, vi } from 'vitest'
import { httpPost } from './http'
import { recoverTask } from './task-control'

vi.mock('./http', () => ({
  httpGet: vi.fn(),
  httpPost: vi.fn(),
  ApiError: class ApiError extends Error {
    code: number
    constructor(code: number, message: string) {
      super(message)
      this.code = code
    }
  },
}))

const httpPostMock = vi.mocked(httpPost)

describe('recoverTask', () => {
  it('POST /tasks/{id}/recover 带幂等 key，返回 {task_id,status}', async () => {
    httpPostMock.mockResolvedValue({ task_id: 't1', status: 'running' })
    const result = await recoverTask('t1', 'key-abc')
    expect(httpPostMock).toHaveBeenCalledWith('/tasks/t1/recover', { idempotency_key: 'key-abc' })
    expect(result).toEqual({ task_id: 't1', status: 'running' })
  })

  it('缺省幂等 key 自动生成 uuid（非空）', async () => {
    httpPostMock.mockResolvedValue({ task_id: 't2', status: 'running' })
    await recoverTask('t2')
    const [, body] = httpPostMock.mock.calls.at(-1)!
    const key = (body as { idempotency_key: string }).idempotency_key
    expect(typeof key).toBe('string')
    expect(key.length).toBeGreaterThan(8)
  })
})

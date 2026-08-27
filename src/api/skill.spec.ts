import { describe, it, expect, vi, beforeEach } from 'vitest'
import { httpGet } from './http'
import { listSkills } from './skill'

vi.mock('./http', () => ({
  httpGet: vi.fn(),
}))

const mockedGet = vi.mocked(httpGet)

describe('api/skill（M7-A 简化 2026-08-25：只读两级目录，删 org CRUD）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('listSkills 无参 → GET /skills', () => {
    listSkills()
    expect(mockedGet).toHaveBeenCalledWith('/skills', { params: {} })
  })

  it('listSkills 带 workspace_id → GET /skills?workspace_id', () => {
    listSkills({ workspace_id: 'ws_001' })
    expect(mockedGet).toHaveBeenCalledWith('/skills', { params: { workspace_id: 'ws_001' } })
  })
})

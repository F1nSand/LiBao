import { describe, it, expect, vi, beforeEach } from 'vitest'
import { httpGet, httpPost, httpPatch, httpDelete } from './http'
import { listSkills, getSkill, createSkill, importSkill, updateSkill, deleteSkill } from './skill'

vi.mock('./http', () => ({
  httpGet: vi.fn(),
  httpPost: vi.fn(),
  httpPatch: vi.fn(),
  httpDelete: vi.fn(),
}))

const mockedGet = vi.mocked(httpGet)
const mockedPost = vi.mocked(httpPost)
const mockedPatch = vi.mocked(httpPatch)
const mockedDelete = vi.mocked(httpDelete)

describe('api/skill（M7-A Skills 契约，交接板 2026-08-20）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('listSkills 透传分页 query', () => {
    listSkills({ page: 2, page_size: 20 })
    expect(mockedGet).toHaveBeenCalledWith('/skills', { params: { page: 2, page_size: 20 } })
  })

  it('listSkills 无参默认空 query', () => {
    listSkills()
    expect(mockedGet).toHaveBeenCalledWith('/skills', { params: {} })
  })

  it('getSkill 命中 /:id', () => {
    getSkill('sk_001')
    expect(mockedGet).toHaveBeenCalledWith('/skills/sk_001')
  })

  it('createSkill POST /skills', () => {
    createSkill({ name: 'n', description: 'd', body: 'b' })
    expect(mockedPost).toHaveBeenCalledWith('/skills', { name: 'n', description: 'd', body: 'b' })
  })

  it('importSkill POST /skills/import', () => {
    importSkill({ url: 'https://github.com/x/y.git' })
    expect(mockedPost).toHaveBeenCalledWith('/skills/import', { url: 'https://github.com/x/y.git' })
  })

  it('updateSkill PATCH /:id（含 enabled 开关）', () => {
    updateSkill('sk_001', { enabled: true })
    expect(mockedPatch).toHaveBeenCalledWith('/skills/sk_001', { enabled: true })
  })

  it('deleteSkill DELETE /:id', () => {
    deleteSkill('sk_001')
    expect(mockedDelete).toHaveBeenCalledWith('/skills/sk_001')
  })
})

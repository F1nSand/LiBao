import { describe, it, expect, vi, beforeEach } from 'vitest'
import { httpGet, httpPost } from './http'
import {
  listCandidates,
  getCandidate,
  validateCandidate,
  publishCandidate,
  rejectCandidate,
  rollbackCandidate,
} from './evolution'

vi.mock('./http', () => ({
  httpGet: vi.fn(),
  httpPost: vi.fn(),
  httpPut: vi.fn(),
  httpPatch: vi.fn(),
  httpDelete: vi.fn(),
}))

const mockedGet = vi.mocked(httpGet)
const mockedPost = vi.mocked(httpPost)

describe('api/evolution（候选区，docs/06 §5 契约提案）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('listCandidates 透传 status/search/分页 query', () => {
    listCandidates({ status: 'approved', search: '计算器', page: 2, page_size: 20 })
    expect(mockedGet).toHaveBeenCalledWith('/evolution/candidates', {
      params: { status: 'approved', search: '计算器', page: 2, page_size: 20 },
    })
  })

  it('listCandidates 无过滤时不带额外 query', () => {
    listCandidates({})
    expect(mockedGet).toHaveBeenCalledWith('/evolution/candidates', { params: {} })
  })

  it('getCandidate 命中 /:id', () => {
    getCandidate('cand_1')
    expect(mockedGet).toHaveBeenCalledWith('/evolution/candidates/cand_1')
  })

  it('状态动作 POST 对应 path', () => {
    validateCandidate('cand_1')
    expect(mockedPost).toHaveBeenCalledWith('/evolution/candidates/cand_1/validate')
    publishCandidate('cand_4')
    expect(mockedPost).toHaveBeenCalledWith('/evolution/candidates/cand_4/publish')
    rejectCandidate('cand_2')
    expect(mockedPost).toHaveBeenCalledWith('/evolution/candidates/cand_2/reject')
    rollbackCandidate('cand_5')
    expect(mockedPost).toHaveBeenCalledWith('/evolution/candidates/cand_5/rollback')
  })
})

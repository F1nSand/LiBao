import { describe, it, expect, vi, beforeEach } from 'vitest'
import { httpGet, httpPost } from './http'
import { listConversations, createConversation } from './chat'

vi.mock('./http', () => ({
  httpGet: vi.fn(),
  httpPost: vi.fn(),
  httpDelete: vi.fn(),
}))

const mockedGet = vi.mocked(httpGet)
const mockedPost = vi.mocked(httpPost)

describe('api/chat 工作区线程（M7-B）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('listConversations 透传 workspace_id 过滤', () => {
    listConversations({ workspace_id: 'ws_001', page: 1, page_size: 20 })
    expect(mockedGet).toHaveBeenCalledWith('/conversations', {
      params: { workspace_id: 'ws_001', page: 1, page_size: 20 },
    })
  })

  it('createConversation 透传 workspace_id body', () => {
    createConversation({ title: 't', workspace_id: 'ws_001' })
    expect(mockedPost).toHaveBeenCalledWith('/conversations', { title: 't', workspace_id: 'ws_001' })
  })
})

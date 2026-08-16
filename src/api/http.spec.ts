import { describe, it, expect, beforeEach, vi } from 'vitest'
import MockAdapter from 'axios-mock-adapter'
import { ElMessage } from 'element-plus'
import { http, httpGet, httpPost, setAuthToken, onUnauthorized, ApiError } from './http'
import { resetUnavailable, isUnavailable, FEATURE } from './availability'

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

describe('http 信封解包', () => {
  let mock: MockAdapter

  beforeEach(() => {
    mock = new MockAdapter(http)
    setAuthToken(null)
  })

  it('code=0 时解包返回 data', async () => {
    mock.onGet('/ping').reply(200, { code: 0, message: 'ok', data: { ok: true }, trace_id: 't1' })
    const data = await httpGet<{ ok: boolean }>('/ping')
    expect(data).toEqual({ ok: true })
  })

  it('code!=0 时抛 ApiError 且携带 code/trace_id', async () => {
    mock.onGet('/fail').reply(200, { code: 40001, message: '参数缺失', data: null, trace_id: 't2' })
    await expect(httpGet('/fail')).rejects.toMatchObject({
      name: 'ApiError',
      code: 40001,
      message: '参数缺失',
      traceId: 't2',
    })
  })

  it('data 为 null 的 404 场景抛 ApiError', async () => {
    mock.onPost('/nope').reply(200, { code: 40401, message: '会话不存在', data: null })
    await expect(httpPost('/nope', {})).rejects.toBeInstanceOf(ApiError)
  })

  it('HTTP 401 触发 onUnauthorized 回调', async () => {
    const cb = vi.fn()
    onUnauthorized(cb)
    mock.onGet('/secret').reply(401, { code: 40101, message: '未登录', data: null })
    await expect(httpGet('/secret')).rejects.toBeTruthy()
    expect(cb).toHaveBeenCalled()
  })

  it('注入 Bearer token', async () => {
    setAuthToken('abc')
    let captured: string | undefined
    mock.onGet('/me').reply((config) => {
      captured = config.headers?.Authorization as string
      return [200, { code: 0, message: 'ok', data: null }]
    })
    await httpGet('/me')
    expect(captured).toBe('Bearer abc')
  })
})

describe('接真实后端优雅降级（HTTP 404 → 打标）', () => {
  let mock: MockAdapter

  beforeEach(() => {
    mock = new MockAdapter(http)
    setAuthToken(null)
    resetUnavailable()
    vi.mocked(ElMessage.error).mockClear()
  })

  it('HTTP 404（端点未实现）→ 打标 + 不 toast', async () => {
    mock.onGet('/users').reply(404, { detail: 'Not Found' })
    await expect(httpGet('/users')).rejects.toBeTruthy()
    expect(isUnavailable(FEATURE.users)).toBe(true)
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('信封 40401 业务错误（HTTP 200）→ toast + 不打标', async () => {
    mock.onGet('/users').reply(200, { code: 40401, message: '用户不存在', data: null })
    await expect(httpGet('/users')).rejects.toBeInstanceOf(ApiError)
    expect(isUnavailable(FEATURE.users)).toBe(false)
    expect(ElMessage.error).toHaveBeenCalled()
  })

  it('信封 404xx 含「未实现」标记 → 打标且不 toast', async () => {
    mock.onGet('/users').reply(200, { code: 40401, message: '接口未实现', data: null })
    await expect(httpGet('/users')).rejects.toBeInstanceOf(ApiError)
    expect(isUnavailable(FEATURE.users)).toBe(true)
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('已降级功能 → fail-fast 短路，不再发网络请求', async () => {
    mock.onGet('/users').reply(404, { detail: 'Not Found' })
    await expect(httpGet('/users')).rejects.toBeTruthy()
    expect(isUnavailable(FEATURE.users)).toBe(true)

    // 短路应使 make() 不被调用：若仍发请求则命中会抛异常的 handler → 断言 code 40401 失败
    mock.onGet('/users').reply(() => {
      throw new Error('不应发起网络请求')
    })
    await expect(httpGet('/users')).rejects.toMatchObject({ code: 40401, message: '接口未实现' })
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('未知路径的 HTTP 404 不误标任何 feature', async () => {
    mock.onGet('/ping').reply(404, { detail: 'Not Found' })
    await expect(httpGet('/ping')).rejects.toBeTruthy()
    expect(isUnavailable(FEATURE.users)).toBe(false)
    expect(isUnavailable(FEATURE.trajectory)).toBe(false)
  })
})

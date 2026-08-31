import { test, expect } from '@playwright/test'
import { gotoChat, sendMessage } from '../e2e/helpers'

/**
 * 真实后端契约冒烟（playwright.real.config.ts）：对接本机后端 :8000。
 * - API 层：验证信封/字段契约（含改名后的 project_instructions roundtrip）
 * - UI 层：工作区创建 → .agent 骨架 → 文件操作（前后端集成）
 * - 聊天：真实 LLM 流式 → 落库（SSE 契约；需在 ~/.LiBao/settings.json 配 DeepSeek key）
 * 用例自行清理创建的临时工作区。
 */

const WS_NAME = `real-e2e-${Date.now()}`
const BASE = `${process.env.E2E_BACKEND_URL ?? 'http://127.0.0.1:8000'}/api/v1`

test.describe('真实后端契约冒烟', () => {
  test('后端健康 + workspace API 契约（project_instructions roundtrip）', async ({ request }) => {
    const health = await request.get(`${BASE}/system/health`)
    expect(health.ok()).toBeTruthy()
    const hb = await health.json()
    expect(hb.code).toBe(0)
    expect(hb.data.status).toBe('ok')

    // 创建带 project_instructions 的工作区（改名后字段契约：旧 system_prompt_fragment 已废）
    const created = await request.post(`${BASE}/workspaces`, {
      data: { name: WS_NAME, description: '真实后端 e2e', project_instructions: '你是 e2e 项目助手' },
    })
    expect(created.ok()).toBeTruthy()
    const cj = await created.json()
    expect(cj.code).toBe(0)
    const ws = cj.data
    expect(ws.name).toBe(WS_NAME)
    expect(ws.project_instructions).toBe('你是 e2e 项目助手')
    expect(ws.root_path).toBeTruthy() // 后端托管真实目录

    // 列表包含
    const listed = await request.get(`${BASE}/workspaces?page=1&page_size=100`)
    const lj = await listed.json()
    expect(lj.data.items.map((w: { name: string }) => w.name)).toContain(WS_NAME)

    // 清理：硬删（级联）
    const del = await request.delete(`${BASE}/workspaces/${ws.id}`)
    expect(del.ok()).toBeTruthy()
    const dj = await del.json()
    expect(dj.code).toBe(0)
  })

  test('聊天契约拒绝越界工作区 file_refs', async ({ request }) => {
    const created = await request.post(`${BASE}/workspaces`, {
      data: { name: `${WS_NAME}-file-ref`, description: 'file_refs contract', project_instructions: '' },
    })
    expect(created.ok()).toBeTruthy()
    const cj = await created.json()
    expect(cj.code).toBe(0)
    const ws = cj.data

    try {
      // 该请求在建立 SSE 前即完成路径校验，不需要真实 LLM；越界路径必须统一返回 40015。
      const rejected = await request.post(`${BASE}/chat/stream`, {
        data: {
          conversation_id: null,
          workspace_id: ws.id,
          message: {
            content: '',
            role: 'user',
            attachments: [],
            file_refs: [{ path: '../outside.txt' }],
          },
          stream: true,
        },
      })
      expect(rejected.ok()).toBeTruthy()
      const body = await rejected.json()
      expect(body.code).toBe(40015)
    } finally {
      const del = await request.delete(`${BASE}/workspaces/${ws.id}`)
      expect(del.ok()).toBeTruthy()
    }
  })

  test('UI 工作区全流程（创建 → .agent 骨架 → 文件操作 → 删除清理）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')

    // 创建
    await page.getByRole('button', { name: '新建工作区' }).click()
    await page.locator('.el-dialog').getByPlaceholder('如 产品文档').fill(WS_NAME)
    await page.locator('.el-dialog').getByRole('button', { name: '创建', exact: true }).click()
    const card = page.locator('.ws-card', { hasText: WS_NAME })
    await expect(card).toBeVisible({ timeout: 10_000 })

    // 进入详情 → 真实后端 init_agent_skeleton 生成的 .agent 骨架可见
    await card.getByRole('button', { name: '进入工作区' }).click()
    const tree = page.locator('.rm-tree-wrap')
    const agentRow = tree.locator('.el-tree-node__content').filter({ hasText: '.agent' }).first()
    await expect(agentRow).toBeVisible({ timeout: 10_000 })
    await agentRow.locator('.el-tree-node__expand-icon').click()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'agent.md' })).toBeVisible({ timeout: 10_000 })

    // 新建文件 → 出现
    await page.locator('.rm-head-right').getByRole('button', { name: '新建' }).click()
    await page.getByRole('menuitem', { name: '新建文件', exact: true }).click()
    await page.locator('.el-dialog').getByPlaceholder(/无后缀默认/).fill('e2e临时')
    await page.locator('.el-dialog').getByRole('button', { name: '创建', exact: true }).click()
    const frow = tree.locator('.el-tree-node__content', { hasText: 'e2e临时.txt' })
    await expect(frow).toBeVisible({ timeout: 10_000 })

    // 行尾三连 → 重命名
    await frow.hover()
    await frow.locator('.rm-more').click()
    await page.getByRole('menuitem', { name: '重命名', exact: true }).click()
    await page.locator('.el-dialog').getByPlaceholder('新名称').fill('e2e临时改.md')
    await page.locator('.el-dialog').getByRole('button', { name: '保存', exact: true }).click()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'e2e临时改.md' })).toBeVisible({ timeout: 10_000 })

    // 删除文件
    const frow2 = tree.locator('.el-tree-node__content', { hasText: 'e2e临时改.md' }).first()
    await frow2.hover()
    await frow2.locator('.rm-more').click()
    await page.getByRole('menuitem', { name: '删除', exact: true }).click()
    await page.locator('.el-message-box').getByRole('button', { name: '确定' }).click()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'e2e临时改.md' })).toHaveCount(0, { timeout: 10_000 })

    // 清理：回列表删除工作区（强确认输入名称）
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: WS_NAME }).getByRole('button', { name: '删除' }).click()
    await page.locator('.el-message-box input').fill(WS_NAME)
    await page.locator('.el-message-box').getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.ws-card', { hasText: WS_NAME })).toHaveCount(0, { timeout: 10_000 })
  })

  test('聊天流式（真实 LLM，SSE 契约 + 落库）', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '用一句话介绍你自己，不超过 20 字')

    // 用户气泡出现（POST /chat/stream 建立会话）
    await expect(page.locator('.msg.user').first()).toBeVisible({ timeout: 15_000 })
    // assistant 完整回复（真实 LLM 流式 → done 落库；耗时较长，宽超时）
    await expect(page.locator('.msg.assistant .markdown-body').first()).toBeVisible({ timeout: 120_000 })
  })
})

import { test, expect } from '@playwright/test'
import { gotoChat, sendMessage } from './helpers'

test.describe('对话流式（核心演示）', () => {
  test('计算 6*7 → 中断确认 → 回填 42 + 工具卡', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '计算 6*7')

    // 中断确认弹窗
    await expect(page.locator('.el-dialog').filter({ hasText: '工具调用确认' })).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: '确认执行' }).click()

    // 流式完成 → 文本含 42；工具行显示摘要 + 状态「完成」
    await expect(page.locator('.markdown-body').first()).toContainText('42', { timeout: 15_000 })
    await expect(page.locator('.tool-row')).toHaveCount(1, { timeout: 10_000 })
    await expect(page.locator('.tool-row').first()).toContainText('完成')
    // 工具行收起预览 = `工具 · 摘要`（calculator + 入参表达式）
    await expect(page.locator('.tool-row').first()).toContainText('calculator')
    // Bug 1 回归守卫：一轮完成后输入框恢复可用
    await expect(page.locator('.composer textarea')).toBeEnabled({ timeout: 10_000 })
  })

  test('拒绝分支 → 显示已取消', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '危险操作')

    await expect(page.locator('.el-dialog').filter({ hasText: '工具调用确认' })).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: '拒绝' }).click()

    await expect(page.locator('.markdown-body').first()).toContainText('已取消', { timeout: 15_000 })
  })

  test('默认分支（web_search 占位→回填）', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '什么是 SSE')

    await expect(page.locator('.tool-row')).toContainText('web_search', { timeout: 15_000 })
    await expect(page.locator('.markdown-body').first()).toContainText('检索', { timeout: 15_000 })
    // Bug 1 回归守卫：单轮完成后输入框恢复可用
    await expect(page.locator('.composer textarea')).toBeEnabled({ timeout: 10_000 })
  })

  test('停止运行中的 Agent → 状态显示已中断且保留当前页部分回复', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '[slow]')

    const stop = page.getByRole('button', { name: '停止' })
    await expect(stop).toBeVisible({ timeout: 10_000 })
    await stop.click()

    await expect(page.locator('.run-status')).toContainText('已中断', { timeout: 10_000 })
    await expect(page.getByRole('button', { name: '停止' })).toHaveCount(0)
    await expect(page.locator('.composer textarea')).toBeEnabled()
  })
})

test.describe('长任务断线恢复', () => {
  test('[disconnect] 断流 → 自动重连 → 收敛已完成', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '[disconnect]')

    // 断流后自动进入重连（不标记失败、不重发）
    await expect(page.locator('.run-status')).toContainText('重连', { timeout: 10_000 })
    await expect(page.locator('.run-status')).toContainText('已完成', { timeout: 15_000 })
    await expect(page.locator('.composer textarea')).toBeEnabled({ timeout: 10_000 })
  })

  test('[fail-recoverable] → 从断点继续 → 完成，且无危险「重试」按钮', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '[fail-recoverable]')

    const errorBar = page.locator('.stream-error')
    await expect(errorBar).toContainText('从断点继续', { timeout: 10_000 })
    await expect(errorBar).toContainText('重新执行（可能重复操作）')
    await expect(errorBar.getByRole('button', { name: '重试' })).toHaveCount(0)

    await page.getByRole('button', { name: '从断点继续' }).click()
    await expect(page.locator('.run-status')).toContainText('已完成', { timeout: 15_000 })
    await expect(page.locator('.composer textarea')).toBeEnabled({ timeout: 10_000 })
  })

  test('[fail] 普通失败 → 仅「重新执行（可能重复操作）」可重发原消息', async ({ page }) => {
    // mock-fast 下 [fail] 脚本 0ms 完成，错误条消失窗口不可观测，改用请求计数验证「重新执行」确实重新 POST 原 chat
    let streamPosts = 0
    page.on('request', (req) => {
      if (req.url().includes('/chat/stream')) streamPosts += 1
    })

    await gotoChat(page)
    await sendMessage(page, '[fail]')

    const errorBar = page.locator('.stream-error')
    await expect(errorBar).toContainText('重新执行（可能重复操作）', { timeout: 10_000 })
    await expect(errorBar).not.toContainText('从断点继续')
    await expect(errorBar.getByRole('button', { name: '重试' })).toHaveCount(0)
    expect(streamPosts).toBe(1)

    // 点击「重新执行」→ 重发原 chat（再次触发 [fail] 脚本）→ 错误条再次出现
    await page.getByRole('button', { name: '重新执行（可能重复操作）' }).click()
    await expect(errorBar).toContainText('发送失败', { timeout: 15_000 })
    expect(streamPosts).toBe(2)
  })
})

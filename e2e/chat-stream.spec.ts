import { test, expect } from '@playwright/test'
import { gotoChat, sendMessage } from './helpers'

test.describe('对话流式（核心演示）', () => {
  test('计算 6*7 → 中断确认 → 回填 42 + 工具卡', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '计算 6*7')

    // 中断确认弹窗
    await expect(page.locator('.el-dialog').filter({ hasText: '工具调用确认' })).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: '确认执行' }).click()

    // 流式完成 → 文本含 42；工具卡只显示名称+状态（参数已隐藏，断言状态标签“完成”）
    await expect(page.locator('.markdown-body').first()).toContainText('42', { timeout: 15_000 })
    await expect(page.locator('.tool-card')).toHaveCount(1, { timeout: 10_000 })
    await expect(page.locator('.tool-card').first()).toContainText('完成')
    // 回归守卫：工具卡默认折叠，入参（calculator input 含表达式）不直接展示；点「参数」才回放
    await expect(page.locator('.tool-card').first()).not.toContainText('6*7')
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

    await expect(page.locator('.tool-card')).toContainText('web_search', { timeout: 15_000 })
    await expect(page.locator('.markdown-body').first()).toContainText('检索', { timeout: 15_000 })
    // Bug 1 回归守卫：单轮完成后输入框恢复可用
    await expect(page.locator('.composer textarea')).toBeEnabled({ timeout: 10_000 })
  })
})

import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('响应式侧边栏', () => {
  test('/chat 窄屏保持展开（会话列表可用）；其它页自动收起', async ({ page }) => {
    await gotoChat(page) // 落在 /chat

    await page.setViewportSize({ width: 1280, height: 800 })
    await expect(page.locator('.sidebar')).not.toHaveClass(/collapsed/)
    await expect(page.locator('.conv-list')).toBeVisible()

    // /chat 窄屏不自动收起（会话列表在侧栏内需可用）
    await page.setViewportSize({ width: 800, height: 800 })
    await expect(page.locator('.sidebar')).not.toHaveClass(/collapsed/)
    await expect(page.locator('.conv-list')).toBeVisible()

    // 其它页窄屏自动收起、会话列表隐藏
    await page.goto('/kb')
    await page.setViewportSize({ width: 800, height: 800 })
    await expect(page.locator('.sidebar')).toHaveClass(/collapsed/)
    await expect(page.locator('.conv-list')).toBeHidden()

    // 回 /chat 恢复展开
    await page.goto('/chat')
    await expect(page.locator('.sidebar')).not.toHaveClass(/collapsed/)
    await expect(page.locator('.conv-list')).toBeVisible()
  })

  test('顶部折叠按钮（宽窗口手动折叠/展开）', async ({ page }) => {
    await gotoChat(page)
    await page.setViewportSize({ width: 1280, height: 800 })
    await expect(page.locator('.sidebar')).not.toHaveClass(/collapsed/)

    await page.locator('.logo-collapse').click()
    await expect(page.locator('.sidebar')).toHaveClass(/collapsed/)

    await page.locator('.logo-collapse').click()
    await expect(page.locator('.sidebar')).not.toHaveClass(/collapsed/)
  })
})

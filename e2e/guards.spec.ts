import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('单用户本地模式：无需登录直访', () => {
  test('直访 /chat 直接可见工作台（不再跳 /login）', async ({ page }) => {
    await gotoChat(page)
    await expect(page.locator('.chat-view')).toBeVisible()
    await expect(page).not.toHaveURL(/\/login/)
  })

  test('直访 /tools、/kb 均可见侧栏与页面内容', async ({ page }) => {
    await page.goto('/tools')
    await expect(page.locator('.sidebar')).toBeVisible()
    await expect(page.locator('.app-page')).toBeVisible()

    await page.goto('/kb')
    await expect(page.locator('.sidebar')).toBeVisible()
    await expect(page.locator('.app-page')).toBeVisible()
  })

  test('设置气泡全 5 子项可见（无角色过滤）', async ({ page }) => {
    await gotoChat(page)
    await page.locator('.settings-toggle').click()
    await expect(page.locator('.settings-popover .sub-item')).toHaveCount(5)
  })
})

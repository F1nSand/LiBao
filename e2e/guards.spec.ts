import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('路由守卫', () => {
  test('未登录访问 /chat → 重定向 /login', async ({ page }) => {
    await page.goto('/chat')
    await page.waitForURL('**/login**')
  })

  test('viewer 访问 /tools（developer+）→ 重定向 /chat', async ({ page }) => {
    await login(page, 'viewer', 'viewer123')
    await page.goto('/tools')
    await page.waitForURL('**/chat')
  })

  test('viewer 设置气泡只见 记忆，admin 全见', async ({ page }) => {
    await login(page, 'viewer', 'viewer123')
    // 设置按钮对所有人可见（子项按角色过滤）；任务已删，viewer 只剩无 roles 限制的「记忆」
    await expect(page.locator('.settings-toggle')).toHaveCount(1)
    await page.locator('.settings-toggle').click()
    await expect(page.locator('.settings-popover .sub-item', { hasText: '任务' })).toHaveCount(0)
    await expect(page.locator('.settings-popover .sub-item', { hasText: '记忆' })).toHaveCount(1)
    await expect(page.locator('.settings-popover .sub-item', { hasText: '系统' })).toHaveCount(0)
    await expect(page.locator('.settings-popover .sub-item', { hasText: '设置' })).toHaveCount(0)

    // 登出换 admin
    await page.locator('.user-chip').click()
    await page.getByText('退出登录').click()
    await page.waitForURL('**/login**')
    await login(page, 'admin', 'admin123')
    await page.locator('.settings-toggle').click()
    await expect(page.locator('.settings-popover .sub-item', { hasText: '系统' })).toHaveCount(1)
    await expect(page.locator('.settings-popover .sub-item', { hasText: '设置' })).toHaveCount(1)
  })
})

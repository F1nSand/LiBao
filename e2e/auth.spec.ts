import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('认证流程', () => {
  test('错误密码 → 提示且停留登录页', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('请输入用户名').fill('admin')
    await page.getByPlaceholder('请输入密码').fill('wrong-password')
    await page.getByRole('button', { name: /登\s*录/ }).click()
    await expect(page.locator('.el-message')).toContainText('用户名或密码错误')
    await expect(page).toHaveURL(/\/login/)
  })

  test('正确登录 → 跳 /chat，刷新保持登录', async ({ page }) => {
    await login(page)
    await expect(page.locator('.sidebar')).toBeVisible()
    await expect(page.locator('.chat-view')).toBeVisible()
    await page.reload()
    await expect(page.locator('.sidebar')).toBeVisible()
  })

  test('登出 → 回登录页', async ({ page }) => {
    await login(page)
    await page.locator('.user-chip').click()
    await page.getByText('退出登录').click()
    await page.waitForURL('**/login')
  })
})

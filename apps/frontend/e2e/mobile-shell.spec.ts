import { test, expect } from '@playwright/test'

test.describe('手机端导航抽屉', () => {
  test('抽屉覆盖主内容，支持遮罩、Escape 和路由后自动关闭', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/chat')
    await page.locator('.chat-view').waitFor({ state: 'visible', timeout: 15_000 })

    await expect(page.locator('.sidebar')).not.toHaveClass(/collapsed/)
    await expect(page.locator('.sidebar')).not.toHaveClass(/drawer-open/)
    await expect(page.locator('.app-main')).toHaveCSS('width', '390px')

    await page.getByRole('button', { name: '打开导航菜单' }).click()
    await expect(page.locator('.sidebar')).toHaveClass(/drawer-open/)
    await expect(page.locator('.sidebar-backdrop')).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(page.locator('.sidebar')).not.toHaveClass(/drawer-open/)

    await page.getByRole('button', { name: '打开导航菜单' }).click()
    await page.locator('.sidebar-backdrop').click({ position: { x: 380, y: 420 } })
    await expect(page.locator('.sidebar')).not.toHaveClass(/drawer-open/)

    await page.getByRole('button', { name: '打开导航菜单' }).click()
    await page.getByRole('link', { name: '知识库' }).click()
    await expect(page).toHaveURL(/\/kb$/)
    await expect(page.locator('.sidebar')).not.toHaveClass(/drawer-open/)
  })
})

import { test, expect } from '@playwright/test'

test.describe('主题配色切换器', () => {
  test('设置页「主题」tag 弹气泡；点选后主色变化并持久化；刷新保留', async ({ page }) => {
    await page.goto('/settings')
    await page.locator('.settings-tag-row').waitFor({ state: 'visible', timeout: 15_000 })

    // 设置页 tag 行：Provider 配置（active）+ 通知 + 主题 依次排开
    await expect(page.locator('.settings-tag', { hasText: 'Provider 配置' })).toHaveClass(/active/)
    await expect(page.locator('.notif-tag')).toBeVisible()
    const btn = page.locator('.theme-tag')
    await expect(btn).toBeVisible()

    // 默认靛蓝
    const primary = () =>
      page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--app-primary').trim())
    expect(await primary()).toBe('#6366f1')

    // 弹气泡 → 选翠绿
    await btn.click()
    await expect(page.locator('.theme-popover')).toBeVisible()
    await page.locator('.theme-swatch', { hasText: '翠绿' }).click()
    await expect
      .poll(async () => primary())
      .toBe('#22c55e')
    expect(await page.evaluate(() => localStorage.getItem('agent.theme'))).toBe('green')

    // 刷新保留
    await page.reload()
    await page.locator('.theme-tag').waitFor()
    await expect.poll(async () => primary()).toBe('#22c55e')
  })
})

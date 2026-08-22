import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('主题配色切换器', () => {
  test('短袖按钮弹气泡；点选后主色变化并持久化；刷新保留', async ({ page }) => {
    await gotoChat(page)

    // 短袖按钮存在（通知左侧）
    const btn = page.locator('.theme-btn')
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
    await page.locator('.theme-btn').waitFor()
    await expect.poll(async () => primary()).toBe('#22c55e')
  })
})

import { test, expect } from '@playwright/test'

test.describe('主题配色切换器', () => {
  test('设置页「主题」tab 切 pane；点选后主色变化并持久化；刷新保留', async ({ page }) => {
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

    // 点「主题」→ 内容区切到 theme pane（不再是悬浮气泡）
    await btn.click()
    await expect(page.locator('.theme-pane')).toBeVisible()
    await page.locator('.theme-swatch', { hasText: '翠绿' }).click()
    await expect
      .poll(async () => primary())
      .toBe('#22c55e')
    expect(await page.evaluate(() => localStorage.getItem('agent.theme'))).toBe('green')

    // 刷新保留；默认 tab 回 provider，主色已持久化
    await page.reload()
    await page.locator('.theme-tag').waitFor()
    await expect.poll(async () => primary()).toBe('#22c55e')
  })

  test('设置页 tab 切换：通知 pane 展示列表与未读徽标', async ({ page }) => {
    await page.goto('/settings')
    await page.locator('.notif-tag').click()
    await expect(page.locator('.notif-pane')).toBeVisible()
    await expect(page.locator('.notif-item').first()).toBeVisible()
    // 徽标宽匹配（mock SSE 3s 后会 +1，避免竞态断言精确数字）
    await expect(page.locator('.notif-tag-badge')).toHaveText(/[1-9]/)
  })
})

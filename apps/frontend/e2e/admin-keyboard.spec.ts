import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('管理台键盘交互', () => {
  test('知识库集合可以用 Enter/Space 选择', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/kb')
    const collections = page.locator('.kb-col-item')
    await expect(collections.first()).toBeVisible({ timeout: 15_000 })
    await collections.first().focus()
    await collections.first().press('Space')
    await expect(collections.first()).toHaveAttribute('aria-current', 'page')
    await collections.first().press('ArrowDown')
    if ((await collections.count()) > 1) await expect(collections.nth(1)).toBeFocused()
    await collections.nth(1).press('Enter')
    await expect(collections.nth(1)).toBeFocused()
  })

  test('系统日志的 trace 操作可通过键盘打开详情', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/system')
    const trace = page.locator('.trace-link').first()
    await expect(trace).toBeVisible({ timeout: 15_000 })
    await trace.focus()
    await trace.press('Enter')
    await expect(page.locator('.el-drawer')).toContainText('Trace 全链路')
    const traceHeads = page.locator('.tl-head')
    if ((await traceHeads.count()) > 1) {
      await traceHeads.first().focus()
      await traceHeads.first().press('ArrowDown')
      await expect(traceHeads.nth(1)).toBeFocused()
    }
  })

  test('设置 tab 与主题 swatch 支持方向键前的 Tab/Space 语义', async ({ page }) => {
    await page.goto('/settings')
    const themeTab = page.getByRole('tab', { name: '主题' })
    await themeTab.focus()
    await themeTab.press('Space')
    await expect(page.locator('.theme-pane')).toBeVisible()

    const green = page.locator('.theme-swatch', { hasText: '翠绿' })
    await green.focus()
    await green.press('Space')
    await expect(green).toHaveAttribute('aria-pressed', 'true')
    await expect(green).toBeFocused()
    await green.press('ArrowRight')
    await expect(page.locator('.theme-swatch').nth(3)).toBeFocused()
  })
})

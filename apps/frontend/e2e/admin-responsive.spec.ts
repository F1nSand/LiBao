import { test, expect } from '@playwright/test'
import { gotoChat, PRIMARY_ROUTES, RESPONSIVE_VIEWPORTS } from './helpers'

test.describe('管理台响应式矩阵', () => {
  test('390/800/1440 三档主路由不产生页面级横向滚动', async ({ page }) => {
    await gotoChat(page)
    for (const viewport of RESPONSIVE_VIEWPORTS) {
      await page.setViewportSize(viewport)
      for (const route of PRIMARY_ROUTES) {
        await page.goto(route)
        await page.locator('.app-page, .chat-view').first().waitFor({ state: 'visible', timeout: 15_000 })
        const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
        expect(scrollWidth, `${route} @ ${viewport.name} ${viewport.width}px`).toBeLessThanOrEqual(viewport.width)
      }
    }
  })

  test('窄屏弹窗宽度保留视口边距', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/tools')
    await page.locator('.tool-table').waitFor({ state: 'visible', timeout: 15_000 })
    await page.getByRole('button', { name: '注册工具' }).click()
    const dialog = page.locator('.el-dialog:visible').last()
    const box = await dialog.boundingBox()
    expect(box).toBeTruthy()
    if (box) expect(box.width).toBeLessThanOrEqual(366)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  })
})

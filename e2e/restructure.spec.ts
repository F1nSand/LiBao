import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('布局重构', () => {
  test('Chat「会话|轨迹」切换：轨迹内嵌、composer 隐藏', async ({ page }) => {
    await login(page)
    // 侧栏选第一个会话
    await page.locator('.conv-item').first().click()
    await expect(page.locator('.composer textarea')).toBeVisible()

    // 切「轨迹」→ 内嵌时间轴出现、composer 隐藏
    await page.locator('.el-radio-button', { hasText: '轨迹' }).click()
    await expect(page.locator('.tj-timeline')).toBeVisible()
    await expect(page.locator('.composer textarea')).toBeHidden()

    // 切回「会话」→ composer 恢复
    await page.locator('.el-radio-button', { hasText: '会话' }).click()
    await expect(page.locator('.composer textarea')).toBeVisible()
  })

  test('侧栏新建会话 → 导航到 /chat', async ({ page }) => {
    await login(page)
    await page.goto('/tools')
    await page.locator('.conv-add').click()
    await page.waitForURL('**/chat')
  })

  test('设置气泡：点击展开、点子项跳转并高亮', async ({ page }) => {
    await login(page)
    await expect(page.locator('.settings-popover')).toBeHidden()

    // 点设置弹气泡（admin 全 5 项，任务已删、技能已加、候选区已删）
    await page.locator('.settings-toggle').click()
    await expect(page.locator('.settings-popover .sub-item')).toHaveCount(5)

    // 点子项 → 跳转 /tools 且设置按钮高亮
    await page.locator('.settings-popover .sub-item', { hasText: '工具' }).click()
    await expect(page).toHaveURL(/\/tools/)
    await expect(page.locator('.settings-toggle')).toHaveClass(/active/)
  })
})

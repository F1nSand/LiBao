import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('工具页：批量启停', () => {
  test('批量启用跳过已启用项，列表不刷新且状态即时生效', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/tools')
    await page.locator('.tool-table').waitFor({ state: 'visible' })

    const calculator = page.locator('.tool-table .el-table__row', { hasText: 'calculator' })
    const webSearch = page.locator('.tool-table .el-table__row', { hasText: 'web_search' })
    await calculator.locator('.el-switch').click()
    await expect(calculator.locator('.el-switch')).not.toHaveClass(/is-checked/)

    await calculator.locator('.el-checkbox').click()
    await webSearch.locator('.el-checkbox').click()
    await expect(page.locator('[data-testid="tool-batch-bar"]')).toContainText('已选 2 项')

    const navigationCount = await page.evaluate(() => performance.getEntriesByType('navigation').length)
    await page.getByRole('button', { name: '启用所选' }).click()
    const confirm = page.locator('.el-message-box')
    await expect(confirm).toContainText('启用所选 1 个工具')
    await confirm.getByRole('button', { name: '启用' }).click()

    await expect(calculator.locator('.el-switch')).toHaveClass(/is-checked/)
    await expect(page.locator('[data-testid="tool-batch-bar"]')).toBeHidden()
    expect(await page.evaluate(() => performance.getEntriesByType('navigation').length)).toBe(navigationCount)
  })
})

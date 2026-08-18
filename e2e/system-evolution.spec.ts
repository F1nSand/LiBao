import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('系统候选区（M6 契约提案，docs/06 §5）', () => {
  test('候选区 tab 渲染种子 + 状态筛选 + 详情抽屉', async ({ page }) => {
    await login(page)
    await page.goto('/system')
    await page.getByRole('tab', { name: '候选区' }).click()

    // 种子 5 条（多状态）
    await expect(page.locator('.evolve-table .el-table__row').first()).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('.evolve-table .el-table__row')).toHaveCount(5)
    await expect(page.locator('.evolve-total')).toContainText('共 5 条')

    // 状态筛选 → 已批准 1 条
    await page.locator('.evolve-toolbar .el-select__wrapper').click()
    await page.locator('.el-select-dropdown__item:has-text("已批准")').click()
    await expect(page.locator('.evolve-table .el-table__row')).toHaveCount(1)

    // 行点击 → 详情抽屉含变更契约字段
    await page.locator('.evolve-table .el-table__row').first().click()
    await expect(page.locator('.evolve-detail')).toContainText('失败证据', { timeout: 5_000 })
    await expect(page.locator('.evolve-detail')).toContainText('推断根因')
  })
})

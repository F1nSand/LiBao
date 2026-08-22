import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('工具页：元工具与常规工具区分（docs 03 §5.5，meta 字段）', () => {
  test('tool_search 标记元工具 + 类别筛选 + 搜索排除元工具', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/tools')
    await page.locator('.tool-table').waitFor({ state: 'visible' })

    // tool_search 行带「元工具」标签；calculator 为「常规工具」（类别列在行内，行级断言避开多 el-tag 严格模式）
    const metaRow = page.locator('.tool-table .el-table__row', { hasText: 'tool_search' })
    await expect(metaRow).toBeVisible({ timeout: 10_000 })
    await expect(metaRow).toContainText('元工具')
    const calcRow = page.locator('.tool-table .el-table__row', { hasText: 'calculator' })
    await expect(calcRow).toContainText('常规工具')

    // 筛选「元工具」→ 只剩 tool_search（元工具置顶，全部时在最前）
    await page.locator('.tool-search-wrap .el-radio-button', { hasText: '元工具' }).click()
    await expect(page.locator('.tool-table .el-table__row')).toHaveCount(1)
    await expect(page.locator('.tool-table .el-table__row')).toContainText('tool_search')

    // 搜索「search」→ tool_search 被排除（元工具不发现自身），返回常规匹配 web_search
    await page.locator('.tool-search input').fill('search')
    await page.locator('.tool-search button', { hasText: '搜索' }).click()
    await expect(page.locator('.tool-search-result')).toBeVisible()
    await expect(page.locator('.tool-search-result')).toContainText('web_search')
    await expect(page.locator('.tool-search-result')).not.toContainText('tool_search')
  })
})

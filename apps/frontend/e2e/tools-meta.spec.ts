import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('工具页：元工具与常规工具区分（《02》接口契约 §5.5，meta 字段）', () => {
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

  test('MCP 工具显示 MCP 分类，且不进入常规工具筛选', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/mcp')
    await page.getByRole('button', { name: '注册 MCP' }).first().click()

    const dialog = page.locator('.el-dialog:visible').last()
    await dialog.locator('input').nth(1).fill('http://mcp.local/mcp')
    await dialog.getByRole('button', { name: '注册' }).click()
    await expect(page.locator('.mcp-table .el-table__row')).toHaveCount(1)

    await page.goto('/tools')
    await page.locator('.tool-table').waitFor({ state: 'visible' })
    const mcpRows = page.locator('.tool-table .el-table__row', { hasText: 'mcp_' })
    await expect(mcpRows).toHaveCount(2)
    await expect(mcpRows.first()).toContainText('MCP')

    await page.locator('.tool-search-wrap .el-radio-button', { hasText: 'MCP' }).click()
    await expect(page.locator('.tool-table .el-table__row')).toHaveCount(2)
    await page.locator('.tool-search-wrap .el-radio-button', { hasText: '常规工具' }).click()
    await expect(page.locator('.tool-table .el-table__row', { hasText: 'mcp_' })).toHaveCount(0)

    await page.goto('/mcp')
    await page.locator('.mcp-table .el-table__row').first().getByRole('button', { name: '删除' }).click()
    await page.locator('.el-message-box:visible').getByRole('button', { name: '确定' }).click()
    await expect(page.locator('.mcp-table .el-table__row')).toHaveCount(0)
  })
})

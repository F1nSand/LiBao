import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('Skills 目录页（M7-A 简化：只读两级目录）', () => {
  test('设置气泡 → /skills：全局种子列表（名称/描述/位置，只读无操作列）', async ({ page }) => {
    await gotoChat(page)

    // 设置气泡 → 技能子项 → 跳转 /skills
    await page.locator('.settings-toggle').click()
    await page.locator('.settings-popover .sub-item', { hasText: '技能' }).click()
    await expect(page).toHaveURL(/\/skills/)

    // 全局表种子 2 条，含名称与路径；只读页面不应有创建/导入按钮
    const table = page.locator('.skill-table').first()
    await expect(table).toBeVisible()
    await expect(table.locator('.el-table__row')).toHaveCount(2)
    const pyRow = table.locator('.el-table__row', { hasText: 'python-代码审查' })
    await expect(pyRow).toContainText('skills/python-代码审查/SKILL.md')
    const sqlRow = table.locator('.el-table__row', { hasText: 'sql-查询优化' })
    await expect(sqlRow).toContainText('skills/sql-查询优化/SKILL.md')
    await expect(page.getByRole('button', { name: '创建技能' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '导入 git 技能' })).toHaveCount(0)
    await expect(page.locator('.skill-table .el-switch')).toHaveCount(0)
  })

  test('工作区 Skills：选中 ws_001 显示 project-lint，清空回全局、ws_002 空态', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/skills')
    await expect(page.locator('.skill-table').first()).toBeVisible()

    // 工作区下拉选 ws_001 → 表格出现 .agent/skills/project-lint（frontmatter description 提取）
    const wsSelect = page.locator('.section-header .el-select')
    await wsSelect.click()
    await page.getByRole('option', { name: '产品文档' }).click()
    const wsTable = page.locator('.skill-table').nth(1)
    const lintRow = wsTable.locator('.el-table__row', { hasText: 'project-lint' })
    await expect(lintRow).toBeVisible()
    await expect(lintRow).toContainText('.agent/skills/project-lint/SKILL.md')
    await expect(lintRow).toContainText('项目代码风格检查')

    // 清空选择 → 工作区表清空回到空态占位
    await wsSelect.hover()
    await wsSelect.locator('.el-select__clear').click()
    await expect(wsTable.locator('.el-table__row')).toHaveCount(0)

    // 选无 skills 的 ws_002 → 空态提示
    await wsSelect.click()
    await page.getByRole('option', { name: '数据管线' }).click()
    await expect(page.getByText('该工作区暂无 skills')).toBeVisible()
  })
})

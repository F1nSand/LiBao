import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('Skills 管理页（M7-A 契约，交接板 2026-08-20）', () => {
  test('设置气泡 → /skills：种子列表 + 来源标签 + 启用开关（含确认）', async ({ page }) => {
    await login(page)

    // 设置气泡 → 技能子项 → 跳转 /skills 且设置按钮高亮
    await page.locator('.settings-toggle').click()
    await page.locator('.settings-popover .sub-item', { hasText: '技能' }).click()
    await expect(page).toHaveURL(/\/skills/)
    await expect(page.locator('.settings-toggle')).toHaveClass(/active/)

    // 种子 2 条：python-代码审查（手动/启用）、sql-查询优化（git/停用）
    const table = page.locator('.skill-table')
    await expect(table).toBeVisible()
    await expect(table.locator('.el-table__row')).toHaveCount(2)
    const manualRow = table.locator('.el-table__row', { hasText: 'python-代码审查' })
    await expect(manualRow).toContainText('手动')
    const gitRow = table.locator('.el-table__row', { hasText: 'sql-查询优化' })
    await expect(gitRow).toContainText('git 导入')

    // 启用停用的技能 → 确认弹窗 → 开关置为启用态
    const sw = gitRow.locator('.el-switch')
    await expect(sw).not.toHaveClass(/is-checked/)
    await sw.click()
    await page.locator('.el-message-box').getByRole('button', { name: '启用' }).click()
    await expect(sw).toHaveClass(/is-checked/)
  })

  test('创建 / git 导入 / 删除 技能', async ({ page }) => {
    await login(page)
    await page.goto('/skills')
    await expect(page.locator('.skill-table')).toBeVisible()

    // 创建：填名称/路由描述/正文 → 列表出现新行（来源=手动）
    await page.getByRole('button', { name: '创建技能' }).click()
    await page.getByPlaceholder('如 python-代码审查').fill('my-doc-skill')
    await page.getByPlaceholder('何时用 / 何时别用（进 system_prompt 前缀，主 Agent 据此路由）').fill('文档总结技能')
    await page.getByPlaceholder('SKILL.md 正文：步骤 / 示例 / 注意事项').fill('# 文档总结\n- 先读全文\n- 输出要点')
    await page.locator('.el-dialog').getByRole('button', { name: '创建', exact: true }).click()
    const createdRow = page.locator('.skill-table .el-table__row', { hasText: 'my-doc-skill' })
    await expect(createdRow).toBeVisible()
    await expect(createdRow).toContainText('手动')

    // git 导入：填仓库地址 → 列表出现新行（来源=git 导入，正文含 mock 标记）
    await page.getByRole('button', { name: '导入 git 技能' }).click()
    await page.getByPlaceholder('https://github.com/org/skill-repo.git').fill('https://github.com/example/awesome-skill.git')
    await page.locator('.el-dialog').getByRole('button', { name: '导入', exact: true }).click()
    const importedRow = page.locator('.skill-table .el-table__row', { hasText: 'awesome-skill' })
    await expect(importedRow).toBeVisible()
    await expect(importedRow).toContainText('git 导入')

    // 删除创建的技能 → 行消失（确认弹窗按钮默认「确定」）
    await createdRow.getByRole('button', { name: '删除' }).click()
    await page.locator('.el-message-box').getByRole('button', { name: '确定' }).click()
    await expect(page.locator('.skill-table .el-table__row', { hasText: 'my-doc-skill' })).toHaveCount(0)
  })
})

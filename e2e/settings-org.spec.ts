import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('数据隔离 org（多租户展示/筛选）', () => {
  test('TopBar 显示组织 + 用户表 org 列 + 组织筛选', async ({ page }) => {
    await login(page)
    // TopBar：当前用户 admin 属 org_1
    await expect(page.locator('.topbar .user-role')).toContainText('org_1')

    await page.goto('/settings')
    const userTable = page.locator('.settings-tabs .el-table').first()
    await expect(userTable.locator('.el-table__row')).toHaveCount(5, { timeout: 10_000 })

    // 用户表 org 列
    await expect(userTable.locator('.el-table__row').first()).toContainText('org_1')

    // 组织筛选 org_2 → 2 条（dev2 / viewer2）
    await page.locator('.settings-tabs .users-toolbar .el-select__wrapper').click()
    await page.locator('.el-select-dropdown__item:has-text("org_2")').click()
    await expect(userTable.locator('.el-table__row')).toHaveCount(2)
    await expect(userTable.locator('.el-table__row').first()).toContainText('org_2')
  })
})

import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('工作区（M7-B，交接板 2026-08-20）', () => {
  test('气泡网格：种子列表 + 新建 + 编辑卡片', async ({ page }) => {
    await login(page)
    await page.goto('/workspace')

    // 种子 2 条气泡卡片
    const grid = page.locator('.ws-grid')
    await expect(grid).toBeVisible()
    await expect(grid.locator('.ws-card')).toHaveCount(2)
    await expect(grid.locator('.ws-card', { hasText: '产品文档' })).toBeVisible()
    await expect(grid.locator('.ws-card', { hasText: '数据管线' })).toBeVisible()

    // 新建工作区
    await page.getByRole('button', { name: '新建工作区' }).click()
    await page.locator('.el-dialog').getByPlaceholder('如 产品文档').fill('测试工作区')
    await page.locator('.el-dialog').getByRole('button', { name: '创建', exact: true }).click()
    const newCard = grid.locator('.ws-card', { hasText: '测试工作区' })
    await expect(newCard).toBeVisible()

    // 编辑卡片 name（编辑态 name 变成 input 值，卡片文本消失 → 按输入框重定位）
    await newCard.getByRole('button', { name: '编辑' }).click()
    await page.locator('.ws-card .el-input input').fill('测试工作区改')
    await page.locator('.ws-card').getByRole('button', { name: '保存' }).click()
    await expect(grid.locator('.ws-card', { hasText: '测试工作区改' })).toBeVisible()
  })

  test('进入详情：文件树展开/读文件 + 引用文件发送 + 工作区会话', async ({ page }) => {
    await login(page)
    await page.goto('/workspace')

    // 进入产品文档工作区
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    // 文件树：根层 README.md / docs / src；展开 docs 后点文件预览（行级定位避免祖行误配）
    const tree = page.locator('.rm-tree-wrap')
    await expect(tree.locator('.el-tree-node__content', { hasText: 'README.md' })).toBeVisible()
    await tree.locator('.el-tree-node__content', { hasText: 'docs' }).locator('.el-tree-node__expand-icon').click()
    const guideRow = tree.locator('.el-tree-node__content', { hasText: '入门指南.md' })
    await expect(guideRow).toBeVisible()
    await guideRow.click()
    await expect(page.locator('.el-dialog').getByText('预览 / 编辑：docs/入门指南.md')).toBeVisible()
    await page.locator('.el-dialog .el-dialog__footer').getByRole('button', { name: '关闭', exact: true }).click()

    // 引用文件选择器：勾选 README.md → 引用 → composer 出现 chip
    await page.getByRole('button', { name: '引用' }).click()
    const picker = page.locator('.ws-ref-tree')
    await picker.locator('.el-tree-node__content', { hasText: 'README.md' }).locator('.el-checkbox').click()
    await page.locator('.el-dialog').getByRole('button', { name: '引用', exact: true }).click()
    await expect(page.locator('.composer-ref-chip', { hasText: 'README.md' })).toBeVisible()

    // 发送消息 → 用户气泡出现 file-ref chip
    await page.locator('.composer textarea').fill('请总结 README 内容')
    await page.locator('.composer textarea').press('Enter')
    await expect(page.locator('.msg.user .file-ref-chip', { hasText: 'README.md' })).toBeVisible()
    await expect(page.locator('.msg.user .user-text', { hasText: '请总结 README 内容' })).toBeVisible()

    // 工作区会话列表出现新会话
    await expect(page.locator('.ws-conv-item')).not.toHaveCount(0)
  })
})

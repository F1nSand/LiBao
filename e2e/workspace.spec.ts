import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('工作区（M7-B，交接板 2026-08-20）', () => {
  test('气泡网格：种子列表 + 新建 + 编辑卡片', async ({ page }) => {
    await gotoChat(page)
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
    await gotoChat(page)
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

  test('详情页：侧边栏折叠/展开（左列整体收起成窄条）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    // 默认展开：左列 260px，文件树 + 会话可见
    await expect(page.locator('.ws-left')).toHaveCSS('width', '260px')
    await expect(page.locator('.rm-tree-wrap')).toBeVisible()
    await expect(page.locator('.ws-conv-items')).toBeVisible()

    // 点头部汉堡（文件树 / 会话任一个）→ 左列整体收起成 28px 窄条，树与会话隐藏
    await page.locator('.rm-toggle').click()
    await expect(page.locator('.ws-left')).toHaveCSS('width', '28px')
    await expect(page.locator('.rm-tree-wrap')).toBeHidden()
    await expect(page.locator('.ws-conv-items')).toBeHidden()

    // 点窄条展开恢复
    await page.locator('.ws-left-strip').click()
    await expect(page.locator('.ws-left')).toHaveCSS('width', '260px')
    await expect(page.locator('.rm-tree-wrap')).toBeVisible()
    await expect(page.locator('.ws-conv-items')).toBeVisible()
  })

  test('详情页：侧边栏窗口变窄自动收起、变宽自动展开（手动折叠不自动展开）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    // 宽视口（>960）默认展开
    await page.setViewportSize({ width: 1280, height: 720 })
    await expect(page.locator('.ws-left')).toHaveCSS('width', '260px')

    // 变窄（≤960）→ 左列自动收起成 28px 窄条
    await page.setViewportSize({ width: 800, height: 720 })
    await expect(page.locator('.ws-left')).toHaveCSS('width', '28px')

    // 变宽 → 自动展开
    await page.setViewportSize({ width: 1280, height: 720 })
    await expect(page.locator('.ws-left')).toHaveCSS('width', '260px')

    // 手动折叠（汉堡）后 → 再变窄/变宽都不自动展开
    await page.locator('.rm-toggle').click()
    await page.setViewportSize({ width: 800, height: 720 })
    await expect(page.locator('.ws-left')).toHaveCSS('width', '28px')
    await page.setViewportSize({ width: 1280, height: 720 })
    await expect(page.locator('.ws-left')).toHaveCSS('width', '28px')
  })

  test('详情页：文件树轮询捕获外部更新（动态显示，且未变化目录不重建不闪烁）', async ({ page, request }) => {
    // 放大刷新窗口：files 请求延迟 150ms——旧实现整树重建时 docs 收起 + loading 可被采样命中
    await page.route('**/workspaces/*/files*', async (route) => {
      await new Promise((r) => setTimeout(r, 150))
      await route.continue()
    })

    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    // 展开 docs（其子树是「不被重建」的观察对象）
    const tree = page.locator('.rm-tree-wrap')
    await tree.locator('.el-tree-node__content', { hasText: 'docs' }).locator('.el-tree-node__expand-icon').click()
    await expect(tree.locator('.el-tree-node__content', { hasText: '入门指南.md' })).toBeVisible()

    // 采样器：每 30ms 检查 docs 子树是否被隐藏（v-show display:none）/ loading 图标出现
    await page.evaluate(() => {
      ;(window as unknown as Record<string, unknown>).__treeFlash = { hidden: 0, loading: 0 }
      const started = Date.now()
      const timer = setInterval(() => {
        if (Date.now() - started > 8000) {
          clearInterval(timer)
          return
        }
        const nodes = [...document.querySelectorAll('.rm-tree-wrap .el-tree-node')]
        const docs = nodes.find((n) => n.querySelector('.el-tree-node__content .rm-node-name')?.textContent === 'docs')
        if (!docs) return
        const wrapper = docs.querySelector(':scope > .el-tree-node__children') as HTMLElement | null
        const flash = (window as unknown as Record<string, unknown>).__treeFlash as { hidden: number; loading: number }
        if (wrapper && wrapper.style.display === 'none') flash.hidden++
        if (docs.querySelector('.el-tree-node__loading-icon')) flash.loading++
      }, 30)
    })

    // 等首个轮询完成签名缓存初始化（更早落地的外部变化会被并入初始签名，之后不再触发）再写入
    await page.waitForTimeout(1200)

    // 外部写入新文件 → 轮询检测根层签名变化 → 外科修补（mock 定时注入已被前置用例触发过，用 API 写保证时序可控）
    const resp = await request.post('/api/v1/workspaces/ws_001/files', {
      data: { path: 'e2e注入.md', content: '# e2e 注入\n' },
    })
    expect(resp.ok()).toBeTruthy()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'e2e注入.md' })).toBeVisible({ timeout: 5000 })

    // 刷新期间 docs 子树从未收起、无 loading（未变化目录未被重建 = 不闪烁）
    await page.waitForTimeout(300)
    const flash = await page.evaluate(
      () => (window as unknown as Record<string, unknown>).__treeFlash as { hidden: number; loading: number },
    )
    expect(flash.hidden).toBe(0)
    expect(flash.loading).toBe(0)

    // 已展开目录保持展开（子项仍在，无需重新点击）
    await expect(tree.locator('.el-tree-node__content', { hasText: '入门指南.md' })).toBeVisible()
  })

  test('详情页：打开本地文件夹按钮（mock 成功路径）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    await page.locator('.rm-head-right button[title^="打开本地文件夹"]').click()
    await expect(page.locator('.el-message__content').filter({ hasText: '已请求在本地打开文件夹' })).toBeVisible()
  })

  test('详情页：.agent/ 项目级能力目录（skills/记忆/知识库，docs/02 §4.2）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    const tree = page.locator('.rm-tree-wrap')
    // 根层出现 .agent/ 目录（项目级能力文件化，文件树直接可见可编辑，无管理 UI）
    const agentRow = tree.locator('.el-tree-node__content').filter({ hasText: '.agent' }).first()
    await expect(agentRow).toBeVisible()
    // 展开 .agent/ → agent.md + skills/memory/knowledge 子目录
    await agentRow.locator('.el-tree-node__expand-icon').click()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'agent.md' })).toBeVisible()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'skills' })).toBeVisible()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'memory' })).toBeVisible()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'knowledge' })).toBeVisible()
  })

  test('气泡网格：删除工作区（强确认输入名称，防误删）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')

    // 新建临时工作区用于删除（不动种子数据）
    await page.getByRole('button', { name: '新建工作区' }).click()
    await page.locator('.el-dialog').getByPlaceholder('如 产品文档').fill('待删除工作区')
    await page.locator('.el-dialog').getByRole('button', { name: '创建', exact: true }).click()
    const card = page.locator('.ws-card', { hasText: '待删除工作区' })
    await expect(card).toBeVisible()

    // 强确认：输入错误名称 → 取消删除（工作区保留）
    await card.getByRole('button', { name: '删除' }).click()
    await page.locator('.el-message-box input').fill('错误名称')
    await page.locator('.el-message-box').getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.el-message').filter({ hasText: '名称不匹配' })).toBeVisible()
    await expect(card).toBeVisible()

    // 输入正确名称 → 删除 → 卡片消失
    await card.getByRole('button', { name: '删除' }).click()
    await page.locator('.el-message-box input').fill('待删除工作区')
    await page.locator('.el-message-box').getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.ws-card', { hasText: '待删除工作区' })).toHaveCount(0)
  })

  test('详情页：文件树三连菜单（新建文件/文件夹 + 重命名 + 删除）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)
    const tree = page.locator('.rm-tree-wrap')

    // 顶部「新建」→ 新建文件（无后缀默认 .txt）
    await page.locator('.rm-head-right').getByRole('button', { name: '新建' }).click()
    await page.getByRole('menuitem', { name: '新建文件', exact: true }).click()
    await page.locator('.el-dialog').getByPlaceholder(/无后缀默认/).fill('临时笔记')
    await page.locator('.el-dialog').getByRole('button', { name: '创建', exact: true }).click()
    await expect(tree.locator('.el-tree-node__content', { hasText: '临时笔记.txt' })).toBeVisible()

    // 行尾三连 → 重命名文件
    const noteRow = tree.locator('.el-tree-node__content', { hasText: '临时笔记.txt' }).first()
    await noteRow.hover()
    await noteRow.locator('.rm-more').click()
    await page.getByRole('menuitem', { name: '重命名', exact: true }).click()
    await page.locator('.el-dialog').getByPlaceholder('新名称').fill('临时笔记改.md')
    await page.locator('.el-dialog').getByRole('button', { name: '保存', exact: true }).click()
    await expect(tree.locator('.el-tree-node__content', { hasText: '临时笔记改.md' })).toBeVisible()

    // 文件夹三连 → 新建文件夹（子目录），展开 docs 可见
    const docsRow = tree.locator('.el-tree-node__content', { hasText: 'docs' }).first()
    await docsRow.hover()
    await docsRow.locator('.rm-more').click()
    await page.getByRole('menuitem', { name: '新建文件夹', exact: true }).click()
    await page.locator('.el-dialog').getByPlaceholder('如 assets').fill('assets')
    await page.locator('.el-dialog').getByRole('button', { name: '创建', exact: true }).click()
    await docsRow.locator('.el-tree-node__expand-icon').click()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'assets' })).toBeVisible()

    // 删除 assets 目录（递归 + 确认）
    const assetsRow = tree.locator('.el-tree-node__content', { hasText: 'assets' }).first()
    await assetsRow.hover()
    await assetsRow.locator('.rm-more').click()
    await page.getByRole('menuitem', { name: '删除', exact: true }).click()
    await page.locator('.el-message-box').getByRole('button', { name: '确定' }).click()
    await expect(tree.locator('.el-tree-node__content', { hasText: 'assets' })).toHaveCount(0)
  })
})

import { test, expect, type Page } from '@playwright/test'
import { gotoChat, sendMessage } from './helpers'

async function loadCheckpointedMessage(page: Page) {
  await gotoChat(page)
  await sendMessage(page, '检查 checkpoint 操作栏')
  await expect(page.locator('.markdown-body').first()).toContainText('检索', { timeout: 15_000 })

  // 当前 mock 的 checkpoint 先通过持久化消息回读；Task 6 会再覆盖首帧即时锚点。
  await page.reload()
  await page.locator('.chat-view').waitFor({ state: 'visible', timeout: 15_000 })
  const conversation = page.locator('.conv-item').first()
  const sidebar = page.locator('.sidebar')
  if ((page.viewportSize()?.width ?? 1280) <= 768 && !(await sidebar.evaluate((element) => element.classList.contains('drawer-open')))) {
    await page.getByRole('button', { name: '打开导航菜单' }).click()
  }
  await conversation.locator('.conv-item-select').click()
  const userMessage = page.locator('.msg.user').last()
  await expect(userMessage.locator('.message-actions')).toHaveCount(1, { timeout: 10_000 })
  return userMessage
}

test.describe('checkpoint 消息操作栏', () => {
  test('鼠标移出后隐藏，打开并关闭回滚预览后不残留可见状态', async ({ page }) => {
    const userMessage = await loadCheckpointedMessage(page)
    const actions = userMessage.locator('.message-actions')
    const rollback = actions.getByRole('button', { name: '回滚到此状态' })

    await expect(actions.locator('.message-action').first()).toHaveCSS('opacity', '0')
    await userMessage.hover()
    await expect(actions.locator('.message-action').first()).toHaveCSS('opacity', '1')

    await rollback.click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '回滚到此状态' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(dialog).toBeHidden()

    await page.mouse.move(5, 5)
    await expect(actions.locator('.message-action').first()).toHaveCSS('opacity', '0')
  })

  test('Tab 聚焦隐藏按钮时显示操作栏并保留可见 focus ring，移焦后隐藏', async ({ page }) => {
    const userMessage = await loadCheckpointedMessage(page)
    const actions = userMessage.locator('.message-actions')
    const rollback = actions.getByRole('button', { name: '回滚到此状态' })

    await page.mouse.move(5, 5)
    await page.locator('body').click({ position: { x: 5, y: 5 } })
    let focused = false
    for (let index = 0; index < 80; index += 1) {
      await page.keyboard.press('Tab')
      if (await rollback.evaluate((element) => document.activeElement === element)) {
        focused = true
        break
      }
    }

    expect(focused).toBe(true)
    await expect(actions.locator('.message-action').first()).toHaveCSS('opacity', '1')
    await expect(rollback).toHaveCSS('outline-style', 'solid')
    expect(await rollback.evaluate((element) => element.matches(':focus-visible'))).toBe(true)

    await page.locator('.composer textarea').focus()
    await expect(actions.locator('.message-action').first()).toHaveCSS('opacity', '0')
  })
})

test.describe('checkpoint 消息操作栏（触屏）', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

  test('触屏常显且按钮命中区至少 44×44px', async ({ page }) => {
    const userMessage = await loadCheckpointedMessage(page)
    const action = userMessage.locator('.message-action').first()

    await expect(action).toHaveCSS('opacity', '1')
    const box = await action.boundingBox()
    expect(box).not.toBeNull()
    expect(box?.width).toBeGreaterThanOrEqual(44)
    expect(box?.height).toBeGreaterThanOrEqual(44)
  })
})

test.describe('checkpoint live anchor', () => {
  test('普通会话在首帧收到 anchor 后立即显示回滚/复制操作，无需刷新', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '首帧锚点普通会话')

    const userMessage = page.locator('.msg.user').last()
    await expect(userMessage.locator('.message-actions')).toHaveCount(1, { timeout: 10_000 })
    await expect(userMessage.getByRole('button', { name: '回滚到此状态' })).toBeVisible()
    await expect(userMessage.getByRole('button', { name: '复制消息' })).toBeVisible()

    const buttons = userMessage.locator('.message-action')
    await expect(buttons).toHaveCount(2)
    await expect(buttons.nth(0)).toHaveAttribute('aria-label', '回滚到此状态')
    await expect(buttons.nth(1)).toHaveAttribute('aria-label', '复制消息')

    await page.evaluate(() => {
      ;(window as unknown as { copied?: string }).copied = ''
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: async (text: string) => { (window as unknown as { copied?: string }).copied = text } },
      })
    })
    await userMessage.hover()
    await userMessage.getByRole('button', { name: '复制消息' }).click()
    await expect.poll(() => page.evaluate(() => (window as unknown as { copied?: string }).copied)).toBe('首帧锚点普通会话')
  })

  test('WorkspaceShell 在首帧收到 anchor 后立即显示消息操作', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    await page.locator('.composer textarea').fill('首帧锚点工作区会话')
    await page.locator('.composer textarea').press('Enter')

    const userMessage = page.locator('.msg.user').last()
    await expect(userMessage.locator('.message-actions')).toHaveCount(1, { timeout: 10_000 })
    await expect(userMessage.getByRole('button', { name: '回滚到此状态' })).toBeVisible()
  })

  test('[disconnect] replay 后不重复追加用户消息', async ({ page }) => {
    await gotoChat(page)
    await sendMessage(page, '[disconnect]')

    await expect(page.locator('.msg.user .message-actions')).toHaveCount(1, { timeout: 10_000 })
    await expect(page.locator('.run-status')).toContainText('已完成', { timeout: 15_000 })
    await expect(page.locator('.msg.user')).toHaveCount(1)
  })
})

test.describe('checkpoint restore v2', () => {
  test('普通会话默认 Both 可直接确认，回滚后可撤销并清理未编辑草稿', async ({ page }) => {
    await gotoChat(page)
    await page.locator('.conv-item[data-conversation-id="c_001"]').click()
    await expect(page.locator('.msg.user .user-text')).toContainText('计算 6*7')

    const userMessage = page.locator('.msg.user').filter({ hasText: '计算 6*7' })
    await userMessage.hover()
    await userMessage.getByRole('button', { name: '回滚到此状态' }).click()

    const dialog = page.locator('.el-dialog').filter({ hasText: '回滚到此状态' })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('input[type="radio"][value="both"]')).toBeChecked()
    await expect(dialog.getByRole('button', { name: '确认回滚', exact: true })).toBeEnabled()
    // 默认 Both 就是实际预览模式：不切换单选项也可以直接确认。
    await dialog.getByRole('button', { name: '确认回滚', exact: true }).click()

    await expect(dialog).toBeHidden()
    await expect(page.locator('.msg.user .user-text')).toHaveCount(0)
    await expect(page.locator('.rollback-undo-banner')).toBeVisible()
    await expect(page.locator('.composer textarea')).toHaveValue('计算 6*7')

    await page.getByRole('button', { name: '撤销本次回滚' }).click()
    const undoDialog = page.locator('.el-dialog').filter({ hasText: '回滚到此状态' })
    await expect(undoDialog).toBeVisible()
    await expect(undoDialog.locator('.mode-grid')).toHaveCount(0)
    await expect(undoDialog.getByRole('button', { name: '确认回滚', exact: true })).toBeEnabled()
    await undoDialog.getByRole('button', { name: '确认回滚', exact: true }).click()

    await expect(undoDialog).toBeHidden()
    await expect(page.locator('.msg-row')).toHaveCount(2)
    await expect(page.locator('.composer textarea')).toHaveValue('')
  })

  test('Workspace 回滚按权威草稿恢复正文与 file_refs', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)

    // 让目标消息携带 file_refs，验证恢复的是后端返回的权威 composer draft。
    await page.getByRole('button', { name: '引用' }).click()
    const picker = page.locator('.ws-ref-tree')
    await picker.locator('.el-tree-node__content', { hasText: 'README.md' }).locator('.el-checkbox').click()
    await page.locator('.el-dialog').getByRole('button', { name: '引用', exact: true }).click()
    await expect(page.locator('.composer-ref-chip', { hasText: 'README.md' })).toBeVisible()

    const targetText = '回滚后恢复 README 引用'
    await page.locator('.composer textarea').fill(targetText)
    await page.locator('.composer textarea').press('Enter')
    const targetUser = page.locator('.msg.user .user-text', { hasText: targetText })
    await expect(targetUser).toBeVisible()
    await expect(page.locator('.msg.assistant').last()).toBeVisible({ timeout: 15_000 })

    const targetMessage = page.locator('.msg.user').filter({ hasText: targetText })
    await targetMessage.hover()
    await targetMessage.getByRole('button', { name: '回滚到此状态' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '回滚到此状态' })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('input[type="radio"][value="both"]')).toBeChecked()
    await dialog.getByRole('button', { name: '确认回滚', exact: true }).click()

    await expect(dialog).toBeHidden()
    await expect(page.locator('.msg.user .user-text', { hasText: targetText })).toHaveCount(0)
    await expect(page.locator('.composer textarea')).toHaveValue(targetText)
    await expect(page.locator('.composer-ref-chip', { hasText: 'README.md' })).toBeVisible()
  })
})

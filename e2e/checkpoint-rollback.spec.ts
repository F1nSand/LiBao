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

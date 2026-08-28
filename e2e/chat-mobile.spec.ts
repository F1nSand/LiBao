import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

async function assertComposerFits(page: Parameters<typeof gotoChat>[0], textareaSelector = '.composer textarea') {
  const composer = page.locator('.composer').first()
  const textarea = page.locator(textareaSelector).first()
  const actions = page.locator('.composer-actions').first()

  await expect(composer).toBeVisible()
  await expect(textarea).toBeVisible()
  await expect(actions).toBeVisible()

  const layout = await page.evaluate(() => {
    const composer = document.querySelector('.composer') as HTMLElement
    const textarea = document.querySelector('.composer-textarea') as HTMLElement
    const actions = document.querySelector('.composer-actions') as HTMLElement
    const textareaBox = textarea.getBoundingClientRect()
    const actionsBox = actions.getBoundingClientRect()
    return {
      composerWidth: composer.clientWidth,
      composerScrollWidth: composer.scrollWidth,
      textareaBottom: textareaBox.bottom,
      actionsTop: actionsBox.top,
    }
  })

  expect(layout.composerScrollWidth).toBeLessThanOrEqual(layout.composerWidth)
  expect(layout.actionsTop).toBeGreaterThanOrEqual(layout.textareaBottom)
}

test.describe('移动端 composer', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('聊天 composer 两行布局且没有内部横向溢出', async ({ page }) => {
    await gotoChat(page)
    await assertComposerFits(page)

    const textarea = page.locator('.composer textarea')
    await textarea.fill(Array.from({ length: 12 }, (_, index) => `第 ${index + 1} 行`).join('\n'))
    const height = await textarea.evaluate((el) => el.clientHeight)
    expect(height).toBeLessThanOrEqual(8 * 24 + 8)
  })

  test('工作区 composer 也保持两行布局', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/workspace')
    await page.locator('.ws-card', { hasText: '产品文档' }).getByRole('button', { name: '进入工作区' }).click()
    await expect(page).toHaveURL(/\/workspace\/ws_001/)
    await assertComposerFits(page)
  })

  test('切换会话时先隐藏旧消息并显示加载骨架', async ({ page }) => {
    await gotoChat(page)
    await page.getByRole('button', { name: '打开导航菜单' }).click()
    await page.locator('.conv-item[data-conversation-id="c_001"]').click()
    await expect(page.locator('.msg-row')).toHaveCount(2)

    let release!: () => void
    const blocked = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.route('**/api/v1/conversations/c_002/messages*', async (route) => {
      await blocked
      await route.continue()
    })

    await page.getByRole('button', { name: '打开导航菜单' }).click()
    await page.locator('.conv-item[data-conversation-id="c_002"]').click()
    await expect(page.locator('.stream-skeleton')).toBeVisible()
    await expect(page.locator('.msg-row')).toHaveCount(0)

    release()
    await expect(page.locator('.stream-skeleton')).toBeHidden()
    await expect(page.locator('.msg-row')).toHaveCount(2)
  })

  test('跨页面切换会话时不等待消息请求才跳转', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/kb')
    await page.getByRole('button', { name: '打开导航菜单' }).click()

    let release!: () => void
    const blocked = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.route('**/api/v1/conversations/c_002/messages*', async (route) => {
      await blocked
      await route.continue()
    })

    await page.locator('.conv-item[data-conversation-id="c_002"]').click()
    await expect(page).toHaveURL(/\/chat$/)
    await expect(page.locator('.conv-item[data-conversation-id="c_002"]')).toHaveClass(/active/)
    await expect(page.locator('.stream-skeleton')).toBeVisible()

    release()
    await expect(page.locator('.stream-skeleton')).toBeHidden()
  })

  test('快速切换时迟到的旧会话响应不覆盖最后一次选择', async ({ page }) => {
    await gotoChat(page)
    await page.getByRole('button', { name: '打开导航菜单' }).click()

    let releaseA!: () => void
    let releaseB!: () => void
    const blockedA = new Promise<void>((resolve) => {
      releaseA = resolve
    })
    const blockedB = new Promise<void>((resolve) => {
      releaseB = resolve
    })
    await page.route('**/api/v1/conversations/c_001/messages*', async (route) => {
      await blockedA
      await route.continue()
    })
    await page.route('**/api/v1/conversations/c_002/messages*', async (route) => {
      await blockedB
      await route.continue()
    })

    await page.locator('.conv-item[data-conversation-id="c_001"]').click()
    await page.getByRole('button', { name: '打开导航菜单' }).click()
    await page.locator('.conv-item[data-conversation-id="c_002"]').click()

    releaseB()
    await expect(page.locator('.msg-row')).toHaveCount(2)
    await expect(page.locator('.msg.user .user-text')).toContainText('什么是 SSE')

    releaseA()
    await expect(page.locator('.msg.user .user-text')).toContainText('什么是 SSE')
    await expect(page.locator('.msg.user .user-text')).not.toContainText('计算 6*7')
  })

  test('流失败后可恢复草稿，重试不会重复追加用户消息', async ({ page }) => {
    let attempts = 0
    await page.route('**/api/v1/chat/stream', async (route) => {
      attempts += 1
      const body =
        attempts === 1
          ? 'event: error\ndata: {"id":"e1","seq":1,"type":"error","ts":1700000000000,"payload":{"code":60001,"message":"mock 流失败","retryable":true}}\n\n'
          : [
              'event: message_start\ndata: {"id":"e2","seq":1,"type":"message_start","ts":1700000000000,"payload":{"message_id":"m_retry","task_id":"t_retry"}}\n\n',
              'event: token\ndata: {"id":"e3","seq":2,"type":"token","ts":1700000000000,"payload":{"text":"重试成功"}}\n\n',
              'event: done\ndata: {"id":"e4","seq":3,"type":"done","ts":1700000000000,"payload":{"message":{"id":"m_retry","role":"assistant","content":"重试成功","tool_calls":[],"created_at":"2026-08-28T00:00:00Z"}}}\n\n',
            ].join('')
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body,
      })
    })

    await gotoChat(page)
    await page.locator('.composer textarea').fill('测试失败恢复')
    await page.locator('.composer textarea').press('Enter')
    await expect(page.locator('.stream-error')).toContainText('mock 流失败')
    await expect(page.locator('.msg.user .user-text')).toHaveCount(1)

    await page.locator('.stream-error .recovery-btn.primary').click()
    await expect(page.locator('.markdown-body').first()).toContainText('重试成功')
    await expect(page.locator('.msg.user .user-text')).toHaveCount(1)
    expect(attempts).toBe(2)
  })
})

import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('附件上下文与展示语义', () => {
  test('上传附件只传 ID，模型回复消费文本，气泡不显示分析状态', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/chat')

    const nonce = 'E2E_ATTACHMENT_NONCE_20260828'
    const requestBodies: Array<Record<string, unknown>> = []
    page.on('request', (request) => {
      if (request.url().endsWith('/api/v1/chat/stream')) {
        requestBodies.push(request.postDataJSON() as Record<string, unknown>)
      }
    })

    await page.locator('#file-input').setInputFiles({
      name: 'nonce.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(nonce, 'utf-8'),
    })
    await expect(page.locator('.composer-attachment-chip', { hasText: 'nonce.txt' })).toBeVisible()

    await page.locator('.composer textarea').fill('请读取附件中的 nonce')
    await page.locator('.composer textarea').press('Enter')

    await expect.poll(() => requestBodies.at(-1)).toMatchObject({
      message: { content: '请读取附件中的 nonce', attachments: expect.arrayContaining([expect.any(String)]) },
    })
    await expect(page.locator('.msg.assistant').filter({ hasText: nonce })).toBeVisible()
    await expect(page.locator('.attach-badge')).toHaveCount(0)
    await expect(page.locator('.msg.user .attach-name', { hasText: 'nonce.txt' })).toBeVisible()
  })

  test('mock 与真实契约一致拒绝无工作区或越界 file_ref', async ({ request }) => {
    const response = await request.post('/api/v1/chat/stream', {
      data: {
        conversation_id: null,
        message: { content: '', role: 'user', attachments: [], file_refs: [{ path: '../outside.txt' }] },
        stream: true,
      },
    })
    expect(response.ok()).toBe(true)
    expect((await response.json()).code).toBe(40015)
  })

  test('纯附件发送不产生空文字气泡，文件卡整卡可打开', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/chat')

    await page.locator('#file-input').setInputFiles({
      name: 'only-file.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-mock', 'utf-8'),
    })
    await page.locator('.composer .composer-actions button', { hasText: '发送' }).click()

    const userRow = page.locator('.msg.user').last()
    await expect(userRow.locator('.attach-file')).toBeVisible()
    await expect(userRow.locator('.user-text')).toHaveCount(0)
    await expect(userRow.locator('.attach-file')).toHaveAttribute('href', /\/api\/v1\/attachments\/.+/)
    await expect(userRow.locator('.attach-file')).toHaveAttribute('target', '_blank')
  })
})

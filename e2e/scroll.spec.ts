import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('对话滚动位置（记忆/恢复 + 新会话贴底，《02》前端设计 §6.2）', () => {
  test('c_scroll：新开默认到底；上滚后切走再回恢复原位', async ({ page }) => {
    await gotoChat(page)

    // 打开长会话（无滚动记录 → 默认到底，最近对话）
    await page.locator('.conv-item[data-conversation-id="c_scroll"]').click()
    const list = page.locator('.msg-list')
    await list.locator('.msg-row').first().waitFor({ timeout: 10_000 })
    await page.waitForTimeout(400) // 等双 rAF + timeout 落地
    let pos = await list.evaluate((el) => ({ top: el.scrollTop, h: el.scrollHeight, c: el.clientHeight }))
    expect(pos.h - pos.c).toBeGreaterThan(100) // 内容确实高到可滚动
    expect(pos.top).toBeGreaterThanOrEqual(pos.h - pos.c - 40) // 新会话 → 贴底

    // 上滚到 ~200（触发 scroll 事件记账）
    await list.evaluate((el) => {
      el.scrollTop = 200
    })
    await page.waitForTimeout(120)
    pos = await list.evaluate((el) => ({ top: el.scrollTop, h: el.scrollHeight, c: el.clientHeight }))
    expect(pos.top).toBeGreaterThan(0)

    // 切走 c_002（无记录 → 默认到底）
    await page.locator('.conv-item[data-conversation-id="c_002"]').click()
    await list.locator('.msg-row').first().waitFor({ timeout: 10_000 })
    await page.waitForTimeout(400)
    pos = await list.evaluate((el) => ({ top: el.scrollTop, h: el.scrollHeight, c: el.clientHeight }))
    expect(pos.top).toBeGreaterThanOrEqual(pos.h - pos.c - 40)

    // 切回 c_scroll → 恢复原位（不被强制拉到底）
    await page.locator('.conv-item[data-conversation-id="c_scroll"]').click()
    await page.waitForTimeout(400)
    pos = await list.evaluate((el) => ({ top: el.scrollTop, h: el.scrollHeight, c: el.clientHeight }))
    expect(pos.top).toBeLessThan(pos.h - pos.c - 100) // 未强制到底
    expect(pos.top).toBeGreaterThan(50) // 恢复到了上滚位置附近
  })

  test('离开底部显示固定倒三角按钮，滚动后位置不随消息滚动并可回底', async ({ page }) => {
    await gotoChat(page)
    await page.locator('.conv-item[data-conversation-id="c_scroll"]').click()
    const list = page.locator('.msg-list')
    await list.locator('.msg-row').first().waitFor({ timeout: 10_000 })
    await page.waitForTimeout(400)

    await list.evaluate((el) => {
      el.scrollTop = 200
    })
    const jumpButton = page.locator('.jump-to-latest-btn')
    await expect(jumpButton).toBeVisible()
    await expect(jumpButton).toHaveAttribute('aria-label', '回到底部')
    await expect(jumpButton.locator('.jump-to-latest-icon')).toBeVisible()
    await expect(jumpButton).not.toContainText('有新内容')

    const before = await jumpButton.boundingBox()
    await list.evaluate((el) => {
      el.scrollTop = 400
    })
    const after = await jumpButton.boundingBox()
    expect(before).toBeTruthy()
    expect(after).toBeTruthy()
    if (before && after) expect(Math.abs(after.y - before.y)).toBeLessThan(1)

    await jumpButton.click()
    const pos = await list.evaluate((el) => ({ top: el.scrollTop, h: el.scrollHeight, c: el.clientHeight }))
    expect(pos.top).toBeGreaterThanOrEqual(pos.h - pos.c - 40)
  })
})

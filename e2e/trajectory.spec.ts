import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('对话轨迹页', () => {
  test('深链 c_001：时间轴 + 台账（含 calculator）+ 选中联动详情 + 返回', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')

    // 台账：USER 标签 + calculator 工具行
    await expect(page.locator('.tj-cell-label', { hasText: 'USER' })).toHaveCount(1, { timeout: 10_000 })
    await expect(page.locator('.tj-ledger')).toContainText('calculator')
    // 时间轴 + 三条泳道
    await expect(page.locator('.tj-timeline')).toBeVisible()
    await expect(page.locator('.tj-timeline')).toContainText('Input')
    await expect(page.locator('.tj-timeline')).toContainText('Model')
    await expect(page.locator('.tj-timeline')).toContainText('Tools')

    // 点工具行 → 详情面板打开「入参」
    await page.locator('.tj-cell', { hasText: 'calculator' }).first().click()
    await expect(page.locator('.tj-detail')).toContainText('入参')

    // 搜索：命中 calculator
    await page.locator('.tj-search input').fill('calculator')
    await expect(page.locator('.tj-cell', { hasText: 'calculator' })).toHaveCount(1)

    // 返回对话
    await page.getByRole('button', { name: '返回对话' }).click()
    await expect(page).toHaveURL(/\/chat/)
  })

  test('初始加载只请求一次并显示轨迹骨架屏', async ({ page }) => {
    let requestCount = 0
    await page.route('**/api/v1/conversations/c_001/trajectory**', async (route) => {
      requestCount += 1
      // 独立 e2e server 首屏加载可能快于短延迟；保留足够窗口观察初始骨架屏。
      await new Promise((resolve) => setTimeout(resolve, 1000))
      await route.continue()
    })

    const navigation = page.goto('/trajectory/c_001')
    await expect(page.locator('.tj-loading')).toBeVisible()
    await navigation
    await expect(page.locator('.tj-ledger')).toBeVisible()
    expect(requestCount).toBe(1)
  })

  test('c_002：纯文本会话，无 TOOL 标签行', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_002')

    await expect(page.locator('.tj-ledger')).toContainText('什么是 SSE', { timeout: 10_000 })
    await expect(page.locator('.tj-cell-label', { hasText: 'TOOL' })).toHaveCount(0)
  })

  test('仅附件/引用的用户消息：USER 摘要显示来源而不是“（空）”', async ({ page }) => {
    await page.route('**/api/v1/conversations/c_002/trajectory**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          code: 0,
          message: 'ok',
          data: {
            conversation_id: 'c_002',
            nodes: [
              {
                seq: 1,
                kind: 'user',
                time: Date.now(),
                content: '',
                attachments: [{ attachment_id: 'atc_img', name: '截图.png', mime_type: 'image/png' }],
                file_refs: [{ path: 'docs/readme.md' }],
              },
              { seq: 2, kind: 'assistant', time: Date.now() + 1000, content: '已收到' },
            ],
            has_more: false,
          },
        }),
      })
    })

    await gotoChat(page)
    await page.goto('/trajectory/c_002')
    await expect(page.locator('.tj-cell-text').first()).toContainText('截图.png')
    await expect(page.locator('.tj-cell-text').first()).toContainText('docs/readme.md')
    await expect(page.locator('.tj-cell-text').first()).not.toContainText('（空）')
  })

  test('跨视图定位：?focus=tc_seed 自动选中工具记录并打开详情', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001?focus=tc_seed')

    await expect(page.locator('.tj-cell.selected')).toContainText('calculator', { timeout: 10_000 })
    await expect(page.locator('.tj-detail')).toContainText('入参')
  })

  test('Duration 切换甘特图投影（默认顺序 → 启用耗时）', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    await page.locator('.tj-timeline').waitFor({ timeout: 10_000 })

    await page.getByRole('button', { name: 'Duration' }).click()
    await page.waitForTimeout(120)
    await expect(page.locator('.tj-timeline')).toBeVisible()
    await expect(page.locator('.tj-lane')).toHaveCount(3)
  })

  test('Turns 收起：仅 USER + CONTEXT，省略行可单独展开', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    await page.locator('.tj-ledger').waitFor({ timeout: 10_000 })

    // 默认全展开：ASSISTANT 行可见
    await expect(page.locator('.tj-cell-label', { hasText: 'ASSISTANT' })).toHaveCount(1)
    // 点 Turns → 收起中间，省略行出现、ASSISTANT 隐藏
    await page.getByRole('button', { name: 'Turns' }).click()
    await page.waitForTimeout(120)
    await expect(page.locator('.tj-cell-label', { hasText: 'ASSISTANT' })).toHaveCount(0)
    await expect(page.locator('.tj-fold')).toBeVisible()
    // 点击省略行 → 单独展开该轮次
    await page.locator('.tj-fold').click()
    await expect(page.locator('.tj-cell-label', { hasText: 'ASSISTANT' })).toHaveCount(1)
  })

  test('时间线点击选中 → 台账对应单元格高亮 + 轮次高光条', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    await page.locator('.tj-timeline').waitFor({ timeout: 10_000 })

    await page.locator('.tj-span').first().click()
    await page.waitForTimeout(120)
    await expect(page.locator('.tj-cell.selected')).toHaveCount(1)
    await expect(page.locator('.tj-turn-bar.on')).toHaveCount(1)
  })

  test('轨迹单元格、台账上下移动、详情分栏器支持键盘操作', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    await page.locator('.tj-ledger').waitFor({ timeout: 10_000 })

    const span = page.locator('.tj-span').first()
    await span.focus()
    await span.press('Enter')
    await expect(span).toHaveAttribute('aria-pressed', 'true')

    const rows = page.locator('.tj-ledger button.tj-cell')
    expect(await rows.count()).toBeGreaterThan(1)
    await rows.first().focus()
    await rows.first().press('ArrowDown')
    await expect(rows.nth(1)).toBeFocused()
    await expect(rows.nth(1)).toHaveAttribute('aria-current', 'true')

    const splitter = page.locator('.tj-splitter')
    await expect(splitter).toBeVisible()
    const before = await splitter.getAttribute('aria-valuenow')
    await splitter.focus()
    await splitter.press('ArrowLeft')
    await expect(splitter).not.toHaveAttribute('aria-valuenow', before ?? '')
  })

  test('800/390 宽度下轨迹详情浮层不制造页面横向溢出', async ({ page }) => {
    await gotoChat(page)
    for (const viewport of [
      { width: 800, height: 700 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/trajectory/c_001')
      await page.locator('.tj-ledger').waitFor({ timeout: 10_000 })
      await expect(page.locator('.tj-lane-label').first()).toHaveAttribute('title', 'Input')
      if (viewport.width < 480) await expect(page.locator('.tj-lane-label-short').first()).toBeVisible()
      await page.locator('.tj-cell').first().click()
      await expect(page.locator('.tj-detail')).toBeVisible()
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(scrollWidth).toBeLessThanOrEqual(viewport.width)
    }
  })

  test('拖动框选 → 甘特聚焦区域：框内正常、外部变灰，首个选中', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    const body = page.locator('.tj-lane-body').first()
    await body.waitFor({ timeout: 10_000 })
    const bb = await body.boundingBox()
    expect(bb).toBeTruthy()
    if (!bb) return
    // 从泳道标签列（左侧空白）向右拖一段 → 框住前几个方块，其余留在框外变灰
    await page.mouse.move(bb.x - 24, bb.y + 9)
    await page.mouse.down()
    await page.mouse.move(bb.x + 96, bb.y + 9, { steps: 6 })
    await page.mouse.up()
    await page.waitForTimeout(120)
    // 选中 = 1 个（框内首个）；框外（甘特 + 台账）同步变灰透明
    await expect(page.locator('.tj-cell.selected')).toHaveCount(1)
    await expect(page.locator('.tj-span.selected')).toHaveCount(1)
    const dim = await page.locator('.tj-cell.focus-dim').count()
    expect(dim).toBeGreaterThan(0)
    await expect(page.locator('.tj-span.focus-dim')).toHaveCount(dim)

    // 点击聚焦区域外的方块 → 取消聚焦（外部不再变灰），该方块转为选中
    await page.locator('.tj-span').last().click()
    await page.waitForTimeout(120)
    await expect(page.locator('.tj-cell.focus-dim')).toHaveCount(0)
    await expect(page.locator('.tj-span.focus-dim')).toHaveCount(0)
    await expect(page.locator('.tj-cell.selected')).toHaveCount(1)
  })

  test('c_001：含 CONTEXT（Diff）与 COMPACTED 节点', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    await page.locator('.tj-ledger').waitFor({ timeout: 10_000 })

    await expect(page.locator('.tj-cell-label', { hasText: 'CONTEXT' })).toHaveCount(1)
    await expect(page.locator('.tj-cell-label', { hasText: 'COMPACTED' })).toHaveCount(1)
  })

  test('长会话 c_long：「加载更早」后节点数增加', async ({ page }) => {
    await gotoChat(page)
    await page.route('**/api/v1/conversations/c_long/trajectory**', async (route) => {
      if (route.request().url().includes('before_seq')) await new Promise((resolve) => setTimeout(resolve, 240))
      await route.continue()
    })
    await page.goto('/trajectory/c_long')
    await page.locator('.tj-ledger').waitFor({ timeout: 10_000 })

    await expect(page.locator('.tj-load-more')).toBeVisible()
    const before = await page.locator('.tj-cell').count()
    const loadMore = page.locator('.tj-load-more')
    await loadMore.click()
    await expect(loadMore).toBeDisabled()
    await expect(loadMore).toBeEnabled({ timeout: 10_000 })
    await page.waitForTimeout(400)
    const after = await page.locator('.tj-cell').count()
    expect(after).toBeGreaterThan(before)
  })
})

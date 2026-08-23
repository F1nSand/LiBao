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

  test('c_002：纯文本会话，无 TOOL 标签行', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_002')

    await expect(page.locator('.tj-ledger')).toContainText('什么是 SSE', { timeout: 10_000 })
    await expect(page.locator('.tj-cell-label', { hasText: 'TOOL' })).toHaveCount(0)
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
    await page.goto('/trajectory/c_long')
    await page.locator('.tj-ledger').waitFor({ timeout: 10_000 })

    await expect(page.locator('.tj-load-more')).toBeVisible()
    const before = await page.locator('.tj-cell').count()
    await page.locator('.tj-load-more').click()
    await page.waitForTimeout(400)
    const after = await page.locator('.tj-cell').count()
    expect(after).toBeGreaterThan(before)
  })
})

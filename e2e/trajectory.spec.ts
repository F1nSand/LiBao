import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('对话轨迹页', () => {
  test('深链 c_001：时间轴 + 台账（含 calculator）+ 选中联动详情 + 返回', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')

    // 台账：user #1 与 calculator 工具行
    await expect(page.locator('.tj-ledger')).toContainText('#1', { timeout: 10_000 })
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

  test('c_002：纯文本会话，无工具行', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_002')

    await expect(page.locator('.tj-ledger')).toContainText('什么是 SSE', { timeout: 10_000 })
    await expect(page.locator('.tj-cell-pill', { hasText: '工具' })).toHaveCount(0)
  })

  test('跨视图定位：?focus=tc_seed 自动选中工具记录并打开详情', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001?focus=tc_seed')

    await expect(page.locator('.tj-cell.selected')).toContainText('calculator', { timeout: 10_000 })
    await expect(page.locator('.tj-detail')).toContainText('入参')
  })

  test('四种投影（顺序/耗时/时间/实际）均可渲染', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    await page.locator('.tj-timeline').waitFor({ timeout: 10_000 })

    for (const name of ['顺序', '耗时', '时间', '实际']) {
      await page.locator('.el-radio-button', { hasText: name }).click()
      await page.waitForTimeout(120)
      await expect(page.locator('.tj-timeline')).toBeVisible()
      await expect(page.locator('.tj-lane')).toHaveCount(3)
    }
  })

  test('c_001：含 context（Diff）与 compaction 节点', async ({ page }) => {
    await gotoChat(page)
    await page.goto('/trajectory/c_001')
    await page.locator('.tj-ledger').waitFor({ timeout: 10_000 })

    await expect(page.locator('.tj-cell-pill', { hasText: '上下文' })).toHaveCount(1)
    await expect(page.locator('.tj-cell-pill', { hasText: '压缩' })).toHaveCount(1)
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

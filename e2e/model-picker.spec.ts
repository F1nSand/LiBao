import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

test.describe('换模型（交接板 ←后端 2026-08-27：provider 唯一激活热切换）', () => {
  // 无数量/初始状态假设（mock 内存态跨测试运行持久化）：恰一项激活、任选未激活项切换
  test('发送按钮左侧展示当前生效模型名；popover 选择器切换 → 按钮与「当前」徽标刷新', async ({ page }) => {
    await gotoChat(page)

    // active provider 在页面挂载时就应加载完成，不能等首次点击 popover 才从「未配置」补回。
    const modelBtn = page.locator('.composer .model-btn')
    await expect(modelBtn).toBeVisible()
    await expect(modelBtn).not.toHaveText('未配置')
    await expect(modelBtn).not.toHaveText('加载中…')
    await expect(modelBtn).toHaveText(/gpt-4o|deepseek-chat/)

    // 点开 popover：hint + 列表，恰一项处于激活态
    await modelBtn.click()
    const menu = page.locator('.model-picker .model-menu')
    await expect(menu.locator('.model-menu-hint')).toContainText('当前：')
    const items = menu.locator('.model-item')
    await expect(items.first()).toBeVisible()
    await expect(menu.locator('.model-item.active')).toHaveCount(1)

    // 记住切换前按钮文案，取任一未激活项作为切换目标
    const beforeLabel = ((await modelBtn.textContent()) ?? '').trim()
    const target = menu.locator('.model-item:not(.active)').first()
    const targetName = ((await target.locator('.model-item-name').textContent()) ?? '').trim()
    const targetModel = ((await target.locator('.model-item-model').textContent()) ?? '').trim()

    // 切到未激活项 → 成功提示 + popover 关闭 + 按钮变为该项
    await target.click()
    await expect(page.locator('.el-message').filter({ hasText: '已切换模型' })).toBeVisible()
    await expect(menu).not.toBeVisible()
    await expect(modelBtn).not.toHaveText(beforeLabel)
    await expect(modelBtn).toHaveText(targetModel || targetName)

    // 重开选择器：「当前」徽标已移到刚切换的项
    await modelBtn.click()
    const nowActive = menu.locator('.model-item.active')
    await expect(nowActive).toHaveCount(1)
    await expect(nowActive).toContainText(targetName)
    await expect(nowActive.locator('.el-tag')).toContainText('当前')
  })

  test('SettingsView Provider tab 与聊天页共享激活态（当前生效 hint 一致）', async ({ page }) => {
    await gotoChat(page)

    // 在聊天页切到「我的 DeepSeek」（若已激活点击为 no-op）；按钮与列表项含其模型名
    await page.locator('.composer .model-btn').click()
    const dsItem = page.locator('.model-picker .model-item', { hasText: 'deepseek-chat' })
    await dsItem.click()
    await expect(page.locator('.composer .model-btn')).toHaveText(/deepseek-chat/)

    // 设置页 Provider tab 显示同一激活态
    await page.goto('/settings')
    await page.locator('.settings-tag-row').getByText('Provider 配置').click()
    await expect(page.locator('.active-hint')).toContainText('我的 DeepSeek · deepseek-chat')
  })
})

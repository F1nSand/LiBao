import type { Page } from '@playwright/test'

export const PRIMARY_ROUTES = ['/chat', '/workspace', '/kb', '/tools', '/mcp', '/skills', '/memory', '/system', '/settings'] as const

export const RESPONSIVE_VIEWPORTS = [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'tablet', width: 800, height: 900 },
  { name: 'desktop', width: 1440, height: 900 },
] as const

/** 单用户本地模式：无登录流程，直接进入 /chat 工作台（等 ChatView 挂载，避免懒加载路由竞态） */
export async function gotoChat(page: Page) {
  await page.goto('/chat')
  await page.locator('.chat-view').waitFor({ state: 'visible', timeout: 15_000 })
  await page.locator('.sidebar').waitFor({ state: 'visible' })
}

/** 在 /chat 发送一条消息 */
export async function sendMessage(page: Page, content: string) {
  const input = page.locator('.composer textarea')
  await input.fill(content)
  await input.press('Enter')
}

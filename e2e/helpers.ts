import type { Page } from '@playwright/test'

/** 登录并等待进入 /chat */
export async function login(page: Page, username = 'admin', password = 'admin123') {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL('**/chat')
  await page.locator('.sidebar').waitFor({ state: 'visible' })
}

/** 在 /chat 发送一条消息 */
export async function sendMessage(page: Page, content: string) {
  const input = page.locator('.composer textarea')
  await input.fill(content)
  await input.press('Enter')
}

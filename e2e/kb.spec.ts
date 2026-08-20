import { test, expect } from '@playwright/test'
import { login } from './helpers'

test.describe('知识库上传状态收敛（不刷新，mock 异步链 uploaded→indexed）', () => {
  test('kb_upload_converge：非空集合上传 → 自动 已索引 + chunks>0 + 重索引按钮', async ({ page }) => {
    await login(page)
    await page.goto('/kb')
    await page.locator('.kb-collections').waitFor({ state: 'visible' })

    await page.setInputFiles('#kb-file-input', {
      name: 'e2e-上传.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('a'.repeat(3000)),
    })

    const row = page.locator('.el-table__body tr', { hasText: 'e2e-上传.md' })
    await expect(row).toBeVisible({ timeout: 10_000 })
    // 不刷新自动收敛：上传 → 轮询 → 已索引（无修复会卡「已上传」直到刷新 → 超时失败）
    await expect(row.locator('.chunk-status')).toContainText('已索引', { timeout: 15_000 })
    await expect(row.locator('.chunk-status')).toContainText('chunks')
    await expect(row.locator('.chunk-status')).not.toContainText('0 chunks')
    // 操作列随已索引出现「重索引」（live 态回写 store 行，读 row.status）
    await expect(row.locator('button', { hasText: '重索引' })).toBeVisible()
  })

  test('kb_upload_empty：空集合上传 → 同样自动收敛，不卡「已上传」', async ({ page }) => {
    await login(page)
    await page.goto('/kb')
    await page.locator('.kb-collections').waitFor({ state: 'visible' })

    await page.getByRole('button', { name: '新建集合' }).click()
    await page.getByPlaceholder('集合名称').fill('e2e 空集合')
    await page.getByRole('button', { name: '创建' }).click()
    await expect(page.locator('.kb-col-item', { hasText: 'e2e 空集合' })).toBeVisible()

    await page.setInputFiles('#kb-file-input', {
      name: '空集.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('b'.repeat(1500)),
    })

    const row = page.locator('.el-table__body tr', { hasText: '空集.md' })
    await expect(row).toBeVisible({ timeout: 10_000 })
    await expect(row.locator('.chunk-status')).toContainText('已索引', { timeout: 15_000 })
    await expect(row.locator('.chunk-status')).toContainText('chunks')
    await expect(row.locator('.chunk-status')).not.toContainText('0 chunks')
  })
})

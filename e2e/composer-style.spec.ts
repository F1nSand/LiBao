import { test, expect } from '@playwright/test'
import { gotoChat } from './helpers'

async function enterWorkspace(page: Parameters<typeof gotoChat>[0]) {
  await page.goto('/workspace')
  await page
    .locator('.ws-card', { hasText: '产品文档' })
    .getByRole('button', { name: '进入工作区' })
    .click()
  await expect(page).toHaveURL(/\/workspace\/ws_001/)
  await expect(page.locator('.composer')).toBeVisible()
}

async function readComposerStyle(page: Parameters<typeof gotoChat>[0]) {
  return page.evaluate(() => {
    const composer = document.querySelector('.composer') as HTMLElement | null
    const textarea = document.querySelector('.composer textarea') as HTMLTextAreaElement | null
    const textareaInner = document.querySelector(
      '.composer .el-textarea__inner',
    ) as HTMLElement | null
    const controls = Array.from(
      document.querySelectorAll('.composer .upload-btn, .composer .model-btn, .composer-submit'),
    ) as HTMLElement[]
    return {
      composer: composer
        ? {
            borderRadius: getComputedStyle(composer).borderRadius,
            boxShadow: getComputedStyle(composer).boxShadow,
          }
        : null,
      textarea: textarea
        ? {
            borderStyle: getComputedStyle(textareaInner ?? textarea).borderStyle,
            boxShadow: getComputedStyle(textareaInner ?? textarea).boxShadow,
          }
        : null,
      controls: controls.map((element) => ({ height: element.getBoundingClientRect().height })),
    }
  })
}

test.describe('composer 视觉契约', () => {
  test('聊天 composer 使用编辑器卡片和统一桌面控件', async ({ page }) => {
    await gotoChat(page)

    const composerInput = page.locator('.composer-input').first()
    const composerOrder = await composerInput.evaluate((element) =>
      Array.from(element.children).map((child) => {
        if (child.classList.contains('composer-textarea')) return 'textarea'
        if (child.classList.contains('composer-toolbar')) return 'toolbar'
        return child.className
      }),
    )
    expect(composerOrder).toEqual(['textarea', 'toolbar'])
    await expect(composerInput.locator('.char-count')).toHaveCount(0)
    await expect(composerInput.locator('.composer-leading > .uploader')).toBeVisible()
    await expect(composerInput.locator('.composer-leading .upload-btn')).toHaveAccessibleName('添加文件')
    await expect(composerInput.locator('.composer-actions .model-btn')).toBeVisible()
    await expect(composerInput.locator('.composer-actions .composer-submit')).toBeVisible()

    const style = await readComposerStyle(page)
    expect(style.composer?.borderRadius).toBe('16px')
    expect(style.composer?.boxShadow).not.toBe('none')
    expect(style.textarea?.borderStyle).toBe('none')
    expect(style.textarea?.boxShadow).toBe('none')

    const heights = style.controls.map((control) => control.height)
    expect(heights.length).toBe(3)
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(1)
    expect(heights[0]).toBeGreaterThanOrEqual(36)

    const borderStyles = await composerInput.locator('.upload-btn, .model-btn, .composer-submit').evaluateAll((elements) =>
      elements.map((element) => getComputedStyle(element).borderStyle),
    )
    expect(borderStyles.every((style) => style === 'none')).toBeTruthy()
  })

  test('工作区 composer 保持相同的控件高度与卡片层次', async ({ page }) => {
    await gotoChat(page)
    await enterWorkspace(page)

    const composerInput = page.locator('.composer-input').first()
    const composerOrder = await composerInput.evaluate((element) =>
      Array.from(element.children).map((child) => {
        if (child.classList.contains('composer-textarea')) return 'textarea'
        if (child.classList.contains('composer-toolbar')) return 'toolbar'
        return child.className
      }),
    )
    expect(composerOrder).toEqual(['textarea', 'toolbar'])
    await expect(composerInput.locator('.char-count')).toHaveCount(0)
    const leading = composerInput.locator(':scope > .composer-toolbar > .composer-leading')
    await expect(leading.locator(':scope > .uploader')).toBeVisible()
    await expect(leading.locator(':scope > .composer-divider')).toHaveText('|')
    await expect(leading.getByRole('button', { name: '引用工作区文件' })).toBeVisible()
    const actions = composerInput.locator(':scope > .composer-toolbar > .composer-actions')
    await expect(actions.locator(':scope > .model-btn')).toBeVisible()
    await expect(actions.locator(':scope > .composer-submit')).toBeVisible()

    const style = await readComposerStyle(page)
    expect(style.composer?.borderRadius).toBe('16px')
    expect(style.composer?.boxShadow).not.toBe('none')
    expect(style.textarea?.borderStyle).toBe('none')
    expect(style.textarea?.boxShadow).toBe('none')

    const controls = page.locator(
      '.composer .upload-btn, .composer .composer-leading .el-button, .composer .model-btn, .composer-submit',
    )
    const heights = await controls.evaluateAll((elements) =>
      elements.map((element) => element.getBoundingClientRect().height),
    )
    expect(heights.length).toBe(4)
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(1)
    expect(heights[0]).toBeGreaterThanOrEqual(36)

    const borderStyles = await composerInput.locator('.upload-btn, .composer-leading .el-button, .model-btn, .composer-submit').evaluateAll(
      (elements) => elements.map((element) => getComputedStyle(element).borderStyle),
    )
    expect(borderStyles.every((style) => style === 'none')).toBeTruthy()
  })

  test.describe('移动端', () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test('保留卡片层次、44px 触控尺寸且不横向溢出', async ({ page }) => {
      await gotoChat(page)

      const layout = await page.evaluate(() => {
        const composer = document.querySelector('.composer') as HTMLElement
        const controls = Array.from(
          document.querySelectorAll(
            '.composer .upload-btn, .composer .model-btn, .composer-submit',
          ),
        ) as HTMLElement[]
        return {
          width: composer.clientWidth,
          scrollWidth: composer.scrollWidth,
          borderRadius: getComputedStyle(composer).borderRadius,
          controls: controls.map((element) => ({ height: element.getBoundingClientRect().height })),
        }
      })

      expect(layout.width).toBeGreaterThan(0)
      expect(layout.scrollWidth).toBeLessThanOrEqual(layout.width)
      expect(layout.borderRadius).toBe('16px')
      expect(layout.controls.every((control) => control.height >= 44)).toBeTruthy()
    })
  })
})

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CodeEditor from './CodeEditor.vue'

describe('CodeEditor（预览/编辑代码编辑器）', () => {
  it('渲染行号 gutter + 高亮 pre + textarea 内容一致', () => {
    const src = 'const a = 1\nconst b = 2'
    const wrapper = mount(CodeEditor, { props: { modelValue: src } })
    expect(wrapper.get('.ce-gutter').text()).toBe('1\n2')
    // hljs 高亮不改文本内容（.value 保留原文）
    expect(wrapper.get('.ce-pre code').text()).toBe(src)
    expect((wrapper.get('.ce-ta').element as HTMLTextAreaElement).value).toBe(src)
  })

  it('input 触发 update:modelValue', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'abc' } })
    await wrapper.get('.ce-ta').setValue('abcd')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['abcd'])
  })

  it('Ctrl+S 触发 save；Tab 插入两空格并保留 caret 偏移', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'a' } })
    const ta = wrapper.get('.ce-ta')

    await ta.trigger('keydown', { key: 's', ctrlKey: true })
    expect(wrapper.emitted('save')).toHaveLength(1)

    // Tab 在位置 1 插入两空格 → 'a  '
    const el = ta.element as HTMLTextAreaElement
    el.setSelectionRange(1, 1)
    await ta.trigger('keydown', { key: 'Tab' })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['a  '])
  })

  it('focus/blur 透传给父级（auto-refresh 守卫依赖）', async () => {
    const wrapper = mount(CodeEditor, { props: { modelValue: 'x' } })
    const ta = wrapper.get('.ce-ta')
    await ta.trigger('focus')
    await ta.trigger('blur')
    expect(wrapper.emitted('focus')).toHaveLength(1)
    expect(wrapper.emitted('blur')).toHaveLength(1)
  })
})

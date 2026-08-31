import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import JsonViewer from './JsonViewer.vue'

describe('JsonViewer', () => {
  it('渲染原始值', () => {
    const w = mount(JsonViewer, { props: { data: 42 } })
    expect(w.text()).toContain('42')
  })

  it('渲染 null', () => {
    const w = mount(JsonViewer, { props: { data: null } })
    expect(w.text()).toContain('null')
  })

  it('渲染字符串带引号', () => {
    const w = mount(JsonViewer, { props: { data: 'hi' } })
    expect(w.text()).toContain('"hi"')
  })

  it('递归渲染嵌套对象', () => {
    const w = mount(JsonViewer, { props: { data: { a: { b: 1 }, c: 'x' } } })
    expect(w.text()).toContain('a')
    expect(w.text()).toContain('b')
    expect(w.text()).toContain('c')
  })

  it('渲染数组', () => {
    const w = mount(JsonViewer, { props: { data: [1, 'two', { three: 3 }] } })
    expect(w.text()).toContain('three')
  })

  it('深递归不崩', () => {
    const deep = { l1: { l2: { l3: { l4: 'leaf' } } } }
    const w = mount(JsonViewer, { props: { data: deep } })
    expect(w.text()).toContain('leaf')
  })
})

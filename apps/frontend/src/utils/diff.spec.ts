import { describe, expect, it } from 'vitest'
import { lineDiff, type DiffSegment } from './diff'

function types(segs: DiffSegment[]): string[] {
  return segs.map((s) => s.type)
}

describe('lineDiff（行级统一 diff）', () => {
  it('无变化 → 全部 context', () => {
    const segs = lineDiff('a\nb', 'a\nb')
    expect(types(segs)).toEqual(['ctx'])
    expect(segs[0].lines).toEqual(['a', 'b'])
  })

  it('追加行 → add 段', () => {
    const segs = lineDiff('a', 'a\nb')
    expect(types(segs)).toEqual(['ctx', 'add'])
    expect(segs[1].lines).toEqual(['b'])
  })

  it('删除行 → del 段', () => {
    const segs = lineDiff('a\nb', 'a')
    expect(types(segs)).toEqual(['ctx', 'del'])
    expect(segs[1].lines).toEqual(['b'])
  })

  it('修改一行 → del + add', () => {
    const segs = lineDiff('a\nb\nc', 'a\nX\nc')
    expect(types(segs)).toEqual(['ctx', 'del', 'add', 'ctx'])
    expect(segs[1].lines).toEqual(['b'])
    expect(segs[2].lines).toEqual(['X'])
  })

  it('空 after → 全 del', () => {
    const segs = lineDiff('a\nb', '')
    expect(types(segs)).toEqual(['del'])
    expect(segs[0].lines).toEqual(['a', 'b'])
  })

  it('空 before → 全 add', () => {
    const segs = lineDiff('', 'x\ny')
    expect(types(segs)).toEqual(['add'])
    expect(segs[0].lines).toEqual(['x', 'y'])
  })
})

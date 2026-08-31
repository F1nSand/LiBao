import { describe, expect, it, vi } from 'vitest'
import {
  collectLoadedPaths,
  patchLayerChildren,
  preloadVisibleFolders,
  signatureOf,
  type ElTreeLike,
  type TreeNodeLike,
} from './workspace-tree'
import type { WorkspaceFile } from '@/types'

/** 假 el-tree Node：TreeNodeLike + childNodes（实现本工具依赖的最小接口，loadData 同步完成） */
interface FakeNode extends TreeNodeLike {
  childNodes: FakeNode[]
}

function makeNode(
  key: string,
  level: number,
  opts: { loaded?: boolean; expanded?: boolean; data?: WorkspaceFile } = {},
): FakeNode {
  const node = {
    key,
    level,
    loaded: opts.loaded ?? false,
    loading: false,
    expanded: opts.expanded ?? false,
    data: opts.data,
    childNodes: [] as FakeNode[],
  } as FakeNode
  node.insertChild = (child, index) => {
    const data = 'data' in child ? (child as { data: WorkspaceFile }).data : (child as FakeNode).data!
    const n = makeNode(data.path, node.level + 1, { data })
    node.childNodes.splice(index ?? node.childNodes.length, 0, n)
  }
  node.removeChild = (child) => {
    const i = node.childNodes.indexOf(child as FakeNode)
    if (i >= 0) node.childNodes.splice(i, 1)
  }
  node.loadData = (cb?: () => void) => {
    node.loading = false
    node.loaded = true
    cb?.()
  }
  node.eachNode = (cb: (n: TreeNodeLike) => void) => {
    const arr = [node]
    while (arr.length) {
      const n = arr.shift()!
      arr.unshift(...n.childNodes)
      cb(n)
    }
  }
  return node
}

/** 假树：getNode 动态从根查找（模拟真实 el-tree registerNode） */
function makeTree(root: FakeNode): ElTreeLike {
  const find = (key: string, node: FakeNode): FakeNode | null =>
    node.key === key ? node : node.childNodes.reduce<FakeNode | null>((acc, n) => acc ?? find(key, n), null)
  return {
    store: {
      root,
      getNode: (key: string) => find(key, root),
    },
  }
}

/** 构造 WorkspaceFile（path 即 node-key；默认文件） */
const f = (path: string, size = 0, isDir = false): WorkspaceFile => ({
  name: path.split('/').pop() ?? path,
  path,
  is_dir: isDir,
  size,
})

describe('workspace-tree 外科逐层修补（patchLayerChildren）', () => {
  it('纯增：缺失项按最终下标插入（首/中/尾），未变化节点引用保持', () => {
    const node = makeNode('', 0, { loaded: true })
    const a = makeNode('a.md', 1, { data: f('a.md') })
    const b = makeNode('b.md', 1, { data: f('b.md') })
    node.childNodes = [a, b]

    patchLayerChildren(node, [f('x.md'), f('a.md'), f('y.md'), f('b.md'), f('z.md')])

    expect(node.childNodes.map((n) => n.key)).toEqual(['x.md', 'a.md', 'y.md', 'b.md', 'z.md'])
    expect(node.childNodes[1]).toBe(a)
    expect(node.childNodes[3]).toBe(b)
  })

  it('纯删：新列表不存在的子节点被移除', () => {
    const node = makeNode('', 0)
    const a = makeNode('a.md', 1, { data: f('a.md') })
    const b = makeNode('b.md', 1, { data: f('b.md') })
    const c = makeNode('c.md', 1, { data: f('c.md') })
    node.childNodes = [a, b, c]

    patchLayerChildren(node, [f('a.md'), f('c.md')])

    expect(node.childNodes).toEqual([a, c])
  })

  it('改：同 path 数据变化 → 就地更新 data，节点引用不变（不重建）', () => {
    const node = makeNode('', 0)
    const a = makeNode('a.md', 1, { data: f('a.md', 10) })
    node.childNodes = [a]

    patchLayerChildren(node, [f('a.md', 99)])

    expect(node.childNodes[0]).toBe(a)
    expect(a.data?.size).toBe(99)
  })

  it('混合：删+增+改 最终顺序正确，未变化节点引用保持', () => {
    const node = makeNode('', 0)
    const a = makeNode('a.md', 1, { data: f('a.md', 10) })
    const b = makeNode('b.md', 1, { data: f('b.md') })
    const c = makeNode('c.md', 1, { data: f('c.md') })
    const d = makeNode('d.md', 1, { data: f('d.md') })
    node.childNodes = [a, b, c, d]

    // b/d 删；x 头部增；y 位 3 增；a size 10→20 就地改
    patchLayerChildren(node, [f('x.md'), f('a.md', 20), f('c.md'), f('y.md')])

    expect(node.childNodes.map((n) => n.key)).toEqual(['x.md', 'a.md', 'c.md', 'y.md'])
    expect(node.childNodes[1]).toBe(a)
    expect(node.childNodes[2]).toBe(c)
    expect(a.data?.size).toBe(20)
  })

  it('空列表：全删', () => {
    const node = makeNode('', 0)
    node.childNodes = [makeNode('a.md', 1, { data: f('a.md') }), makeNode('b.md', 1, { data: f('b.md') })]

    patchLayerChildren(node, [])

    expect(node.childNodes).toEqual([])
  })

  it('无变化：不触发 insertChild/removeChild（签名层已挡，双重保险）', () => {
    const node = makeNode('', 0)
    const a = makeNode('a.md', 1, { data: f('a.md', 10) })
    const b = makeNode('b.md', 1, { data: f('b.md') })
    node.childNodes = [a, b]
    const insertSpy = vi.fn(node.insertChild)
    const removeSpy = vi.fn(node.removeChild)
    node.insertChild = insertSpy
    node.removeChild = removeSpy

    patchLayerChildren(node, [f('a.md', 10), f('b.md')])

    expect(insertSpy).not.toHaveBeenCalled()
    expect(removeSpy).not.toHaveBeenCalled()
  })
})

describe('workspace-tree 文件树工具', () => {
  it('signatureOf：name/is_dir/size 编码；同内容同签名，size 变化签名变', () => {
    const a = [
      { name: 'a.md', is_dir: false, size: 10 },
      { name: 'docs', is_dir: true, size: 0 },
    ]
    const b = [
      { name: 'a.md', is_dir: false, size: 10 },
      { name: 'docs', is_dir: true, size: 0 },
    ]
    const c = [
      { name: 'a.md', is_dir: false, size: 99 }, // 内容变化 → size 变
      { name: 'docs', is_dir: true },
    ]
    expect(signatureOf(a)).toBe('a.md|false|10,docs|true|0')
    expect(signatureOf(a)).toBe(signatureOf(b))
    expect(signatureOf(a)).not.toBe(signatureOf(c))
  })

  it('collectLoadedPaths：根层 + 已展开非叶；收起目录（含预加载）/未加载/叶节点排除', () => {
    const root = makeNode('', 0, { loaded: true, expanded: true })
    const docs = makeNode('docs', 1, { loaded: true, expanded: true })
    const src = makeNode('src', 1, { loaded: false }) // 未加载
    const hidden = makeNode('hidden', 1, { loaded: true, expanded: false }) // 已加载但收起（预加载）→ 不轮询
    const readme = makeNode('README.md', 1, { loaded: true }) // 叶文件
    root.childNodes = [docs, src, hidden, readme]
    docs.isLeaf = false
    src.isLeaf = false
    hidden.isLeaf = false
    readme.isLeaf = true

    const tree = makeTree(root)
    expect(collectLoadedPaths(tree)).toEqual(['', 'docs'])
  })

  it('preloadVisibleFolders：未加载非叶触发 loadData（loaded 置真）；已加载/加载中/叶跳过', () => {
    const root = makeNode('', 0, { loaded: true, expanded: true })
    const docs = makeNode('docs', 1, { loaded: false }) // 未加载目录 → 预载
    const src = makeNode('src', 1, { loaded: true }) // 已加载 → 跳过（保持 loaded）
    const busy = makeNode('busy', 1, { loaded: false }) // 加载中 → 跳过
    busy.loading = true
    const readme = makeNode('README.md', 1, { loaded: false }) // 叶文件 → 跳过
    docs.isLeaf = false
    src.isLeaf = false
    busy.isLeaf = false
    readme.isLeaf = true
    root.childNodes = [docs, src, busy, readme]

    preloadVisibleFolders(makeTree(root))
    expect(docs.loaded).toBe(true) // 预载触发
    expect(src.loaded).toBe(true) // 原本已加载，不受影响
    expect(busy.loaded).toBe(false) // 加载中跳过
    expect(readme.loaded).toBe(false) // 叶节点跳过
  })
})

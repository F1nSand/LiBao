import { describe, expect, it } from 'vitest'
import {
  collectLoadedPaths,
  refreshExpandedTree,
  reloadNode,
  signatureOf,
  snapshotExpandedPaths,
  type ElTreeLike,
  type TreeNodeLike,
} from './workspace-tree'

/** 假 el-tree Node：TreeNodeLike + childNodes（实现本工具依赖的最小接口，loadData/expand 同步完成） */
interface FakeNode extends TreeNodeLike {
  childNodes: FakeNode[]
}

function makeNode(key: string, level: number, opts: { loaded?: boolean; expanded?: boolean } = {}): FakeNode {
  const node = {
    key,
    level,
    loaded: opts.loaded ?? false,
    loading: false,
    expanded: opts.expanded ?? false,
    childNodes: [] as FakeNode[],
  } as FakeNode
  node.loadData = (cb?: () => void) => {
    node.loading = false
    node.loaded = true
    cb?.()
  }
  node.expand = (cb?: () => void) => {
    node.expanded = true
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

/** 假树：getNode 动态从根查找（reload 重建子节点后自动可见，模拟真实 el-tree registerNode） */
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

describe('workspace-tree 保展开刷新', () => {
  it('snapshotExpandedPaths 只收 level>0 且 loaded+expanded 的目录', () => {
    const root = makeNode('', 0, { loaded: true, expanded: true })
    const docs = makeNode('docs', 1, { loaded: true, expanded: true })
    const src = makeNode('src', 1, { loaded: true, expanded: false }) // 收起
    const guide = makeNode('docs/入门指南.md', 2, { loaded: true, expanded: true })
    root.childNodes = [docs, src]
    docs.childNodes = [guide]

    const tree = makeTree(root)
    expect(snapshotExpandedPaths(tree)).toEqual(['docs', 'docs/入门指南.md'])
  })

  it('reloadNode 置 loaded=false 后重新拉取', async () => {
    const node = makeNode('docs', 1, { loaded: true })
    await reloadNode(node)
    expect(node.loaded).toBe(true)
  })

  it('refreshExpandedTree 重载根并保持已展开目录展开、已收起保持收起', async () => {
    const root = makeNode('', 0, { loaded: true, expanded: true })
    const docs = makeNode('docs', 1, { loaded: true, expanded: true })
    const src = makeNode('src', 1, { loaded: true, expanded: false })
    root.childNodes = [docs, src]
    const tree = makeTree(root)

    // 模拟真实 el-tree：reload 根会重建顶层子 Node（新对象 expanded=false）
    root.loadData = (cb?: () => void) => {
      root.childNodes = [
        makeNode('docs', 1, { loaded: true, expanded: false }),
        makeNode('src', 1, { loaded: true, expanded: false }),
      ]
      root.loaded = true
      cb?.()
    }

    await refreshExpandedTree(tree)

    // 快照目录补展开；未展开目录保持收起（断言重建后的当前节点）
    expect(tree.store.getNode('docs')?.expanded).toBe(true)
    expect(tree.store.getNode('src')?.expanded).toBe(false)
  })

  it('refreshExpandedTree 防重入：刷新进行中重复调用返回 false 且不重载', async () => {
    const root = makeNode('', 0, { loaded: true, expanded: true })
    const tree = makeTree(root)
    tree.__refreshing = true
    await expect(refreshExpandedTree(tree)).resolves.toBe(false)
  })

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

  it('collectLoadedPaths：根层 + 已加载非叶；未加载/叶节点排除', () => {
    const root = makeNode('', 0, { loaded: true, expanded: true })
    const docs = makeNode('docs', 1, { loaded: true, expanded: true })
    const src = makeNode('src', 1, { loaded: false }) // 未加载
    const readme = makeNode('README.md', 1, { loaded: true }) // 叶文件
    root.childNodes = [docs, src, readme]
    docs.isLeaf = false
    src.isLeaf = false
    readme.isLeaf = true

    const tree = makeTree(root)
    expect(collectLoadedPaths(tree)).toEqual(['', 'docs'])
  })
})

import { nextTick } from 'vue'

/**
 * el-tree lazy 保展开刷新（工作区文件树轮询专用，docs/02 §4 资源管理器「动态显示」）。
 *
 * 背景：el-tree 实例**没有 reload() 方法**（`treeRef.reload()` 是静默 no-op bug）；而
 * `Node.loadData()` 仅在 `!loaded` 时真正拉取（node.mjs），且 reload 父节点会重建子 Node
 * （insertChild 每次 new Node）、`expanded` 重置为 false。故「刷新已展开目录并保持展开」=
 * 快照展开路径 → 重载根 → 按快照顺序（父先子后）逐个 `expand(cb)` 补展开
 * （`expand` 对未加载节点会自动 loadData 并在完成后回调，天然提供顺序化钩子）。
 *
 * 只依赖 el-tree store/Node 的最小接口，便于单测（可传假树）。
 */

/** el-tree TreeStore 最小接口（本工具用到的部分） */
export interface TreeStoreLike {
  root: TreeNodeLike
  getNode(key: string): TreeNodeLike | null
}

/** el-tree Node 最小接口 */
export interface TreeNodeLike {
  key: string | null
  level: number
  loaded: boolean
  loading: boolean
  expanded: boolean
  isLeaf?: boolean
  loadData?: (cb?: () => void) => void
  expand?: (cb?: () => void) => void
  eachNode?: (cb: (node: TreeNodeLike) => void) => void
}

export interface ElTreeLike {
  store: TreeStoreLike
  /** 防重入标记（挂在树对象上而非模块级，避免多实例互相干扰） */
  __refreshing?: boolean
}

/** 快照当前已展开的目录路径（eachNode 遍历，父先子后；排除 level 0 根节点） */
export function snapshotExpandedPaths(tree: ElTreeLike): string[] {
  const paths: string[] = []
  tree.store.root.eachNode?.((node) => {
    if (node.level > 0 && node.loaded && node.expanded && node.key != null) paths.push(node.key)
  })
  return paths
}

/** 重载单个节点：置 loaded=false 后 loadData（拉取完成后 resolve）。调用方须保证该节点非 loading 中。 */
export function reloadNode(node: TreeNodeLike): Promise<void> {
  node.loaded = false
  return new Promise<void>((resolve) => {
    node.loadData?.(() => resolve())
  })
}

/**
 * 刷新文件树并保持已展开目录展开。
 * 防重入：刷新进行中重复调用直接返回 false（el-tree 并发 loadData 会静默丢回调导致展开卡住）。
 * 返回是否实际执行了刷新。
 */
export async function refreshExpandedTree(tree: ElTreeLike): Promise<boolean> {
  if (tree.__refreshing) return false
  tree.__refreshing = true
  try {
    const paths = snapshotExpandedPaths(tree)
    await reloadNode(tree.store.root)
    await nextTick()
    for (const p of paths) {
      const node = tree.store.getNode(p)
      if (!node || node.expanded) continue
      await new Promise<void>((resolve) => node.expand?.(() => resolve()))
    }
    return true
  } finally {
    tree.__refreshing = false
  }
}

/**
 * 收集可见层路径：根层（''）+ 所有已加载非叶节点（轮询数据变化检测用）。
 * 轮询只需对比这些层的数据（未加载/未展开的层不在视野内，无刷新价值）。
 */
export function collectLoadedPaths(tree: ElTreeLike): string[] {
  const paths: string[] = ['']
  // 只收已展开的已加载非叶——预加载会让收起目录也 loaded，若按 loaded 收会触发对收起目录的重建
  // （用户正交互时树被刷新、下拉被卸载）；只轮询已展开目录 = 无预加载时的原语义。
  tree.store.root.eachNode?.((node) => {
    if (node.level > 0 && node.loaded && node.expanded && node.isLeaf === false && node.key != null)
      paths.push(node.key)
  })
  return paths
}

/** 预加载所有可见文件夹的子节点（不展开、不改变 expanded）——让 `node.childNodes` 就绪，
 * 供树节点插槽据此区分「空文件夹 / 有内容文件夹」的图标。
 * 只处理已渲染（eachNode 可达）且未加载、非加载中的非叶节点；`loadData` 仅 `!loaded` 时真正拉取，
 * 故重复调用廉价（首载后跳过）。
 */
export function preloadVisibleFolders(tree: ElTreeLike): void {
  tree.store.root.eachNode?.((node) => {
    if (node.level > 0 && node.isLeaf === false && !node.loaded && !node.loading) {
      node.loadData?.()
    }
  })
}

/** 文件列表签名：name|is_dir|size 拼接。轮询对比用——签名不变说明该层未变化，跳过刷新避免闪烁。 */
export function signatureOf(files: Array<{ name: string; is_dir: boolean; size?: number }>): string {
  return files.map((f) => `${f.name}|${f.is_dir}|${f.size ?? 0}`).join(',')
}

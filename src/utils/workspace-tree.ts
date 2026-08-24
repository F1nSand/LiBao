import type { WorkspaceFile } from '@/types'

/**
 * el-tree lazy 树外科逐层修补（工作区文件树轮询专用，docs/02 §4 资源管理器「动态显示」）。
 *
 * 背景：旧实现「快照展开路径 → 重载根 → 逐级补展开」会整树重建（所有顶层 Node 对象替换、
 * expanded 归 false），任何一层变化都导致已展开目录先收起再逐层展开（闪烁）。现改为**只修补
 * 变化层**：el-tree Node 提供 `insertChild/removeChild`（node.d.ts 公共 API），按最新 children
 * 列表增删改，未变化子节点（DOM/展开态/loaded）原样保留。
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
  /** 节点数据（reactive 深代理：就地 Object.assign 即触发行渲染） */
  data?: WorkspaceFile
  childNodes?: TreeNodeLike[]
  loadData?: (cb?: () => void) => void
  eachNode?: (cb: (node: TreeNodeLike) => void) => void
  /** 插入子节点。必须传 batch=true：否则内部 getChildren(true) 会给 node.data 塞 children 数组（副作用，触发 tree-node 的 data.children watch） */
  insertChild?: (child: { data: WorkspaceFile } | TreeNodeLike, index?: number, batch?: boolean) => void
  removeChild?: (child: TreeNodeLike) => void
}

export interface ElTreeLike {
  store: TreeStoreLike
}

/**
 * 单层外科修补：按最新 children 列表对已加载节点做 diff——
 * ① 删：旧 childNodes 中 path 不在新列表的 → removeChild（deregister 递归清理子树）；
 * ② 改：同 path 但数据变化 → Object.assign 就地更新（节点身份保留，不重建）；
 * ③ 增：缺失项按最终下标升序 insertChild（先删后插 + 升序 splice 保证最终顺序正确）。
 * 未变化子节点完全不触碰 → 其 DOM/展开态/loaded 保留，杜绝整树重建闪烁。
 */
export function patchLayerChildren(node: TreeNodeLike, files: WorkspaceFile[]): void {
  const old = [...(node.childNodes ?? [])]
  const kept = new Map(old.map((c) => [c.data?.path, c]))
  for (const c of old) {
    if (c.data && !files.some((f) => f.path === c.data!.path)) node.removeChild?.(c)
  }
  for (let i = 0; i < files.length; i++) {
    const f = files[i]
    const ex = kept.get(f.path)
    if (ex && ex.data) Object.assign(ex.data, f)
    else node.insertChild?.({ data: f }, i, true)
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

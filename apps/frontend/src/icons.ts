import { defineComponent, h, type Component } from 'vue'
import {
  ArrowLeftRight,
  Bell,
  BookOpen,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Crosshair,
  Cpu,
  EllipsisVertical,
  EyeOff,
  FilePlus,
  FileText,
  Folder,
  FolderDot,
  FolderOpen,
  FolderPlus,
  Gauge,
  LayoutGrid,
  Link,
  LoaderCircle,
  MessageSquare,
  NotebookText,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  PauseCircle,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Star,
  Timer,
  Upload,
  WandSparkles,
  Wrench,
  X,
} from 'lucide-vue-next'

/**
 * 全局图标映射（《02》前端设计 主题系统）：App 图标统一走 Lucide（现代简约描边），
 * key = 模板/路由里沿用至今的 Element 图标字符串名（`<component :is>` / `:icon` / `:prefix-icon`），
 * value = 对应 Lucide 组件。main.ts 按同名注册，模板与路由零改动。
 *
 * Element 内部图标（el-alert/el-message/el-button loading 等）仍由 element-plus 自带，不走此表。
 */
function filled(c: Component): Component {
  return defineComponent({
    name: 'FilledLucideIcon',
    setup(_props, { attrs }) {
      return () => h(c, { ...attrs, fill: 'currentColor' })
    },
  })
}

export const appIcons: Record<string, Component> = {
  Aim: Crosshair,
  ArrowDown: ChevronDown,
  ArrowLeft: ChevronLeft,
  ArrowRight: ChevronRight,
  Bell,
  Box: Package,
  ChatDotRound: MessageSquare,
  Close: X,
  Collection: BookOpen,
  Cpu,
  Document: FileText,
  DocumentAdd: FilePlus,
  Expand: ChevronsDownUp, // 通用展开 chevron（侧栏/工作区面板折叠由 PanelLeft* 替代）
  Fold: ChevronsUpDown, // 通用折叠 chevron
  Folder,
  FolderAdd: FolderPlus,
  FolderDot, // 有内容的文件夹（空文件夹用 Folder）
  FolderOpened: FolderOpen,
  Grid: LayoutGrid,
  Hide: EyeOff,
  Link,
  Loading: LoaderCircle,
  MagicStick: WandSparkles,
  MoreFilled: EllipsisVertical,
  Odometer: Gauge,
  Paperclip,
  Plus,
  Promotion: Send,
  Refresh: RefreshCw,
  Search,
  Setting: Settings,
  StarFilled: filled(Star),
  Switch: ArrowLeftRight,
  Tickets: NotebookText,
  Timer,
  Tools: Wrench,
  UploadFilled: filled(Upload),
  VideoPause: PauseCircle,
  // 现代面板折叠（VS Code 式）：侧栏 / 工作区左列
  PanelLeftClose,
  PanelLeftOpen,
}

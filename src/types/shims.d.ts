declare module 'markdown-it-task-lists' {
  import type MarkdownIt from 'markdown-it'
  interface TaskListsOptions {
    enabled?: boolean
    label?: boolean | string
    labelAfter?: boolean
  }
  export default function taskLists(md: MarkdownIt, options?: TaskListsOptions): void
}

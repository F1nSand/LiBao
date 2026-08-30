import { httpGet, httpPost } from './http'
import type { RestorePreview, RestoreResult } from '@/types'

export interface CheckpointHistoryItem {
  kind: 'checkpoint' | 'rollback_operation'
  id: string
  user_message_id?: string
  target_checkpoint_id?: string
  status: string
  mode?: string
  changed_file_count?: number
  created_at: string
}

export interface CheckpointHistory {
  conversation_id: string
  current_state_id?: string | null
  cursor: {
    active_message_head_id?: string | null
    active_graph_checkpoint_id?: string | null
    active_code_node_id?: string | null
    history_revision: number
  }
  items: CheckpointHistoryItem[]
}

export function listCheckpoints(id: string) {
  return httpGet<CheckpointHistory>(`/conversations/${id}/checkpoints`)
}

export function createRestorePreview(
  id: string,
  body: { target_checkpoint_id?: string; target_type?: 'checkpoint' | 'rollback_operation_before'; target_id?: string; mode: 'code_only' | 'conversation_only' | 'both' },
) {
  return httpPost<RestorePreview>(`/conversations/${id}/restore-previews`, body)
}

export function executeRestore(id: string, preview_id: string) {
  return httpPost<RestoreResult>(`/conversations/${id}/restores`, { preview_id })
}

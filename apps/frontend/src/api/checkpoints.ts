import { httpGet, httpPost } from './http'
import type { RestorePreview, RestoreResult, RollbackMode } from '@/types'

export type RestoreDialogTarget =
  | { type: 'checkpoint'; checkpointId: string; messageId: string }
  | { type: 'rollback_operation_before'; operationId: string }

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
  body: RestorePreviewRequest,
) {
  return httpPost<RestorePreview>(`/conversations/${id}/restore-previews`, body)
}

export type RestorePreviewRequest =
  | {
      target_type: 'checkpoint'
      target_checkpoint_id: string
      mode: RollbackMode
      client_request_id: string
    }
  | {
      target_type: 'rollback_operation_before'
      target_id: string
      client_request_id: string
    }

export interface RestoreExecuteRequest {
  preview_id: string
  expected_mode: RollbackMode
  client_request_id: string
}

export function executeRestore(id: string, body: RestoreExecuteRequest) {
  return httpPost<RestoreResult>(`/conversations/${id}/restores`, body)
}

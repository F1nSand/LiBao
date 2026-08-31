import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { createRestorePreview, executeRestore } = vi.hoisted(() => ({
  createRestorePreview: vi.fn(),
  executeRestore: vi.fn(),
}))

vi.mock('@/api/checkpoints', () => ({ createRestorePreview, executeRestore }))

import CheckpointRestoreDialog from './CheckpointRestoreDialog.vue'

function previewFor(body: { mode?: string; client_request_id: string }) {
  return {
    preview_id: `preview_${body.client_request_id}`,
    client_request_id: body.client_request_id,
    target: { type: 'checkpoint', id: 'cp_1', message_id: 'm_1' },
    mode: body.mode ?? 'both',
    conversation_revision: 2,
    expires_at: '2026-08-30T01:00:00.000Z',
    conversation: {
      action: body.mode === 'code_only' ? 'unchanged' : 'withdraw_from_target',
      active_message_head_after_id: null,
      withdrawn_from_message_id: body.mode === 'code_only' ? null : 'm_1',
      hidden_message_count: body.mode === 'code_only' ? 0 : 1,
      draft: body.mode === 'code_only' ? null : { source_message_id: 'm_1', content: '原输入', attachments: [], file_refs: [] },
    },
    files: [],
    warnings: [],
  }
}

function mountDialog(modelValue = false) {
  return mount(CheckpointRestoreDialog, {
    props: { modelValue, conversationId: 'c_1', target: { type: 'checkpoint', checkpointId: 'cp_1', messageId: 'm_1' } },
    global: {
      stubs: {
        ResponsiveDialog: {
          props: ['modelValue'],
          template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
        },
        'el-button': {
          props: ['disabled', 'loading'],
          emits: ['click'],
          template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })
}

describe('CheckpointRestoreDialog v2 preview consistency', () => {
  beforeEach(() => {
    createRestorePreview.mockReset()
    executeRestore.mockReset()
    createRestorePreview.mockImplementation((_id: string, body: { mode?: string; client_request_id: string }) => Promise.resolve(previewFor(body)))
    executeRestore.mockResolvedValue({
      operation_id: 'op_1',
      preview_id: 'preview',
      client_request_id: 'request',
      mode: 'both',
      target_message_id: 'm_1',
      status: 'completed',
      restored_files: 0,
      deleted_files: 0,
      skipped_conflicts: [],
      conversation: previewFor({ mode: 'both', client_request_id: 'request' }).conversation,
      undo_available: true,
      history_revision: 3,
    })
  })

  it('opens with checked both and confirms without mode toggle', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ modelValue: true })
    expect((wrapper.findAll('button').find((button) => button.text() === '取消')!.element as HTMLButtonElement).disabled).toBe(true)
    await flushPromises()

    expect((wrapper.find('input[value="both"]').element as HTMLInputElement).checked).toBe(true)
    expect((wrapper.findAll('button').find((button) => button.text() === '取消')!.element as HTMLButtonElement).disabled).toBe(false)
    expect(createRestorePreview).toHaveBeenCalledWith('c_1', expect.objectContaining({ mode: 'both', client_request_id: expect.any(String) }))
    const confirm = wrapper.findAll('button').find((button) => button.text() === '确认回滚')!
    expect((confirm.element as HTMLButtonElement).disabled).toBe(false)
    await confirm.trigger('click')
    expect(executeRestore).toHaveBeenCalledWith('c_1', expect.objectContaining({ expected_mode: 'both', client_request_id: expect.any(String) }))
  })

  it('reopens with both after a previous code-only selection', async () => {
    const wrapper = mountDialog(true)
    await flushPromises()
    await wrapper.find('input[value="code_only"]').trigger('change')
    await flushPromises()
    expect(createRestorePreview).toHaveBeenLastCalledWith('c_1', expect.objectContaining({ mode: 'code_only' }))

    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    expect((wrapper.find('input[value="both"]').element as HTMLInputElement).checked).toBe(true)
    expect(createRestorePreview).toHaveBeenLastCalledWith('c_1', expect.objectContaining({ mode: 'both' }))
  })

  it('ignores out-of-order preview responses from earlier request versions', async () => {
    const deferred: Array<{ body: { mode?: string; client_request_id: string }; resolve: (value: ReturnType<typeof previewFor>) => void }> = []
    createRestorePreview.mockImplementation((_id: string, body: { mode?: string; client_request_id: string }) => new Promise((resolve) => deferred.push({ body, resolve })))
    const wrapper = mountDialog(true)
    await flushPromises()
    ;(wrapper.vm as unknown as { beginPreview: (mode: 'code_only' | 'conversation_only' | 'both') => void }).beginPreview('code_only')
    ;(wrapper.vm as unknown as { beginPreview: (mode: 'code_only' | 'conversation_only' | 'both') => void }).beginPreview('conversation_only')
    await flushPromises()

    deferred[0].resolve(previewFor(deferred[0].body))
    deferred[1].resolve(previewFor(deferred[1].body))
    deferred[2].resolve(previewFor(deferred[2].body))
    await flushPromises()
    expect((wrapper.vm as unknown as { preview: { mode: string } }).preview.mode).toBe('conversation_only')
  })

  it('operation-before target sends no mode and executes the mode returned by preview', async () => {
    createRestorePreview.mockImplementation((_id: string, body: { client_request_id: string }) => Promise.resolve({
      ...previewFor({ mode: 'code_only', client_request_id: body.client_request_id }),
      target: { type: 'rollback_operation_before', id: 'op_1' },
      mode: 'code_only',
    }))
    const wrapper = mount(CheckpointRestoreDialog, {
      props: { modelValue: true, conversationId: 'c_1', target: { type: 'rollback_operation_before', operationId: 'op_1' } },
      global: { stubs: { ResponsiveDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' }, 'el-button': { props: ['disabled'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' } } },
    })
    await flushPromises()
    expect(createRestorePreview).toHaveBeenCalledWith('c_1', expect.not.objectContaining({ mode: expect.anything() }))
    expect(wrapper.find('.mode-grid').exists()).toBe(false)
    const confirm = wrapper.findAll('button').find((button) => button.text() === '确认回滚')!
    await confirm.trigger('click')
    expect(executeRestore).toHaveBeenCalledWith('c_1', expect.objectContaining({ expected_mode: 'code_only' }))
  })
})

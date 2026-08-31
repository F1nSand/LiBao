import { httpGet, httpPatch } from './http'
import type { SandboxMode, SandboxSettings } from '@/types'

export type { SandboxMode, SandboxSettings }

export function getSandboxSettings() {
  return httpGet<SandboxSettings>('/settings/sandbox')
}

export function updateSandboxSettings(mode: SandboxMode) {
  return httpPatch<SandboxSettings>('/settings/sandbox', { mode })
}

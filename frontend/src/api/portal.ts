import { request } from './client'

export interface WorkspaceEntry {
  id: 'erp' | 'ai' | 'lim' | 'oms' | 'storefront'
  name: string
  description: string
  deep_link: string | null
  identity_note: string
  available: boolean
  external: boolean
}

export interface WorkspaceList {
  items: WorkspaceEntry[]
}

export const fetchWorkspaces = () => request<WorkspaceList>('/portal/workspaces')

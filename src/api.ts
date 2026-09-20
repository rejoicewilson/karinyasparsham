const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export type ApiRole = 'ADMIN' | 'AGENT' | 'MEMBER'

export interface ApiProfile {
  id: string
  login_id: string
  full_name: string
  role: ApiRole
  must_change_password?: boolean
  taluk_name?: string | null
  bank?: { bank_name: string; branch_name: string; last4: string; ifsc_code: string } | null
  member_code?: string | null
  agent?: { id: string; full_name: string; phone?: string | null } | null
}

export interface Workspace {
  profile: ApiProfile
  cases: Record<string, any>[]
  members: Record<string, any>[]
  dues: Record<string, any>[]
  collections: Record<string, any>[]
  deposits: Record<string, any>[]
  taluks: Record<string, any>[]
  agents: Record<string, any>[]
  bank_accounts: Record<string, any>[]
  notifications: Record<string, any>[]
  case_whatsapp_tracking: Record<string, any>[]
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message)
  }
}

let refreshPromise: Promise<boolean> | null = null

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST', credentials: 'include'
    }).then(response => response.ok).catch(() => false).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

export async function apiRequest<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers, credentials: 'include' })
  const canRefresh = path === '/auth/session' || !path.startsWith('/auth/')
  if (response.status === 401 && retry && canRefresh) {
    if (await refreshSession()) return apiRequest<T>(path, init, false)
  }
  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = payload.error || {}
    if (response.status === 401 && canRefresh) window.dispatchEvent(new Event('karunya:session-expired'))
    throw new ApiError(error.code || 'REQUEST_FAILED', error.message || 'Request failed.', response.status)
  }
  return payload.data as T
}

export const authApi = {
  login: (loginId: string, password: string) => apiRequest<{ profile: ApiProfile }>('/auth/login', {
    method: 'POST', body: JSON.stringify({ login_id: loginId, password })
  }, false),
  session: () => apiRequest<{ profile: ApiProfile }>('/auth/session'),
  logout: () => apiRequest<void>('/auth/logout', { method: 'POST' }, false),
  changePassword: (newPassword: string) => apiRequest<{ profile: ApiProfile }>('/auth/change-password', {
    method: 'POST', body: JSON.stringify({ new_password: newPassword })
  }, false),
}

export const workspaceApi = {
  load: () => apiRequest<Workspace>('/workspace'),
  createAdminCollectionBatch: (payload: Record<string, unknown>) => apiRequest<Record<string, any>>('/admin/collection-batches', {
    method: 'POST', body: JSON.stringify(payload)
  }),
  recordCollection: (payload: Record<string, unknown>) => apiRequest('/agent/collections', {
    method: 'POST', body: JSON.stringify(payload)
  }),
  createHandover: (payload: Record<string, unknown>) => apiRequest<Record<string, any>>('/agent/handovers', {
    method: 'POST', body: JSON.stringify(payload)
  }),
  submitHandover: (id: string, version: number) => apiRequest<Record<string, any>>(`/agent/handovers/${id}/submit`, {
    method: 'POST', body: JSON.stringify({ expected_version: version })
  }),
  reviewHandover: (id: string, version: number, approve: boolean, reason?: string) =>
    apiRequest(`/admin/handovers/${id}/${approve ? 'approve' : 'reject'}`, {
      method: 'POST', body: JSON.stringify(approve ? { expected_version: version } : { expected_version: version, reason })
    }),
  uploadCasePhoto: async (file: File) => {
    const body = new FormData(); body.append('photo', file)
    return apiRequest<{ object_path: string }>('/admin/death-cases/photo', { method: 'POST', body })
  },
  casePreview: () => apiRequest<Record<string, any>>('/admin/death-cases/preview', { method: 'POST' }),
  publishCase: (payload: Record<string, unknown>) => apiRequest<Record<string, any>>('/admin/death-cases', {
    method: 'POST', body: JSON.stringify(payload)
  }),
  updateCaseWhatsAppStatus: (caseId: string, memberId: string, status: 'OPENED' | 'SENT' | 'NOT_SENT') =>
    apiRequest<Record<string, any>>(`/admin/death-cases/${caseId}/whatsapp/${memberId}`, {
      method: 'PUT', body: JSON.stringify({ status })
    }),
  createTaluk: (payload: Record<string, unknown>) => apiRequest('/admin/taluks', { method: 'POST', body: JSON.stringify(payload) }),
  updateTaluk: (id: string, payload: Record<string, unknown>) => apiRequest(`/admin/taluks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  createAgent: (payload: Record<string, unknown>) => apiRequest('/admin/agents', { method: 'POST', body: JSON.stringify(payload) }),
  updateAgent: (id: string, payload: Record<string, unknown>) => apiRequest(`/admin/agents/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  createMember: (payload: Record<string, unknown>) => apiRequest('/admin/members', { method: 'POST', body: JSON.stringify(payload) }),
  updateMember: (id: string, payload: Record<string, unknown>) => apiRequest(`/admin/members/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  createBank: (payload: Record<string, unknown>) => apiRequest('/admin/bank-accounts', { method: 'POST', body: JSON.stringify(payload) }),
  replaceBank: (id: string, payload: Record<string, unknown>) => apiRequest(`/admin/bank-accounts/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
}

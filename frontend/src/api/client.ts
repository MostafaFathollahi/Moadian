/** Thin fetch wrapper over the backend.
 *
 * Errors are surfaced with the server's own Persian message where there is one.
 * The backend already localises validation findings and maps the tax service's
 * error codes, so inventing a second set of messages here would only produce
 * two vocabularies for the same failure.
 */

import { clearSession, getToken } from '../lib/session'
import type {
  Buyer,
  CertificateCheck,
  Dashboard,
  EnvironmentInfo,
  GoodsService,
  InquiredRecord,
  InquiryOutcome,
  InvoicePayload,
  InvoiceRecord,
  PatternFields,
  PatternInfo,
  ProfileView,
  SigningMaterial,
  SubmitResult,
  UserInfo,
  VerifyResult,
} from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Pull the most useful message out of whatever shape the error took. */
function describe(status: number, body: unknown): string {
  if (typeof body === 'object' && body !== null) {
    const record = body as Record<string, unknown>
    const detail = record.detail
    if (typeof detail === 'string') return detail
    // A verification failure nests its summary under detail.
    if (typeof detail === 'object' && detail !== null) {
      const summary = (detail as Record<string, unknown>).summary
      if (typeof summary === 'string') return summary
    }
    if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI's own 422 shape.
      const first = detail[0] as Record<string, unknown>
      if (typeof first.msg === 'string') return `${first.msg} (${String(first.loc)})`
    }
  }
  return `خطای ${status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
    })
  } catch (cause) {
    throw new ApiError('ارتباط با سرور برقرار نشد.', 0, cause)
  }

  // A 401 means the session is gone — deactivated, password changed, or an
  // admin signed everyone out. Clearing here is what routes the app back to
  // the login screen instead of showing an empty page with an error on it.
  if (response.status === 401 && !path.startsWith('/api/auth/login')) {
    clearSession()
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()

  // Not every failure is JSON. A 500 from Starlette is the bare string
  // "Internal Server Error", and a proxy or gateway in front can return HTML.
  // Parsing before checking response.ok turned those into an unreadable
  // "Unexpected token 'I'" SyntaxError that escaped every caller's catch,
  // leaving the UI blank instead of showing what went wrong.
  let body: unknown = null
  let parsed = true
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    parsed = false
  }

  if (!response.ok) {
    const message = parsed
      ? describe(response.status, body)
      : text.trim().slice(0, 200) || `خطای ${response.status}`
    throw new ApiError(message, response.status, parsed ? body : text)
  }
  if (!parsed) {
    throw new ApiError('پاسخ سرور قابل خواندن نبود.', response.status, text)
  }
  return body as T
}

const encode = encodeURIComponent

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; user: UserInfo }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<UserInfo>('/api/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    request<{ ok: boolean; token: string }>('/api/auth/password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),

  users: () => request<UserInfo[]>('/api/admin/users'),
  createUser: (body: {
    username: string
    password: string
    display_name?: string
    role?: string
  }) => request<UserInfo>('/api/admin/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (id: number, body: Record<string, unknown>) =>
    request<UserInfo>(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  removeUser: (id: number) =>
    request<{ ok: boolean; deleted: boolean }>(`/api/admin/users/${id}`, { method: 'DELETE' }),
  revokeUserSessions: (id: number) =>
    request<{ ok: boolean; token: string | null }>(`/api/admin/users/${id}/sessions/revoke`, {
      method: 'POST',
    }),
  revokeAllSessions: () =>
    request<{ ok: boolean; token: string }>('/api/admin/users/sessions/revoke-all', {
      method: 'POST',
    }),

  environments: () => request<EnvironmentInfo[]>('/api/environments'),
  patterns: () => request<PatternInfo[]>('/api/patterns'),
  patternFields: (pattern: number, type: number) =>
    request<PatternFields>(`/api/patterns/${pattern}/fields?type=${type}`),
  signingMaterial: () => request<SigningMaterial[]>('/api/signing-material'),
  verifySigningMaterial: () =>
    request<CertificateCheck[]>('/api/signing-material/verify'),

  profiles: () => request<ProfileView[]>('/api/profiles'),
  createProfile: (body: {
    name: string
    memory_id: string
    environment: string
    economic_code?: string | null
  }) => request<ProfileView>('/api/profiles', { method: 'POST', body: JSON.stringify(body) }),
  deleteProfile: (name: string) =>
    request<void>(`/api/profiles/${encode(name)}`, { method: 'DELETE' }),
  testConnection: (name: string) =>
    request<{
      profile: string
      environment: string
      baseUrl: string
      nonce: { ok: boolean; expDate?: string; error?: string }
      authenticated: { ok: boolean; serverKeys?: number; error?: string; codes?: string[] }
    }>(`/api/profiles/${encode(name)}/test-connection`, { method: 'POST' }),

  dashboard: (profile: string) => request<Dashboard>(`/api/profiles/${encode(profile)}/dashboard`),

  // Not under /api/profiles. Both catalogues are keyed on nationally issued
  // identifiers that mean the same thing in either environment, so they are
  // shared — and, more to the point, usable before a شناسه یکتای حافظه مالیاتی
  // has been obtained.
  buyers: () => request<Buyer[]>('/api/buyers'),
  addBuyer: (body: Partial<Buyer>) =>
    request<Buyer>('/api/buyers', { method: 'POST', body: JSON.stringify(body) }),
  deleteBuyer: (id: number) => request<void>(`/api/buyers/${id}`, { method: 'DELETE' }),

  goods: () => request<GoodsService[]>('/api/goods'),
  addGoods: (body: Partial<GoodsService>) =>
    request<GoodsService>('/api/goods', { method: 'POST', body: JSON.stringify(body) }),
  makeGoodsDefault: (id: number) =>
    request<{ ok: boolean }>(`/api/goods/${id}/default`, { method: 'POST' }),
  deleteGoods: (id: number) => request<void>(`/api/goods/${id}`, { method: 'DELETE' }),

  verify: (profile: string, invoice: InvoicePayload) =>
    request<VerifyResult>(`/api/profiles/${encode(profile)}/invoices/verify`, {
      method: 'POST',
      body: JSON.stringify({ invoice }),
    }),
  recompute: (profile: string, invoice: InvoicePayload) =>
    request<InvoicePayload>(`/api/profiles/${encode(profile)}/invoices/recompute`, {
      method: 'POST',
      body: JSON.stringify({ invoice }),
    }),
  saveDraft: (profile: string, invoice: InvoicePayload) =>
    request<{ id: number; state: string; verification: VerifyResult }>(
      `/api/profiles/${encode(profile)}/invoices`,
      { method: 'POST', body: JSON.stringify({ invoice }) },
    ),
  submit: (profile: string, invoice: InvoicePayload) =>
    request<SubmitResult>(`/api/profiles/${encode(profile)}/invoices/submit`, {
      method: 'POST',
      body: JSON.stringify({ invoice }),
    }),
  invoices: (profile: string, state?: string) =>
    request<InvoiceRecord[]>(
      `/api/profiles/${encode(profile)}/invoices${state ? `?state=${encode(state)}` : ''}`,
    ),
  /** استعلام for every invoice still awaiting a verdict, writing the result back. */
  inquirePending: (profile: string) =>
    request<InquiryOutcome>(`/api/profiles/${encode(profile)}/invoices/inquire`, {
      method: 'POST',
    }),
  inquireOne: (profile: string, id: number) =>
    request<InquiredRecord>(`/api/profiles/${encode(profile)}/invoices/${id}/inquire`, {
      method: 'POST',
    }),
  inquiryByReference: (profile: string, references: string[]) =>
    request<unknown[]>(
      `/api/profiles/${encode(profile)}/inquiry/by-reference?` +
        references.map((r) => `reference=${encode(r)}`).join('&'),
    ),
}

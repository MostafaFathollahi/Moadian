/** Thin fetch wrapper over the backend.
 *
 * Errors are surfaced with the server's own Persian message where there is one.
 * The backend already localises validation findings and maps the tax service's
 * error codes, so inventing a second set of messages here would only produce
 * two vocabularies for the same failure.
 */

import type {
  Buyer,
  Dashboard,
  EnvironmentInfo,
  GoodsService,
  InvoicePayload,
  InvoiceRecord,
  PatternFields,
  PatternInfo,
  ProfileView,
  SigningMaterial,
  SubmitResult,
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
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    throw new ApiError('ارتباط با سرور برقرار نشد.', 0, cause)
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) throw new ApiError(describe(response.status, body), response.status, body)
  return body as T
}

const encode = encodeURIComponent

export const api = {
  environments: () => request<EnvironmentInfo[]>('/api/environments'),
  patterns: () => request<PatternInfo[]>('/api/patterns'),
  patternFields: (pattern: number, type: number) =>
    request<PatternFields>(`/api/patterns/${pattern}/fields?type=${type}`),
  signingMaterial: () => request<SigningMaterial[]>('/api/signing-material'),

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

  buyers: (profile: string) => request<Buyer[]>(`/api/profiles/${encode(profile)}/buyers`),
  addBuyer: (profile: string, body: Partial<Buyer>) =>
    request<Buyer>(`/api/profiles/${encode(profile)}/buyers`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  deleteBuyer: (profile: string, id: number) =>
    request<void>(`/api/profiles/${encode(profile)}/buyers/${id}`, { method: 'DELETE' }),

  goods: (profile: string) => request<GoodsService[]>(`/api/profiles/${encode(profile)}/goods`),
  addGoods: (profile: string, body: Partial<GoodsService>) =>
    request<GoodsService>(`/api/profiles/${encode(profile)}/goods`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  makeGoodsDefault: (profile: string, id: number) =>
    request<{ ok: boolean }>(`/api/profiles/${encode(profile)}/goods/${id}/default`, {
      method: 'POST',
    }),
  deleteGoods: (profile: string, id: number) =>
    request<void>(`/api/profiles/${encode(profile)}/goods/${id}`, { method: 'DELETE' }),

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
  inquiryByReference: (profile: string, references: string[]) =>
    request<unknown[]>(
      `/api/profiles/${encode(profile)}/inquiry/by-reference?` +
        references.map((r) => `reference=${encode(r)}`).join('&'),
    ),
}

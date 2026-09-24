/** Shapes returned by the backend. Wire field names are kept verbatim.
 *
 * `taxid`, `indatim`, `tprdis` and the rest are the organization's names, not
 * ours. Renaming them for comfort here would mean a translation layer that is
 * invisible when it goes wrong — the invoice would be rejected by the tax
 * service with no clue why. They stay ugly on purpose.
 */

export interface UserInfo {
  id: number
  username: string
  display_name: string
  role: 'user' | 'admin'
  is_active: boolean
  created_at?: string | null
  disabled_at?: string | null
}

export type Obligation = 'required' | 'optional' | 'conditional' | 'not_applicable'

export interface EnvironmentInfo {
  value: 'sandbox' | 'production'
  label: string
  host: string
  baseUrl: string
  isProduction: boolean
}

export interface CertificateSummary {
  subject: string
  serial_number: string
  not_before: string
  not_after: string
  national_id: string | null
}

export interface ProfileView {
  name: string
  memory_id: string
  environment: 'sandbox' | 'production'
  environment_label: string
  is_production: boolean
  base_url: string
  economic_code: string | null
  certificate: CertificateSummary | null
  certificate_error?: string
}

export interface MaterialStatus {
  configured: boolean
  path: string | null
  exists: boolean
  mode: string | null
  worldReadable: boolean
  error: string | null
}

export interface SigningMaterial {
  environment: string
  certificate: MaterialStatus
  privateKey: MaterialStatus
  keyPassphraseSet: boolean
}

export interface CertificateDetail {
  subject: string
  issuer: string
  serialNumber: string
  notBefore: string
  notAfter: string
  /** شناسه ملی, from the subject SERIALNUMBER. */
  nationalId: string | null
  keySize: number
  publicKeyFingerprint: string
}

/** The answer to "is this private key actually this certificate's key?".
 *
 * `matches` is three-valued on purpose. `false` means the pair was compared and
 * is wrong; `null` means it could not be compared at all — usually a key that is
 * encrypted with no passphrase configured — and those call for different fixes.
 */
export interface CertificateCheck {
  environment: string
  environmentLabel: string
  certificatePath: string | null
  privateKeyPath: string | null
  keyPassphraseSet: boolean
  ok: boolean
  matches: boolean | null
  certificate: CertificateDetail | null
  message: string
}

export interface PatternInfo {
  number: number
  name: string
  nameEn: string
  types: number[]
  coverage: string
}

export interface FieldRule {
  field: string
  title: string
  obligation: Obligation
  condition: string | null
  reference: string
}

export interface PatternFields {
  pattern: number
  name: string
  type: number
  sections: { header: FieldRule[]; body: FieldRule[]; payment: FieldRule[] }
}

export interface Buyer {
  id: number
  name: string
  national_id: string
  economic_code: string | null
  person_type: number
  postal_code: string | null
  branch_code: string | null
  note: string | null
}

export interface GoodsService {
  id: number
  stuff_id: string
  description: string
  unit: string | null
  vat_rate: number | null
  default_fee: number | null
  is_default: boolean
}

/** A verification finding, already localised by the backend. */
export interface VerifyIssue {
  field: string
  title: string
  line: number | null
  rule: string
  message: string
  reference: string
  expected: number | null
  actual: number | null
}

export interface VerifyResult {
  ok: boolean
  summary: string
  pattern: number | null
  patternName: string
  errors: VerifyIssue[]
  warnings: VerifyIssue[]
  /** The organization's answer, once استعلام has been run. Absent until then. */
  inquiry?: InquiryDetail
  /** Set on an invoice a confirmed ابطالی voided. */
  cancelledBy?: { id: number; taxId: string | null; at: string }
}

/** One error code from the tax service. Not a VerifyIssue: this one carries no
 *  field, no clause citation and no expected/actual — only the code and text
 *  the organization returned. */
export interface TaxIssue {
  code: string
  message: string
  errorType?: string | null
}

export interface InquiryDetail {
  status: RequestStatus | string | null
  checkedAt: string
  referenceNumber: string | null
  uid: string | null
  errors: TaxIssue[]
  warnings: TaxIssue[]
}

export type RequestStatus =
  | 'IN_PROGRESS'
  | 'SUCCESS'
  | 'FAILED'
  | 'TIMEOUT'
  | 'NOT_FOUND'

export interface InquiredRecord {
  id: number
  taxId: string | null
  referenceNumber: string | null
  previousState: InvoiceState
  state: InvoiceState
  inquiry: InquiryDetail
  cancelledTaxId: string | null
}

export interface InquiryOutcome {
  checked: number
  updated: number
  records: InquiredRecord[]
}

export type InvoiceState =
  | 'draft'
  | 'invalid'
  | 'sent'
  | 'confirmed'
  | 'rejected'
  | 'cancelled'

export interface InvoiceRecord {
  id: number
  profile: string
  state: InvoiceState
  tax_id: string | null
  uid: string | null
  reference_number: string | null
  payload: InvoicePayload
  detail: VerifyResult | null
  created_at: string
  updated_at: string
}

export interface Dashboard {
  profile: ProfileView
  counts: Record<InvoiceState | 'total', number>
  recent: InvoiceRecord[]
}

export interface InvoiceLine {
  sstid?: string
  sstt?: string
  mu?: string
  am?: number
  fee?: number
  prdis?: number
  dis?: number
  adis?: number
  vra?: number
  vam?: number
  odam?: number
  olam?: number
  tsstam?: number
  [key: string]: unknown
}

export interface InvoiceHeader {
  taxid?: string
  indatim?: number
  indati2m?: number
  inty?: number
  inno?: string
  irtaxid?: string
  inp?: number
  ins?: number
  tins?: string
  tob?: number
  bid?: string
  tinb?: string
  bpc?: string
  tprdis?: number
  tdis?: number
  tadis?: number
  tvam?: number
  todam?: number
  tbill?: number
  setm?: number
  cap?: number
  insp?: number
  [key: string]: unknown
}

export interface InvoicePayload {
  header: InvoiceHeader
  body: InvoiceLine[]
  payments?: unknown[]
}

export interface SubmitResult {
  id: number
  state: InvoiceState
  taxId: string | null
  uid: string | null
  referenceNumber: string | null
}

/** One row of the organization's published شناسه کالا/خدمت list.
 *
 * Distinct from [GoodsService], which is the operator's own shortlist. This is
 * reference data we only ever read; that is a favourite they curated. */
export interface CatalogueEntry {
  stuffId: string
  description: string
  vatRate: number | null
  /** مشمول | معاف | غیر مشمول */
  taxable: string | null
  /** Jalali, as the organization exported it — not converted. */
  runDate: string | null
  expirationDate: string | null
  kind: string | null
  pricing: string | null
  isCurrent: boolean
}

export interface CatalogueStatus {
  total: number
  current: number
  superseded: number
  importedAt: string | null
  source: string | null
  /** No catalogue imported yet. The UI must say so rather than show "no
   *  results", which reads as a broken search. */
  empty: boolean
}

export interface CatalogueItem {
  current: CatalogueEntry | null
  /** Every VAT rate this code has carried, newest first. */
  history: CatalogueEntry[]
}

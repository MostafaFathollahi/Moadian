import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type {
  Buyer,
  CatalogueStatus,
  FieldRule,
  GoodsService,
  InvoiceLine,
  InvoicePayload,
  PatternFields,
  PatternInfo,
  ProfileView,
  VerifyResult,
} from '../../api/types'
import { Banner, Card, Field, money } from '../../components/common'
import { StuffPicker } from '../catalogue/StuffPicker'
import { IssueList } from './IssueList'

/** Blank line. Only the fields an operator types — everything derived comes
 *  back from the server's recompute, which owns the §8 formulas. */
const BLANK_LINE: InvoiceLine = { sstid: '', sstt: '', mu: '', am: 1, fee: 0, dis: 0, vra: 9 }

function emptyInvoice(): InvoicePayload {
  return {
    header: { inty: 1, inp: 1, ins: 1, setm: 2, indatim: Date.now() },
    body: [{ ...BLANK_LINE }],
    payments: [],
  }
}

export function InvoiceEntry({ profile }: { profile: ProfileView }) {
  const [invoice, setInvoice] = useState<InvoicePayload>(emptyInvoice)
  const [patterns, setPatterns] = useState<PatternInfo[]>([])
  const [rules, setRules] = useState<PatternFields | null>(null)
  const [buyers, setBuyers] = useState<Buyer[]>([])
  const [goods, setGoods] = useState<GoodsService[]>([])
  const [catalogue, setCatalogue] = useState<CatalogueStatus | null>(null)
  const [verification, setVerification] = useState<VerifyResult | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'err' | 'info'; text: string } | null>(null)

  const pattern = invoice.header.inp ?? 1
  const invoiceType = invoice.header.inty ?? 1

  useEffect(() => {
    void api.patterns().then(setPatterns).catch(() => undefined)
  }, [])

  // Both catalogues are shared across fiscal memories, so this does not depend
  // on the selected profile and does not reload when it changes.
  useEffect(() => {
    void api.buyers().then(setBuyers).catch(() => undefined)
    void api.goods().then(setGoods).catch(() => undefined)
    // Status, not results: without it an un-imported catalogue looks
    // identical to a search that matched nothing.
    void api.catalogueStatus().then(setCatalogue).catch(() => undefined)
  }, [])

  // Requiredness comes from جدول ۱ via the API, never from hard-coded rules
  // here — a correction to the matrix changes this form with no release.
  useEffect(() => {
    setRules(null)
    void api.patternFields(pattern, invoiceType).then(setRules).catch(() => setRules(null))
  }, [pattern, invoiceType])

  // A goods catalogue entry marked default pre-fills the first line.
  useEffect(() => {
    const fallback = goods.find((g) => g.is_default)
    if (!fallback) return
    setInvoice((current) => {
      const first = current.body[0]
      if (!first || first.sstid) return current
      const body = [...current.body]
      body[0] = {
        ...first,
        sstid: fallback.stuff_id,
        sstt: fallback.description,
        mu: fallback.unit ?? '',
        vra: fallback.vat_rate ?? first.vra,
        fee: fallback.default_fee ?? first.fee,
      }
      return { ...current, body }
    })
  }, [goods])

  const ruleFor = useCallback(
    (section: 'header' | 'body', field: string): FieldRule | undefined =>
      rules?.sections[section].find((r) => r.field === field),
    [rules],
  )

  /** Errors keyed by field, so an input can highlight itself. */
  const issuesByField = useMemo(() => {
    const map = new Map<string, string>()
    for (const issue of verification?.errors ?? []) {
      const key = issue.line === null ? issue.field : `${issue.field}#${issue.line}`
      if (!map.has(key)) map.set(key, issue.message)
    }
    return map
  }, [verification])

  function patch(header: Partial<InvoicePayload['header']>) {
    setInvoice((current) => ({ ...current, header: { ...current.header, ...header } }))
    setVerification(null)
  }

  function patchLine(index: number, changes: Partial<InvoiceLine>) {
    setInvoice((current) => {
      const body = [...current.body]
      body[index] = { ...body[index], ...changes }
      return { ...current, body }
    })
    setVerification(null)
  }

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label)
    setMessage(null)
    try {
      await action()
    } catch (cause) {
      setMessage({ kind: 'err', text: cause instanceof ApiError ? cause.message : String(cause) })
    } finally {
      setBusy(null)
    }
  }

  const calculate = () =>
    run('calc', async () => {
      const filled = await api.recompute(profile.name, invoice)
      setInvoice(filled)
      setVerification(null)
      setMessage({ kind: 'info', text: 'مبالغ بر اساس قواعد محاسبه شد.' })
    })

  const verify = () =>
    run('verify', async () => {
      const result = await api.verify(profile.name, invoice)
      setVerification(result)
      setMessage(
        result.ok
          ? { kind: 'ok', text: result.summary }
          : { kind: 'err', text: result.summary },
      )
    })

  const saveDraft = () =>
    run('save', async () => {
      const saved = await api.saveDraft(profile.name, invoice)
      setVerification(saved.verification)
      setMessage({ kind: 'ok', text: `پیش‌نویس ذخیره شد (شناسه ${saved.id}).` })
    })

  const submit = () =>
    run('submit', async () => {
      const result = await api.submit(profile.name, invoice)
      setMessage({
        kind: 'ok',
        text: `ارسال شد. شماره پیگیری ${result.referenceNumber ?? '—'} · شماره مالیاتی ${result.taxId ?? '—'}`,
      })
      setInvoice(emptyInvoice())
      setVerification(null)
    })

  const totals = invoice.header

  return (
    <>
      <div className="page-head">
        <div>
          <h1>صدور صورتحساب</h1>
          <p>
            {profile.environment_label} · شناسه یکتا{' '}
            <span className="ltr">{profile.memory_id}</span>
            {rules && ` · الگوی ${rules.name}`}
          </p>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={calculate} disabled={busy !== null}>
            {busy === 'calc' ? '…' : 'محاسبه مبالغ'}
          </button>
          <button className="btn" onClick={verify} disabled={busy !== null}>
            {busy === 'verify' ? '…' : 'اعتبارسنجی'}
          </button>
          <button className="btn" onClick={saveDraft} disabled={busy !== null}>
            ذخیره پیش‌نویس
          </button>
          <button
            className="btn primary"
            onClick={submit}
            disabled={busy !== null || verification?.ok !== true}
            title={
              verification?.ok
                ? 'ارسال به سامانه مودیان'
                : 'ابتدا اعتبارسنجی کنید؛ ارسال صورتحساب نامعتبر شماره مالیاتی را هدر می‌دهد.'
            }
          >
            {busy === 'submit' ? '…' : 'ارسال به سامانه'}
          </button>
        </div>
      </div>

      {message && <Banner kind={message.kind}>{message.text}</Banner>}

      {verification && (verification.errors.length > 0 || verification.warnings.length > 0) && (
        <Card title="نتیجه اعتبارسنجی">
          <IssueList result={verification} />
        </Card>
      )}

      <div className="grid cols-2">
        <Card title="سرآمد صورتحساب">
          <Field label="الگوی صورتحساب" required>
            <select value={pattern} onChange={(e) => patch({ inp: Number(e.target.value) })}>
              {patterns.map((p) => (
                <option key={p.number} value={p.number}>
                  {p.number} — {p.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="نوع صورتحساب" required>
            <select value={invoiceType} onChange={(e) => patch({ inty: Number(e.target.value) })}>
              <option value={1}>نوع اول</option>
              <option value={2}>نوع دوم</option>
            </select>
          </Field>

          <Field label="موضوع صورتحساب" required>
            <select value={invoice.header.ins ?? 1} onChange={(e) => patch({ ins: Number(e.target.value) })}>
              <option value={1}>اصلی</option>
              <option value={2}>اصلاحی</option>
              <option value={3}>ابطالی</option>
              <option value={4}>برگشت از فروش</option>
            </select>
          </Field>

          {/* Conditional per §5 — only a referring invoice needs a reference. */}
          {[2, 3, 4].includes(invoice.header.ins ?? 1) && (
            <Field
              label="شماره مالیاتی صورتحساب مرجع"
              conditional
              error={issuesByField.get('irtaxid')}
            >
              <input
                className="ltr"
                value={invoice.header.irtaxid ?? ''}
                onChange={(e) => patch({ irtaxid: e.target.value })}
              />
            </Field>
          )}

          <Field
            label="شماره اقتصادی فروشنده"
            required={ruleFor('header', 'tins')?.obligation === 'required'}
            error={issuesByField.get('tins')}
            hint={
              profile.certificate?.national_id
                ? `کد ملی گواهی: ${profile.certificate.national_id}`
                : undefined
            }
          >
            <input
              className="ltr"
              value={invoice.header.tins ?? ''}
              onChange={(e) => patch({ tins: e.target.value })}
            />
          </Field>

          <Field label="خریدار" error={issuesByField.get('tinb')}>
            <select
              value={invoice.header.bid ?? ''}
              onChange={(e) => {
                const buyer = buyers.find((b) => b.national_id === e.target.value)
                patch(
                  buyer
                    ? {
                        bid: buyer.national_id,
                        tinb: buyer.economic_code ?? buyer.national_id,
                        tob: buyer.person_type,
                        bpc: buyer.postal_code ?? undefined,
                      }
                    : { bid: undefined, tinb: undefined },
                )
              }}
            >
              <option value="">— انتخاب کنید —</option>
              {buyers.map((b) => (
                <option key={b.id} value={b.national_id}>
                  {b.name} ({b.national_id})
                </option>
              ))}
            </select>
          </Field>

          <Field
            label="نوع شخص خریدار"
            required={ruleFor('header', 'tob')?.obligation === 'required'}
            error={issuesByField.get('tob')}
          >
            <select value={invoice.header.tob ?? 2} onChange={(e) => patch({ tob: Number(e.target.value) })}>
              <option value={1}>حقیقی</option>
              <option value={2}>حقوقی</option>
              <option value={3}>مشارکت مدنی</option>
              <option value={4}>اتباع غیرایرانی</option>
              <option value={5}>مصرف‌کننده نهایی</option>
            </select>
          </Field>

          <Field label="روش تسویه" required={ruleFor('header', 'setm')?.obligation === 'required'}
                 error={issuesByField.get('setm')}>
            <select value={invoice.header.setm ?? 2} onChange={(e) => patch({ setm: Number(e.target.value) })}>
              <option value={1}>نقدی</option>
              <option value={2}>نسیه</option>
              <option value={3}>نقدی/نسیه</option>
            </select>
          </Field>

          {invoice.header.setm === 3 && (
            <div className="grid cols-2">
              <Field label="مبلغ پرداختی نقدی" conditional error={issuesByField.get('cap')}>
                <input
                  type="number"
                  value={invoice.header.cap ?? ''}
                  onChange={(e) => patch({ cap: Number(e.target.value) })}
                />
              </Field>
              <Field label="مبلغ نسیه" conditional error={issuesByField.get('insp')}>
                <input
                  type="number"
                  value={invoice.header.insp ?? ''}
                  onChange={(e) => patch({ insp: Number(e.target.value) })}
                />
              </Field>
            </div>
          )}
        </Card>

        <Card title="جمع‌بندی">
          <p className="small muted">
            این مقادیر با «محاسبه مبالغ» از روی اقلام پر می‌شوند. مقدار دستی هم پذیرفته
            می‌شود، ولی اعتبارسنجی آن را با فرمول‌های بخش ۸ می‌سنجد.
          </p>
          <table>
            <tbody>
              <Total label="مجموع قبل از تخفیف" value={totals.tprdis} field="tprdis" issues={issuesByField} />
              <Total label="مجموع تخفیفات" value={totals.tdis} field="tdis" issues={issuesByField} />
              <Total label="مجموع پس از تخفیف" value={totals.tadis} field="tadis" issues={issuesByField} />
              <Total label="مجموع مالیات بر ارزش افزوده" value={totals.tvam} field="tvam" issues={issuesByField} />
              <Total label="سایر مالیات و عوارض" value={totals.todam} field="todam" issues={issuesByField} />
              <Total label="مجموع صورتحساب" value={totals.tbill} field="tbill" issues={issuesByField} strong />
            </tbody>
          </table>
        </Card>
      </div>

      <Card
        title="اقلام کالا و خدمت"
        actions={
          <button
            className="btn"
            onClick={() => setInvoice((c) => ({ ...c, body: [...c.body, { ...BLANK_LINE }] }))}
          >
            افزودن قلم
          </button>
        }
      >
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>شناسه کالا/خدمت</th>
                <th>شرح</th>
                <th>واحد</th>
                <th className="numeric">تعداد</th>
                <th className="numeric">مبلغ واحد</th>
                <th className="numeric">تخفیف</th>
                <th className="numeric">نرخ %</th>
                <th className="numeric">مبلغ کل</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {invoice.body.map((line, index) => (
                <tr key={index}>
                  <td>
                    <StuffPicker
                      value={line.sstid ?? ''}
                      favourites={goods}
                      catalogueEmpty={catalogue?.empty}
                      invalid={issuesByField.has(`sstid#${index}`)}
                      onPick={(pick) =>
                        patchLine(index, {
                          sstid: pick.stuffId,
                          sstt: pick.description,
                          // A catalogue row carries no unit or price — only the
                          // operator's own entry does — so those hold whatever
                          // the line already had rather than being cleared.
                          mu: pick.unit ?? line.mu ?? '',
                          vra: pick.vatRate ?? line.vra,
                          fee: pick.fee ?? line.fee,
                        })
                      }
                      onRaw={(text) => patchLine(index, { sstid: text })}
                    />
                  </td>
                  <td>
                    <input
                      value={line.sstt ?? ''}
                      onChange={(e) => patchLine(index, { sstt: e.target.value })}
                      style={{ minWidth: 150 }}
                    />
                  </td>
                  <td>
                    <input
                      value={line.mu ?? ''}
                      onChange={(e) => patchLine(index, { mu: e.target.value })}
                      style={{ width: 70 }}
                    />
                  </td>
                  <NumberCell value={line.am} onChange={(v) => patchLine(index, { am: v })} />
                  <NumberCell value={line.fee} onChange={(v) => patchLine(index, { fee: v })} />
                  <NumberCell value={line.dis} onChange={(v) => patchLine(index, { dis: v })} />
                  <NumberCell value={line.vra} onChange={(v) => patchLine(index, { vra: v })} width={60} />
                  <td className="numeric">{money(line.tsstam)}</td>
                  <td>
                    <button
                      className="btn ghost"
                      disabled={invoice.body.length === 1}
                      onClick={() =>
                        setInvoice((c) => ({ ...c, body: c.body.filter((_, i) => i !== index) }))
                      }
                    >
                      حذف
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

function NumberCell({
  value, onChange, width = 90,
}: {
  value: number | undefined
  onChange: (value: number) => void
  width?: number
}) {
  return (
    <td className="numeric">
      <input
        type="number"
        value={value ?? ''}
        onChange={(event) => onChange(Number(event.target.value))}
        style={{ width, textAlign: 'end' }}
      />
    </td>
  )
}

function Total({
  label, value, field, issues, strong,
}: {
  label: string
  value: number | undefined
  field: string
  issues: Map<string, string>
  strong?: boolean
}) {
  const error = issues.get(field)
  return (
    <tr>
      <td style={{ fontWeight: strong ? 700 : undefined }}>
        {label}
        {error && <div className="err small">{error}</div>}
      </td>
      <td
        className="numeric"
        style={{ fontWeight: strong ? 700 : undefined, color: error ? 'var(--danger)' : undefined }}
      >
        {money(value)}
      </td>
    </tr>
  )
}

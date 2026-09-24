import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  UnitTable,
  VerifyResult,
} from '../../api/types'
import { Banner, Card, Field, money } from '../../components/common'
import { StuffPicker } from '../catalogue/StuffPicker'
import { IssueList } from './IssueList'

/** Blank line. Only the fields an operator types — everything derived comes
 *  back from the server's recompute, which owns the §8 formulas. */
/** شرح کالا/خدمت, RC_IITP §8-28، جدول ۳۰. The field is optional free text and
 *  the spec records no content rule for it; length is the only constraint. */
const MAX_SSTT = 400

/** کد واحد «عدد». Most things on an invoice are counted rather than weighed, and
 *  a blank mu is what earned a real invoice error 0103502 — the field is optional
 *  but an empty string is not a code. The server is the authority on the table
 *  (GET /api/units); this is the fallback if that call has not landed yet. */
const DEFAULT_UNIT = '1627'

const BLANK_LINE: InvoiceLine = {
  sstid: '', sstt: '', mu: DEFAULT_UNIT, am: 1, fee: 0, dis: 0, vra: 9,
}

function emptyInvoice(): InvoicePayload {
  return {
    // setm 1 = نقدی. The common case by a wide margin, and 3 (نقدی/نسیه) is the
  // only value that demands extra fields, so it should never be the default.
  // indatim  تاریخ و زمان صدور — editable, and the one the tax id's day range
  //          is derived from (in Asia/Tehran, server side).
  // indati2m تاریخ و زمان ایجاد — when this draft was started. Stamped once and
  //          never touched again, which is the whole point of recording it.
  header: { inty: 1, inp: 1, ins: 1, setm: 1, indatim: Date.now(), indati2m: Date.now() },
    body: [{ ...BLANK_LINE }],
    payments: [],
  }
}

export function InvoiceEntry({
  profile,
  draftId,
  onDraftOpened,
}: {
  profile: ProfileView
  /** A stored draft to reopen, from پیگیری ارسال‌ها. */
  draftId?: number | null
  /** Told which record is being edited — null once it is submitted or cleared —
   *  so the caller does not reopen the same draft on every visit. */
  onDraftOpened?: (id: number | null) => void
}) {
  const [invoice, setInvoice] = useState<InvoicePayload>(emptyInvoice)
  // Which stored record this form is editing. Set, ذخیره overwrites it instead
  // of saving yet another near-identical copy.
  const [editing, setEditing] = useState<number | null>(draftId ?? null)
  const [patterns, setPatterns] = useState<PatternInfo[]>([])
  const [rules, setRules] = useState<PatternFields | null>(null)
  const [buyers, setBuyers] = useState<Buyer[]>([])
  const [goods, setGoods] = useState<GoodsService[]>([])
  const [catalogue, setCatalogue] = useState<CatalogueStatus | null>(null)
  const [units, setUnits] = useState<UnitTable | null>(null)
  const [verification, setVerification] = useState<VerifyResult | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<{ kind: 'ok' | 'err' | 'info'; text: string } | null>(null)

  const unitByCode = useMemo(
    () => new Map((units?.units ?? []).map((u) => [u.code, u.name])),
    [units],
  )

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
    void api.units().then(setUnits).catch(() => undefined)
  }, [])

  // Reopening a stored draft. The id stays set while it is being edited, so
  // leaving this page and coming back returns to the same draft rather than a
  // blank form; صورتحساب جدید is what lets go of it.
  useEffect(() => {
    if (!draftId) return
    setEditing(draftId)
    api
      .invoice(profile.name, draftId)
      .then((record) => {
        setInvoice(record.payload)
        setVerification(record.detail ?? null)
        setMessage({ kind: 'info', text: `پیش‌نویس ${draftId} برای ویرایش باز شد.` })
      })
      .catch((cause) =>
        setMessage({
          kind: 'err',
          text: cause instanceof ApiError ? cause.message : String(cause),
        }),
      )
  }, [draftId, profile.name])

  // Requiredness comes from جدول ۱ via the API, never from hard-coded rules
  // here — a correction to the matrix changes this form with no release.
  useEffect(() => {
    setRules(null)
    void api.patternFields(pattern, invoiceType).then(setRules).catch(() => setRules(null))
  }, [pattern, invoiceType])

  // The server owns the unit table, including which code is the default. A line
  // still carrying the compiled-in fallback is moved onto the server's answer, so
  // the two cannot drift apart across a table revision.
  useEffect(() => {
    const preferred = units?.default
    if (!preferred || preferred === DEFAULT_UNIT) return
    setInvoice((current) => ({
      ...current,
      body: current.body.map((line) =>
        line.mu === DEFAULT_UNIT ? { ...line, mu: preferred } : line,
      ),
    }))
  }, [units?.default])

  // شماره اقتصادی فروشنده comes from the certificate that will sign the invoice.
  //
  // It is not really a free field: the organization checks that the seller's
  // شماره اقتصادی matches the identity in the signing certificate, so any value
  // other than the one in the certificate is a rejection. The certificate's
  // subject serialNumber (2.5.4.5) is that identity, and the profile's own
  // economic_code stands in when the certificate cannot be read — a profile
  // whose certificate has gone missing must still let an invoice be drafted.
  //
  // Only ever fills a blank. Typing over it is allowed, because a taxpayer
  // filing on behalf of another has a reason to.
  useEffect(() => {
    const fromCertificate = profile.certificate?.national_id ?? profile.economic_code
    if (!fromCertificate) return
    setInvoice((current) =>
      current.header.tins
        ? current
        : { ...current, header: { ...current.header, tins: fromCertificate } },
    )
  }, [profile.certificate?.national_id, profile.economic_code])

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
        sstt: fallback.description.slice(0, MAX_SSTT),
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
      // Overwrite when a stored record is open; insert only for a new invoice.
      // Always inserting is what left the list full of near-duplicate drafts
      // with no way to tell which one was current.
      const saved = editing
        ? await api.updateDraft(profile.name, editing, invoice)
        : await api.saveDraft(profile.name, invoice)
      setEditing(saved.id)
      onDraftOpened?.(saved.id)
      setVerification(saved.verification)
      setMessage({
        kind: 'ok',
        text: editing
          ? `پیش‌نویس ${saved.id} به‌روزرسانی شد.`
          : `پیش‌نویس ذخیره شد (شناسه ${saved.id}).`,
      })
    })

  const startNew = () => {
    setInvoice(emptyInvoice())
    setEditing(null)
    onDraftOpened?.(null)
    setVerification(null)
    setMessage(null)
  }

  const submit = () =>
    run('submit', async () => {
      // Pass the open draft, so submitting it moves that row to ارسال‌شده
      // rather than leaving it behind as a taxid-less copy of what was sent.
      const result = await api.submit(profile.name, invoice, editing)
      setMessage({
        kind: 'ok',
        text: `ارسال شد. شماره پیگیری ${result.referenceNumber ?? '—'} · شماره مالیاتی ${result.taxId ?? '—'}`,
      })
      setInvoice(emptyInvoice())
      // The record it came from is SENT now, and a sent invoice is not editable.
      setEditing(null)
      onDraftOpened?.(null)
      setVerification(null)
    })

  const totals = invoice.header

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{editing ? `ویرایش پیش‌نویس ${editing.toLocaleString('fa-IR')}` : 'صدور صورتحساب'}</h1>
          <p>
            {profile.environment_label} · شناسه یکتا{' '}
            <span className="ltr">{profile.memory_id}</span>
            {rules && ` · الگوی ${rules.name}`}
            {/* Said plainly, because ذخیره behaves differently in the two cases
                and the difference is otherwise invisible until the list grows a
                duplicate. */}
            {editing && ' · ذخیره همین پیش‌نویس را به‌روز می‌کند'}
          </p>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={calculate} disabled={busy !== null}>
            {busy === 'calc' ? '…' : 'محاسبه مبالغ'}
          </button>
          <button className="btn" onClick={verify} disabled={busy !== null}>
            {busy === 'verify' ? '…' : 'اعتبارسنجی'}
          </button>
          {editing !== null && (
            <button className="btn ghost" onClick={startNew} disabled={busy !== null}>
              صورتحساب جدید
            </button>
          )}
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
          {/* Read-only, and shown precisely because it is not yours to fill.
              The شماره منحصر به فرد مالیاتی encodes the fiscal memory, the issue
              date and a serial that must never repeat, so it is derived from the
              persisted counter at the moment of sending. An empty box here is
              the correct state for an invoice that has not been sent, and saying
              so beats leaving the field out and having the operator wonder where
              the number went. */}
          <Field
            label="شماره منحصر به فرد مالیاتی"
            hint={
              invoice.header.taxid
                ? 'در زمان ارسال توسط برنامه ساخته شد.'
                : 'هنگام ارسال به‌طور خودکار ساخته می‌شود؛ قابل ویرایش نیست.'
            }
          >
            <input
              className="ltr"
              value={invoice.header.taxid ?? ''}
              readOnly
              tabIndex={-1}
              placeholder="— هنگام ارسال ساخته می‌شود —"
              style={{ background: 'var(--surface-2)', color: 'var(--muted)' }}
            />
          </Field>

          {/* Read-only for the same reason the taxid is: inno is the same serial
              rendered as 10 hex digits, drawn from the same persisted counter at
              the same moment. Typing one here would either duplicate a serial or
              disagree with the taxid that embeds it. */}
          <Field
            label="سریال صورتحساب"
            hint="سریال داخلی حافظه مالیاتی — همان سریالی که در شماره مالیاتی به کار می‌رود."
          >
            <input
              className="ltr"
              value={invoice.header.inno ?? ''}
              readOnly
              tabIndex={-1}
              placeholder="— هنگام ارسال ساخته می‌شود —"
              style={{ background: 'var(--surface-2)', color: 'var(--muted)' }}
            />
          </Field>

          <div className="grid cols-2">
            <Field
              label="تاریخ صدور صورتحساب"
              required
              error={issuesByField.get('indatim')}
              hint={jalali(invoice.header.indatim)}
            >
              <input
                type="date"
                className="ltr"
                value={toDateInput(invoice.header.indatim)}
                onChange={(e) => patch({ indatim: fromDateInput(e.target.value, invoice.header.indatim) })}
              />
            </Field>

            <Field label="تاریخ ایجاد" hint={jalali(invoice.header.indati2m)}>
              <input
                className="ltr"
                value={toDateInput(invoice.header.indati2m)}
                readOnly
                tabIndex={-1}
                style={{ background: 'var(--surface-2)', color: 'var(--muted)' }}
              />
            </Field>
          </div>

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
            <select value={invoice.header.setm ?? 1} onChange={(e) => patch({ setm: Number(e.target.value) })}>
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
                          // Capped: شرح کالا/خدمت is limited to 400 characters
                          // (RC_IITP §8-28) and 13 current catalogue entries run
                          // past it, the longest at 625. Filling the line
                          // unmodified would build an invoice the organization
                          // refuses. Trimmed rather than refused, because the
                          // first 400 characters of a classification path are
                          // still the useful part and the operator edits it
                          // anyway.
                          sstt: pick.description.slice(0, MAX_SSTT),
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
                      maxLength={MAX_SSTT}
                      title={`شرح کالا/خدمت — حداکثر ${MAX_SSTT} نویسه`}
                      onChange={(e) => patchLine(index, { sstt: e.target.value })}
                      // Filled in from whichever list the code was picked from,
                      // and editable after: the catalogue's شرح is often a long
                      // classification path where the invoice wants the plain
                      // name of what was sold.
                      style={{ minWidth: 220 }}
                    />
                  </td>
                  <td>
                    {/* A select, not a text box: the codes are opaque numbers and
                        an operator should not have to know that 1627 is عدد. A
                        code outside the table is error 0103502, so picking from
                        the list is the only reliable way to fill it.
                        "بدون واحد" is offered because §8-30 makes mu اختیاری and
                        a blank is dropped from the payload rather than sent. */}
                    <select
                      value={line.mu ?? ''}
                      onChange={(e) => patchLine(index, { mu: e.target.value })}
                      style={{
                        minWidth: 120,
                        borderColor: issuesByField.has(`mu#${index}`) ? 'var(--danger)' : undefined,
                      }}
                    >
                      <option value="">— بدون واحد —</option>
                      {/* A code already on the invoice that this snapshot of the
                          table does not contain still has to be selectable, or
                          reopening such a draft would silently change it. */}
                      {line.mu && !unitByCode.has(line.mu) && (
                        <option value={line.mu}>{line.mu} (ناشناخته)</option>
                      )}
                      {(units?.units ?? []).map((u) => (
                        <option key={u.code} value={u.code}>
                          {u.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <NumberCell value={line.am} onChange={(v) => patchLine(index, { am: v })} />
                  <MoneyCell value={line.fee} onChange={(v) => patchLine(index, { fee: v })} />
                  <MoneyCell value={line.dis} onChange={(v) => patchLine(index, { dis: v })} />
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

/** An amount in rials, grouped as you type.
 *
 * `type="number"` cannot do this — a browser will not render a separator inside
 * one — and an ungrouped rial figure is genuinely hard to read: 21255000 and
 * 2125500 differ by a factor of ten and by one character. Invoice amounts here
 * run to eight and nine digits, so the grouping is not decoration.
 *
 * Text rather than number, therefore, with the separators inserted on every
 * keystroke and the caret put back where it belongs — counting digits rather
 * than characters, because reformatting moves every separator and a caret
 * restored by character index walks backwards through the number as it grows.
 *
 * Persian and Arabic-Indic digits are accepted: the amount is often pasted or
 * typed on a Persian keyboard, and rejecting ۱۲۳ would be a validation failure
 * the operator cannot see.
 */
function MoneyCell({
  value, onChange, width = 110,
}: {
  value: number | undefined
  onChange: (value: number) => void
  width?: number
}) {
  const input = useRef<HTMLInputElement>(null)
  const [caret, setCaret] = useState<number | null>(null)

  const text = value === undefined || Number.isNaN(value) ? '' : group(value)

  // Laid in after render, because the value React paints is the reformatted one
  // and setting selectionStart before that paint is overwritten by it.
  useEffect(() => {
    if (caret === null || !input.current) return
    input.current.setSelectionRange(caret, caret)
    setCaret(null)
  }, [caret, text])

  return (
    <td className="numeric">
      <input
        ref={input}
        // A numeric keypad on a phone without the number-input behaviour that
        // would strip the separators.
        inputMode="numeric"
        className="ltr"
        value={text}
        onChange={(event) => {
          const raw = event.target.value
          const position = event.target.selectionStart ?? raw.length
          const digitsBefore = countDigits(raw.slice(0, position))
          const digits = toAscii(raw).replace(/[^\d]/g, '')
          onChange(digits === '' ? 0 : Number(digits))
          // Where the caret lands: after the same number of digits it was after
          // before, wherever the separators ended up.
          setCaret(offsetAfterDigits(group(digits === '' ? 0 : Number(digits)), digitsBefore))
        }}
        style={{ width, textAlign: 'end' }}
      />
    </td>
  )
}

/** Digit grouping, in the same Persian numerals the rest of the app reads in. */
function group(value: number): string {
  return value.toLocaleString('fa-IR', { useGrouping: true, maximumFractionDigits: 0 })
}

function toAscii(text: string): string {
  return text
    .replace(/[\u06f0-\u06f9]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
}

function countDigits(text: string): number {
  return toAscii(text).replace(/[^\d]/g, '').length
}

/** The offset in `text` that sits just after its `count`-th digit. */
function offsetAfterDigits(text: string, count: number): number {
  if (count <= 0) return 0
  let seen = 0
  const ascii = toAscii(text)
  for (let index = 0; index < ascii.length; index += 1) {
    if (/\d/.test(ascii[index])) {
      seen += 1
      if (seen === count) return index + 1
    }
  }
  return text.length
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


/** Epoch millis to the `YYYY-MM-DD` an `<input type="date">` wants.
 *
 * Built from the local calendar parts rather than `toISOString().slice(0, 10)`,
 * which converts to UTC first: an evening in Tehran is already the next day in
 * UTC, so the ISO shortcut shows the operator a date one off from the one they
 * picked — and that date is what the شماره منحصر به فرد مالیاتی encodes.
 */
function toDateInput(millis: number | undefined): string {
  if (!millis) return ''
  const when = new Date(millis)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`
}

/** A picked date back to epoch millis, keeping the time of day already on the
 *  invoice. The organization records a تاریخ و زمان, not a date, and discarding
 *  the clock to midnight would move every invoice to 00:00. */
function fromDateInput(text: string, previous: number | undefined): number {
  const [year, month, day] = text.split('-').map(Number)
  if (!year || !month || !day) return previous ?? Date.now()
  const base = new Date(previous ?? Date.now())
  base.setFullYear(year, month - 1, day)
  return base.getTime()
}

/** The Persian calendar reading of a timestamp, shown beside the picker.
 *
 * `<input type="date">` is Gregorian in every browser, and the operator thinks
 * in Jalali — so the picker takes one and the hint states the other, rather than
 * either one being left to be worked out. */
function jalali(millis: number | undefined): string {
  if (!millis) return ''
  return new Date(millis).toLocaleDateString('fa-IR', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  })
}

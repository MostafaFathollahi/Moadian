import { Fragment, useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { InquiryDetail, InvoiceRecord, ProfileView } from '../../api/types'
import { Banner, Card, Empty, money } from '../../components/common'
import { IssueList } from '../invoice/IssueList'
import { StateChip } from './StateChip'

/** Sent ≠ confirmed, so this is a screen rather than a toast.
 *
 * The organization validates asynchronously with a mandatory wait of at least
 * ten seconds, then a status that may sit at IN_PROGRESS for longer. An
 * operator needs somewhere to watch that, and somewhere to see the error codes
 * when it ends badly.
 *
 * Two different buttons, deliberately:
 *
 * * **به‌روزرسانی** re-reads what we already know. No network beyond our own API.
 * * **استعلام وضعیت** asks the *organization* and writes the answer back. That
 *   is the half of filing an invoice that submission does not do — a سند stays
 *   ارسال‌شده until this runs.
 */
export function SubmissionsPage({
  profile,
  onEdit,
}: {
  profile: ProfileView
  /** Reopen a draft in the entry form. Absent, the column is simply not shown. */
  onEdit?: (id: number) => void
}) {
  const [records, setRecords] = useState<InvoiceRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [filter, setFilter] = useState<string>('')
  const [inquiring, setInquiring] = useState(false)

  const load = useCallback(() => {
    setRecords(null)
    setError(null)
    api
      .invoices(profile.name, filter || undefined)
      .then(setRecords)
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : String(cause)))
  }, [profile.name, filter])

  useEffect(load, [load])

  const inquire = useCallback(async () => {
    setInquiring(true)
    setError(null)
    setNotice(null)
    try {
      const outcome = await api.inquirePending(profile.name)
      if (outcome.checked === 0) {
        setNotice('صورتحسابی در انتظار پاسخ سامانه نیست.')
      } else {
        // "Asked about" and "answered" are different numbers, and an operator
        // who sees only the first will read an unchanged screen as a failure.
        setNotice(
          `${outcome.checked.toLocaleString('fa-IR')} صورتحساب استعلام شد؛ ` +
            `${outcome.updated.toLocaleString('fa-IR')} مورد تعیین تکلیف شد. ` +
            (outcome.updated < outcome.checked
              ? 'بقیه هنوز در صف بررسی سامانه هستند.'
              : ''),
        )
      }
      load()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
    } finally {
      setInquiring(false)
    }
  }, [profile.name, load])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>پیگیری ارسال‌ها</h1>
          <p>وضعیت صورتحساب‌های این حافظه مالیاتی</p>
        </div>
        <div className="btn-row">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">همه وضعیت‌ها</option>
            <option value="draft">پیش‌نویس</option>
            <option value="invalid">دارای خطا</option>
            <option value="sent">ارسال‌شده</option>
            <option value="confirmed">ثبت‌شده</option>
            <option value="rejected">رد‌شده</option>
            <option value="cancelled">ابطال‌شده</option>
          </select>
          <button className="btn" onClick={load}>به‌روزرسانی</button>
          <button className="btn primary" onClick={inquire} disabled={inquiring}>
            {inquiring ? 'در حال استعلام…' : 'استعلام وضعیت'}
          </button>
        </div>
      </div>

      {error && <Banner kind="err">{error}</Banner>}
      {notice && <Banner kind="info">{notice}</Banner>}

      <Card>
        {!records ? (
          <Empty>در حال بارگذاری…</Empty>
        ) : records.length === 0 ? (
          <Empty>موردی یافت نشد.</Empty>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>وضعیت</th>
                  <th>شماره مالیاتی</th>
                  <th className="numeric">مبلغ</th>
                  <th>شماره پیگیری</th>
                  <th>شناسه درخواست</th>
                  <th>آخرین استعلام</th>
                  <th>تاریخ</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {records.map((record) => {
                  const inquiry = record.detail?.inquiry
                  const hasDetail =
                    !!record.detail &&
                    (record.detail.errors.length > 0 ||
                      record.detail.warnings.length > 0 ||
                      !!inquiry)
                  return (
                    <Fragment key={record.id}>
                      <tr>
                        <td><StateChip state={record.state} /></td>
                        <td className="ltr">{record.tax_id ?? '—'}</td>
                        <td className="numeric">{money(record.payload?.header?.tbill)}</td>
                        <td className="ltr">{record.reference_number ?? '—'}</td>
                        <td className="ltr small">{record.uid ?? '—'}</td>
                        <td className="small muted">
                          {inquiry ? <StatusText status={inquiry.status} /> : '—'}
                        </td>
                        <td className="small muted">
                          {new Date(record.created_at).toLocaleString('fa-IR')}
                        </td>
                        <td>
                          <div className="btn-row">
                            {/* Only a draft. A sent invoice's payload is the
                                record of what was actually signed, and the API
                                refuses to rewrite it — offering the button would
                                be a promise the server will not keep. */}
                            {onEdit && (record.state === 'draft' || record.state === 'invalid') && (
                              <button className="btn ghost" onClick={() => onEdit(record.id)}>
                                ویرایش
                              </button>
                            )}
                            {hasDetail && (
                              <button
                                className="btn ghost"
                                onClick={() =>
                                  setExpanded(expanded === record.id ? null : record.id)
                                }
                              >
                                {expanded === record.id ? 'بستن' : 'جزئیات'}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {expanded === record.id && record.detail && (
                        <tr>
                          <td colSpan={8} style={{ background: 'var(--surface-2)' }}>
                            {inquiry && <InquiryPanel inquiry={inquiry} />}
                            {(record.detail.errors.length > 0 ||
                              record.detail.warnings.length > 0) && (
                              <>
                                <h4 className="detail-head">اعتبارسنجی پیش از ارسال</h4>
                                <IssueList result={record.detail} />
                              </>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

const STATUS_TEXT: Record<string, string> = {
  IN_PROGRESS: 'در صف بررسی',
  SUCCESS: 'فاقد خطا',
  FAILED: 'دارای خطا',
  TIMEOUT: 'انقضای زمان بررسی',
  NOT_FOUND: 'یافت نشد',
}

function StatusText({ status }: { status: string | null }) {
  if (!status) return <>—</>
  return <>{STATUS_TEXT[status] ?? status}</>
}

/** What the organization said, kept apart from what we predicted.
 *
 * Its errors carry a code and a message and nothing else — no field, no clause
 * citation — so they cannot go through IssueList without inventing the parts
 * that are missing.
 */
function InquiryPanel({ inquiry }: { inquiry: InquiryDetail }) {
  return (
    <div className="inquiry-panel">
      <h4 className="detail-head">
        پاسخ سامانه — <StatusText status={inquiry.status} />
        <span className="muted small">
          {' '}(استعلام در {new Date(inquiry.checkedAt).toLocaleString('fa-IR')})
        </span>
      </h4>
      {inquiry.errors.length === 0 && inquiry.warnings.length === 0 ? (
        <p className="empty">
          {inquiry.status === 'SUCCESS'
            ? 'بدون خطا؛ در کارپوشه ثبت شد.'
            : 'سامانه هنوز جزئیاتی اعلام نکرده است.'}
        </p>
      ) : (
        <ul className="issue-list">
          {inquiry.errors.map((issue, index) => (
            <li className="issue" key={`e${index}`}>
              <span className="where ltr">{issue.code}</span>
              {': '}
              {issue.message}
            </li>
          ))}
          {inquiry.warnings.map((issue, index) => (
            <li className="issue warn" key={`w${index}`}>
              <span className="where ltr">{issue.code}</span>
              {': '}
              {issue.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

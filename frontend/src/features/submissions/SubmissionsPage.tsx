import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { InvoiceRecord, ProfileView } from '../../api/types'
import { Banner, Card, Empty, money } from '../../components/common'
import { IssueList } from '../invoice/IssueList'
import { StateChip } from './StateChip'

/** Sent ≠ confirmed, so this is a screen rather than a toast.
 *
 * The organization validates asynchronously with a mandatory wait of at least
 * ten seconds, then a status that may sit at IN_PROGRESS for longer. An
 * operator needs somewhere to watch that, and somewhere to see the error codes
 * when it ends badly.
 */
export function SubmissionsPage({ profile }: { profile: ProfileView }) {
  const [records, setRecords] = useState<InvoiceRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [filter, setFilter] = useState<string>('')

  const load = useCallback(() => {
    setRecords(null)
    api
      .invoices(profile.name, filter || undefined)
      .then(setRecords)
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : String(cause)))
  }, [profile.name, filter])

  useEffect(load, [load])

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
          </select>
          <button className="btn" onClick={load}>به‌روزرسانی</button>
        </div>
      </div>

      {error && <Banner kind="err">{error}</Banner>}

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
                  <th>تاریخ</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <>
                    <tr key={record.id}>
                      <td><StateChip state={record.state} /></td>
                      <td className="ltr">{record.tax_id ?? '—'}</td>
                      <td className="numeric">{money(record.payload?.header?.tbill)}</td>
                      <td className="ltr">{record.reference_number ?? '—'}</td>
                      <td className="ltr small">{record.uid ?? '—'}</td>
                      <td className="small muted">
                        {new Date(record.created_at).toLocaleString('fa-IR')}
                      </td>
                      <td>
                        {record.detail && (record.detail.errors.length > 0 || record.detail.warnings.length > 0) && (
                          <button
                            className="btn ghost"
                            onClick={() => setExpanded(expanded === record.id ? null : record.id)}
                          >
                            {expanded === record.id ? 'بستن' : 'جزئیات'}
                          </button>
                        )}
                      </td>
                    </tr>
                    {expanded === record.id && record.detail && (
                      <tr key={`${record.id}-detail`}>
                        <td colSpan={7} style={{ background: 'var(--surface-2)' }}>
                          <IssueList result={record.detail} />
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

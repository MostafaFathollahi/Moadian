import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { Dashboard, InvoiceState, ProfileView } from '../../api/types'
import { Banner, Card, Empty, money } from '../../components/common'
import { StateChip } from '../submissions/StateChip'

/** Every state, always — including the zeros.
 *
 * Rendering only the states that have rows would make the dashboard's shape
 * depend on the data, so "no rejected invoices" would look identical to "the
 * rejected card is missing". A zero is information.
 */
const CARDS: { state: InvoiceState | 'total'; label: string; tone?: string }[] = [
  { state: 'total', label: 'همه صورتحساب‌ها', tone: 'is-total' },
  { state: 'draft', label: 'پیش‌نویس' },
  { state: 'invalid', label: 'دارای خطا', tone: 'is-warn' },
  { state: 'sent', label: 'ارسال‌شده' },
  { state: 'confirmed', label: 'ثبت‌شده در کارپوشه', tone: 'is-ok' },
  { state: 'rejected', label: 'رد‌شده', tone: 'is-danger' },
  { state: 'cancelled', label: 'ابطال‌شده' },
]

export function DashboardPage({
  profile, onNavigate,
}: {
  profile: ProfileView
  onNavigate: (route: 'invoice' | 'submissions' | 'admin') => void
}) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    setError(null)
    api
      .dashboard(profile.name)
      .then(setData)
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : String(cause)))
  }, [profile.name])

  const expiry = profile.certificate?.not_after
  const daysLeft = expiry
    ? Math.floor((new Date(expiry).getTime() - Date.now()) / 86_400_000)
    : null

  return (
    <>
      <div className="page-head">
        <div>
          <h1>داشبورد</h1>
          <p>
            {profile.name} — شناسه یکتا <span className="ltr">{profile.memory_id}</span> ·{' '}
            {profile.environment_label}
          </p>
        </div>
        <div className="btn-row">
          <button className="btn primary" onClick={() => onNavigate('invoice')}>
            صدور صورتحساب جدید
          </button>
          <button className="btn" onClick={() => onNavigate('submissions')}>
            پیگیری ارسال‌ها
          </button>
        </div>
      </div>

      {error && <Banner kind="err">{error}</Banner>}

      {/* A certificate that expires silently takes the whole system down at the
          worst moment, so it is surfaced before anything goes wrong. */}
      {daysLeft !== null && daysLeft < 30 && (
        <Banner kind={daysLeft < 0 ? 'err' : 'warn'}>
          {daysLeft < 0
            ? `گواهی امضا در تاریخ ${new Date(expiry!).toLocaleDateString('fa-IR')} منقضی شده است؛ ارسال صورتحساب ممکن نیست.`
            : `گواهی امضا تا ${daysLeft.toLocaleString('fa-IR')} روز دیگر منقضی می‌شود.`}{' '}
          <button className="btn ghost" onClick={() => onNavigate('admin')}>
            بررسی تنظیمات
          </button>
        </Banner>
      )}

      {profile.certificate_error && (
        <Banner kind="err">گواهی امضا خوانده نشد: {profile.certificate_error}</Banner>
      )}

      <div className="grid stats" style={{ marginBottom: 16 }}>
        {CARDS.map((card) => (
          <div key={card.state} className={`stat ${card.tone ?? ''}`}>
            <div className="value">{(data?.counts[card.state] ?? 0).toLocaleString('fa-IR')}</div>
            <div className="label">{card.label}</div>
          </div>
        ))}
      </div>

      <Card title="آخرین صورتحساب‌ها">
        {!data ? (
          <Empty>در حال بارگذاری…</Empty>
        ) : data.recent.length === 0 ? (
          <Empty>هنوز صورتحسابی برای این حافظه ثبت نشده است.</Empty>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>وضعیت</th>
                  <th>شماره مالیاتی</th>
                  <th className="numeric">مبلغ کل</th>
                  <th>شماره پیگیری</th>
                  <th>تاریخ</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((record) => (
                  <tr key={record.id}>
                    <td><StateChip state={record.state} /></td>
                    <td className="ltr">{record.tax_id ?? '—'}</td>
                    <td className="numeric">{money(record.payload?.header?.tbill)}</td>
                    <td className="ltr">{record.reference_number ?? '—'}</td>
                    <td className="small muted">
                      {new Date(record.created_at).toLocaleString('fa-IR')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

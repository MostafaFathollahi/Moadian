import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './api/client'
import type { ProfileView } from './api/types'
import { Banner } from './components/common'
import { AdminPanel } from './features/admin/AdminPanel'
import { BuyersPage } from './features/buyers/BuyersPage'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { GoodsPage } from './features/goods/GoodsPage'
import { InvoiceEntry } from './features/invoice/InvoiceEntry'
import { SubmissionsPage } from './features/submissions/SubmissionsPage'

type Route = 'dashboard' | 'invoice' | 'submissions' | 'buyers' | 'goods' | 'admin'

const NAV: { id: Route; label: string }[] = [
  { id: 'dashboard', label: 'داشبورد' },
  { id: 'invoice', label: 'صدور صورتحساب' },
  { id: 'submissions', label: 'پیگیری ارسال‌ها' },
  { id: 'buyers', label: 'خریداران' },
  { id: 'goods', label: 'کالا و خدمات' },
  { id: 'admin', label: 'تنظیمات' },
]

export function App() {
  const [route, setRoute] = useState<Route>('dashboard')
  const [profiles, setProfiles] = useState<ProfileView[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const reloadProfiles = useCallback(async () => {
    try {
      const list = await api.profiles()
      setProfiles(list)
      setActive((current) => {
        if (current && list.some((p) => p.name === current)) return current
        // Prefer a sandbox profile on first load. Landing an operator on
        // production by accident of alphabetical order is exactly the kind of
        // default that eventually files a real invoice by mistake.
        return list.find((p) => !p.is_production)?.name ?? list[0]?.name ?? null
      })
      setError(null)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reloadProfiles()
  }, [reloadProfiles])

  const profile = profiles.find((p) => p.name === active) ?? null

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          سامانه مودیان
          <small>صدور صورتحساب الکترونیکی</small>
        </div>

        <ProfileSwitcher
          profiles={profiles}
          active={active}
          onChange={setActive}
          disabled={loading}
        />

        {NAV.map((item) => (
          <button
            key={item.id}
            className="nav-item"
            aria-current={route === item.id ? 'page' : undefined}
            onClick={() => setRoute(item.id)}
          >
            {item.label}
          </button>
        ))}
      </aside>

      <main className="main">
        {error && <Banner kind="err">{error}</Banner>}

        {profile?.is_production && (
          <div className="production-banner">
            <span>محیط عملیاتی</span>
            <span className="small" style={{ fontWeight: 400 }}>
              صورتحساب‌های ارسالی در این محیط واقعی هستند و در کارپوشه ثبت می‌شوند.
            </span>
          </div>
        )}

        {!loading && profiles.length === 0 && (
          <Banner kind="info">
            هنوز هیچ حافظه مالیاتی تعریف نشده است. از بخش «تنظیمات» یک شناسه یکتا اضافه کنید.
          </Banner>
        )}

        {route === 'admin' ? (
          <AdminPanel profiles={profiles} onChanged={reloadProfiles} />
        ) : !profile ? (
          !loading && <Banner kind="warn">برای ادامه، یک حافظه مالیاتی انتخاب کنید.</Banner>
        ) : route === 'dashboard' ? (
          <DashboardPage profile={profile} onNavigate={setRoute} />
        ) : route === 'invoice' ? (
          <InvoiceEntry profile={profile} />
        ) : route === 'submissions' ? (
          <SubmissionsPage profile={profile} />
        ) : route === 'buyers' ? (
          <BuyersPage profile={profile} />
        ) : (
          <GoodsPage profile={profile} />
        )}
      </main>
    </div>
  )
}

/** One picker over profiles — not two over environment and memory id.
 *
 * A شناسه یکتای حافظه مالیاتی belongs to exactly one environment, so offering
 * them as independent choices would let an operator point a sandbox identity at
 * production. Selecting a profile picks both at once, by construction.
 */
function ProfileSwitcher({
  profiles, active, onChange, disabled,
}: {
  profiles: ProfileView[]
  active: string | null
  onChange: (name: string) => void
  disabled?: boolean
}) {
  const current = profiles.find((p) => p.name === active)
  return (
    <div className={`env-switch${current?.is_production ? ' is-production' : ''}`}>
      <label className="small muted">حافظه مالیاتی</label>
      <select
        value={active ?? ''}
        disabled={disabled || profiles.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        {profiles.length === 0 && <option value="">—</option>}
        {profiles.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name} — {p.memory_id} ({p.environment_label})
          </option>
        ))}
      </select>
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './api/client'
import type { CertificateCheck, ProfileView, UserInfo } from './api/types'
import { Banner } from './components/common'
import { clearSession, getUser, onSessionChange } from './lib/session'
import { ThemeSwitch } from './components/ThemeSwitch'
import { AdminPanel } from './features/admin/AdminPanel'
import { ChangePassword } from './features/auth/ChangePassword'
import { LoginPage } from './features/auth/LoginPage'
import { HelpPanel } from './features/help/HelpPanel'
import { BuyersPage } from './features/buyers/BuyersPage'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { GoodsPage } from './features/goods/GoodsPage'
import { InvoiceEntry } from './features/invoice/InvoiceEntry'
import { SubmissionsPage } from './features/submissions/SubmissionsPage'

type Route =
  | 'dashboard'
  | 'invoice'
  | 'submissions'
  | 'buyers'
  | 'goods'
  | 'admin'
  | 'help'
  | 'password'

const NAV: { id: Route; label: string; adminOnly?: boolean }[] = [
  { id: 'dashboard', label: 'داشبورد' },
  { id: 'invoice', label: 'صدور صورتحساب' },
  { id: 'submissions', label: 'پیگیری ارسال‌ها' },
  { id: 'buyers', label: 'خریداران' },
  { id: 'goods', label: 'کالا و خدمات' },
  { id: 'admin', label: 'تنظیمات', adminOnly: true },
  { id: 'help', label: 'راهنما' },
]

export function App() {
  const [user, setUser] = useState<UserInfo | null>(getUser)

  // A 401 anywhere clears the session; this turns that into a redirect to the
  // login screen rather than a blank page with an error on it.
  useEffect(() => onSessionChange(setUser), [])

  if (!user) return <LoginPage />
  return <Shell user={user} onSignOut={clearSession} />
}

function Shell({ user, onSignOut }: { user: UserInfo; onSignOut: () => void }) {
  const [route, setRoute] = useState<Route>('dashboard')
  // Which stored draft the entry form is editing. Held until the form submits
  // it or the operator asks for a new invoice, so switching to پیگیری and back
  // returns to the same draft instead of a blank form.
  const [openDraft, setOpenDraft] = useState<number | null>(null)
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
      // Show whatever happened. An unexpected error type used to fall through
      // as an empty page with a working sidebar and nothing in it.
      setError(
        cause instanceof ApiError
          ? cause.message
          : cause instanceof Error
            ? cause.message
            : String(cause),
      )
      setProfiles([])
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

        {NAV.filter((item) => !item.adminOnly || user.role === 'admin').map((item) => (
          <button
            key={item.id}
            className="nav-item"
            aria-current={route === item.id ? 'page' : undefined}
            onClick={() => setRoute(item.id)}
          >
            {item.label}
          </button>
        ))}

        <div className="sidebar-foot">
          <ThemeSwitch />
          <button className="nav-item" onClick={() => setRoute('password')}>
            <span>{user.display_name || user.username}</span>
            <span className="badge">{user.role === 'admin' ? 'مدیر' : 'کاربر'}</span>
          </button>
          <button className="nav-item" onClick={onSignOut}>
            خروج
          </button>
        </div>
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

        {user.role === 'admin' && <CertificateWarning />}

        {!loading && profiles.length === 0 && (
          <Banner kind="info">
            هنوز هیچ حافظه مالیاتی تعریف نشده است. از بخش «تنظیمات» یک شناسه یکتا اضافه کنید.
            تا آن زمان می‌توانید «خریداران» و «کالا و خدمات» را تکمیل کنید.
          </Banner>
        )}

        {/* Buyers and goods sit above the profile gate, with help, settings and
            the password form. They need no fiscal memory — and filling them in
            is the work available while waiting for one, which the gate used to
            make impossible. Everything below the gate really does belong to one
            memory: a dashboard, an invoice, a submission history. */}
        {route === 'help' ? (
          <HelpPanel isAdmin={user.role === 'admin'} />
        ) : route === 'password' ? (
          <ChangePassword user={user} />
        ) : route === 'admin' ? (
          <AdminPanel profiles={profiles} onChanged={reloadProfiles} me={user} />
        ) : route === 'buyers' ? (
          <BuyersPage />
        ) : route === 'goods' ? (
          <GoodsPage />
        ) : !profile ? (
          !loading && (
            <Banner kind="warn">
              برای این بخش، یک حافظه مالیاتی لازم است. آن را از «تنظیمات» تعریف و سپس از
              نوار کناری انتخاب کنید.
            </Banner>
          )
        ) : route === 'dashboard' ? (
          <DashboardPage profile={profile} onNavigate={setRoute} />
        ) : route === 'invoice' ? (
          <InvoiceEntry
            profile={profile}
            draftId={openDraft}
            onDraftOpened={setOpenDraft}
          />
        ) : (
          <SubmissionsPage
            profile={profile}
            onEdit={(id) => {
              setOpenDraft(id)
              setRoute('invoice')
            }}
          />
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

/** The certificate/key check, run once when the application loads.
 *
 * A private key that does not belong to its certificate signs perfectly well
 * and is refused by the tax service, so the failure surfaces on a real
 * submission with a serial already spent. There is no reason to wait for that:
 * the check is one comparison, and the answer is the same every time until
 * someone changes a file. Admins only — it names paths on the server, and it is
 * an admin who can act on the answer.
 *
 * Silent when everything matches. A banner that appears on every load is a
 * banner nobody reads on the load that matters.
 */
function CertificateWarning() {
  const [problems, setProblems] = useState<CertificateCheck[]>([])

  useEffect(() => {
    void api
      .verifySigningMaterial()
      .then((checks) => {
        // Both environments fall back to the same MOADIAN_CERTIFICATE_PATH
        // unless overridden, and one broken file is one problem however many
        // environments point at it.
        const seen = new Set<string>()
        setProblems(
          checks.filter((check) => {
            if (check.ok) return false
            const key = `${check.certificatePath}|${check.privateKeyPath}`
            if (seen.has(key)) return false
            seen.add(key)
            return true
          }),
        )
      })
      // A failed check is not itself a warning: the endpoint is admin-only and
      // reports every certificate problem as a 200. Anything else is a network
      // or session fault that the rest of the page will surface anyway.
      .catch(() => setProblems([]))
  }, [])

  if (problems.length === 0) return null
  return (
    <>
      {problems.map((problem) => (
        <Banner key={problem.environment} kind={problem.matches === false ? 'err' : 'warn'}>
          <strong>
            {problem.matches === false
              ? 'کلید خصوصی با گواهی امضا مطابقت ندارد'
              : 'گواهی امضا آماده نیست'}
            {' — '}
            {problem.environmentLabel}
          </strong>
          <div className="small" style={{ marginBlockStart: 4 }}>
            {problem.message} تا رفع این مشکل، ارسال صورتحساب انجام نخواهد شد.
          </div>
        </Banner>
      ))}
    </>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type {
  CertificateCheck,
  EnvironmentInfo,
  ProfileView,
  SigningMaterial,
  UserInfo,
} from '../../api/types'
import { Banner, Card, Empty, Field } from '../../components/common'
import { UsersPanel } from './UsersPanel'

export function AdminPanel({
  profiles, onChanged, me,
}: {
  profiles: ProfileView[]
  onChanged: () => void
  me: UserInfo
}) {
  const [tab, setTab] = useState<'system' | 'users'>('system')
  const [material, setMaterial] = useState<SigningMaterial[] | null>(null)
  const [environments, setEnvironments] = useState<EnvironmentInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [draft, setDraft] = useState({
    name: '', memory_id: '', environment: 'sandbox', economic_code: '',
  })
  const [testing, setTesting] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, string>>({})
  const [checks, setChecks] = useState<CertificateCheck[] | null>(null)
  const [checking, setChecking] = useState(false)

  const runCertificateCheck = useCallback(async () => {
    setChecking(true)
    try {
      setChecks(await api.verifySigningMaterial())
    } catch (cause) {
      setChecks(null)
      setError(cause instanceof ApiError ? cause.message : String(cause))
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void api.signingMaterial().then(setMaterial).catch(() => setMaterial(null))
    void api.environments().then(setEnvironments).catch(() => undefined)
    // Run on open as well as on the button. The answer does not change until
    // someone changes a file on the server, and an admin who opens this panel is
    // usually here because something is already wrong.
    void runCertificateCheck()
  }, [runCertificateCheck])

  async function addProfile() {
    setError(null)
    setNotice(null)
    try {
      await api.createProfile({
        name: draft.name,
        memory_id: draft.memory_id.toUpperCase(),
        environment: draft.environment,
        economic_code: draft.economic_code || null,
      })
      setDraft({ name: '', memory_id: '', environment: 'sandbox', economic_code: '' })
      setNotice('حافظه مالیاتی افزوده شد.')
      onChanged()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  async function test(name: string) {
    setTesting(name)
    try {
      const result = await api.testConnection(name)
      setResults((current) => ({
        ...current,
        [name]: result.nonce.ok
          ? result.authenticated.ok
            ? `اتصال و احراز هویت موفق — ${result.authenticated.serverKeys ?? 0} کلید سرور دریافت شد.`
            : `اتصال برقرار شد ولی احراز هویت رد شد: ${result.authenticated.error ?? ''}`
          : `اتصال برقرار نشد: ${result.nonce.error ?? ''}`,
      }))
    } catch (cause) {
      setResults((current) => ({
        ...current,
        [name]: cause instanceof ApiError ? cause.message : String(cause),
      }))
    } finally {
      setTesting(null)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>تنظیمات</h1>
          <p>حافظه‌های مالیاتی، گواهی امضا، اتصال و کاربران</p>
        </div>
        <div className="btn-row">
          <button className={`btn${tab === 'system' ? ' primary' : ''}`} onClick={() => setTab('system')}>
            سامانه
          </button>
          <button className={`btn${tab === 'users' ? ' primary' : ''}`} onClick={() => setTab('users')}>
            کاربران
          </button>
        </div>
      </div>

      {tab === 'users' && <UsersPanel me={me} />}

      {tab === 'system' && (
        <>
      {error && <Banner kind="err">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      <Card title="گواهی امضا و کلید خصوصی">
        <Banner kind="info">
          کلید خصوصی از طریق این صفحه بارگذاری نمی‌شود و هرگز از سمت مرورگر ارسال
          نمی‌گردد. مسیر فایل‌ها در متغیرهای محیطی سرور
          (<span className="ltr">MOADIAN_CERTIFICATE_PATH</span> و{' '}
          <span className="ltr">MOADIAN_PRIVATE_KEY_PATH</span>) تنظیم می‌شود و فایل‌ها
          مستقیماً روی سرور قرار می‌گیرند. آنچه در ادامه می‌بینید فقط وضعیت است.
        </Banner>

        {!material ? (
          <Empty>در حال بارگذاری…</Empty>
        ) : (
          <div className="grid cols-2">
            {material.map((entry) => (
              <div key={entry.environment} className="card" style={{ boxShadow: 'none' }}>
                <div className="spread" style={{ marginBottom: 8 }}>
                  <strong>{entry.environment === 'production' ? 'عملیاتی' : 'آزمایشی'}</strong>
                  {entry.keyPassphraseSet && (
                    <span className="chip ok">کلید رمزگذاری‌شده</span>
                  )}
                </div>
                <MaterialRow label="گواهی امضا" status={entry.certificate} />
                <MaterialRow label="کلید خصوصی" status={entry.privateKey} isKey />
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card
        title="آزمون تطابق گواهی و کلید"
        actions={
          <button className="btn" onClick={runCertificateCheck} disabled={checking}>
            {checking ? 'در حال بررسی…' : 'بررسی مجدد'}
          </button>
        }
      >
        <p className="small muted">
          کلید عمومی از فایل گواهی استخراج و با کلید خصوصی مقایسه می‌شود. این کار روی
          سرور انجام می‌گیرد و هیچ بخشی از کلید به مرورگر ارسال نمی‌شود. اگر این دو زوج
          نباشند، امضا ساخته می‌شود ولی سامانه مودیان آن را رد می‌کند — و آن موقع شماره
          سریال صورتحساب مصرف شده است.
        </p>
        {!checks ? (
          <Empty>در حال بررسی…</Empty>
        ) : (
          checks.map((check) => <CertificateCheckRow key={check.environment} check={check} />)
        )}
      </Card>

      <Card title="افزودن حافظه مالیاتی">
        <p className="small muted">
          هر شناسه یکتای حافظه مالیاتی تنها به یک محیط تعلق دارد و بین محیط‌ها قابل
          انتقال نیست؛ به همین دلیل محیط بخشی از خودِ حافظه است، نه یک انتخاب جداگانه.
        </p>
        <div className="grid cols-2">
          <Field label="نام نمایشی" required>
            <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </Field>
          <Field label="شناسه یکتای حافظه مالیاتی" required hint="۶ نویسه، حروف بزرگ و رقم">
            <input
              className="ltr"
              maxLength={6}
              value={draft.memory_id}
              onChange={(e) => setDraft({ ...draft, memory_id: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field label="محیط" required>
            <select
              value={draft.environment}
              onChange={(e) => setDraft({ ...draft, environment: e.target.value })}
            >
              {environments.map((env) => (
                <option key={env.value} value={env.value}>
                  {env.label} — {env.host}
                </option>
              ))}
            </select>
          </Field>
          <Field label="شماره اقتصادی">
            <input
              className="ltr"
              value={draft.economic_code}
              onChange={(e) => setDraft({ ...draft, economic_code: e.target.value })}
            />
          </Field>
        </div>
        <button
          className="btn primary"
          onClick={addProfile}
          disabled={draft.name.trim().length === 0 || draft.memory_id.length !== 6}
        >
          افزودن
        </button>
      </Card>

      <Card title="حافظه‌های تعریف‌شده">
        {profiles.length === 0 ? (
          <Empty>هنوز حافظه‌ای تعریف نشده است.</Empty>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>نام</th>
                  <th>شناسه یکتا</th>
                  <th>محیط</th>
                  <th>گواهی</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {profiles.map((profile) => (
                  <>
                    <tr key={profile.name}>
                      <td>{profile.name}</td>
                      <td className="ltr">{profile.memory_id}</td>
                      <td>
                        <span className={`chip ${profile.is_production ? 'prod' : ''}`}>
                          {profile.environment_label}
                        </span>
                      </td>
                      <td className="small">
                        {profile.certificate ? (
                          <>
                            <div className="ltr">{profile.certificate.national_id ?? '—'}</div>
                            <div className="muted">
                              انقضا {new Date(profile.certificate.not_after).toLocaleDateString('fa-IR')}
                            </div>
                          </>
                        ) : (
                          <span className="chip danger">در دسترس نیست</span>
                        )}
                      </td>
                      <td>
                        <div className="btn-row">
                          <button
                            className="btn ghost"
                            disabled={testing !== null}
                            onClick={() => test(profile.name)}
                          >
                            {testing === profile.name ? '…' : 'آزمون اتصال'}
                          </button>
                          <button
                            className="btn ghost"
                            onClick={async () => {
                              await api.deleteProfile(profile.name)
                              onChanged()
                            }}
                          >
                            حذف
                          </button>
                        </div>
                      </td>
                    </tr>
                    {results[profile.name] && (
                      <tr key={`${profile.name}-result`}>
                        <td colSpan={5} className="small" style={{ background: 'var(--surface-2)' }}>
                          {results[profile.name]}
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
      )}
    </>
  )
}

function MaterialRow({
  label, status, isKey,
}: {
  label: string
  status: SigningMaterial['certificate']
  isKey?: boolean
}) {
  const tone = !status.configured || !status.exists ? 'danger' : status.error ? 'warn' : 'ok'
  return (
    <div style={{ marginBottom: 8 }}>
      <div className="spread">
        <span className="small">{label}</span>
        <span className={`chip ${tone}`}>
          {!status.configured ? 'تنظیم نشده' : !status.exists ? 'یافت نشد' : `دسترسی ${status.mode}`}
        </span>
      </div>
      {status.path && <div className="ltr small muted">{status.path}</div>}
      {/* File mode is the key's only protection unless it is PKCS#8-encrypted. */}
      {isKey && status.error && <div className="err small">{status.error}</div>}
      {!isKey && status.error && <div className="err small">{status.error}</div>}
    </div>
  )
}

/** One environment's certificate/key verdict.
 *
 * Shows the certificate even when the pair could not be compared. A locked key
 * and a wrong key are different problems, and an operator who can see which
 * certificate is deployed can at least confirm it is the right one.
 */
function CertificateCheckRow({ check }: { check: CertificateCheck }) {
  const tone = check.ok ? 'ok' : check.matches === false ? 'danger' : 'warn'
  const verdict = check.ok
    ? 'زوج و معتبر'
    : check.matches === false
      ? 'عدم تطابق'
      : 'قابل بررسی نبود'
  return (
    <div className="card" style={{ boxShadow: 'none', marginBlockStart: 12 }}>
      <div className="spread" style={{ marginBottom: 8 }}>
        <strong>{check.environmentLabel}</strong>
        <span className={`chip ${tone}`}>{verdict}</span>
      </div>
      <p className="small" style={{ marginBlockEnd: 8 }}>{check.message}</p>
      {check.certificate && (
        <dl className="small muted" style={{ display: 'grid', gap: 2, margin: 0 }}>
          <CertificateFact label="دارنده" value={check.certificate.subject} ltr />
          <CertificateFact label="صادرکننده" value={check.certificate.issuer} ltr />
          <CertificateFact label="شناسه ملی" value={check.certificate.nationalId ?? '—'} ltr />
          <CertificateFact
            label="اعتبار تا"
            value={new Date(check.certificate.notAfter).toLocaleDateString('fa-IR')}
          />
          <CertificateFact
            label="اثر انگشت کلید عمومی"
            value={check.certificate.publicKeyFingerprint}
            ltr
          />
          <CertificateFact label="فایل گواهی" value={check.certificatePath ?? '—'} ltr />
          <CertificateFact label="فایل کلید" value={check.privateKeyPath ?? '—'} ltr />
        </dl>
      )}
    </div>
  )
}

function CertificateFact({ label, value, ltr }: { label: string; value: string; ltr?: boolean }) {
  return (
    <div className="spread" style={{ gap: 12 }}>
      <dt>{label}</dt>
      <dd className={ltr ? 'ltr' : undefined} style={{ margin: 0, textAlign: 'start' }}>
        {value}
      </dd>
    </div>
  )
}

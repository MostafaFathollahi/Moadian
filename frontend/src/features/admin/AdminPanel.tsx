import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { EnvironmentInfo, ProfileView, SigningMaterial } from '../../api/types'
import { Banner, Card, Empty, Field } from '../../components/common'

export function AdminPanel({
  profiles, onChanged,
}: {
  profiles: ProfileView[]
  onChanged: () => void
}) {
  const [material, setMaterial] = useState<SigningMaterial[] | null>(null)
  const [environments, setEnvironments] = useState<EnvironmentInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [draft, setDraft] = useState({
    name: '', memory_id: '', environment: 'sandbox', economic_code: '',
  })
  const [testing, setTesting] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, string>>({})

  useEffect(() => {
    void api.signingMaterial().then(setMaterial).catch(() => setMaterial(null))
    void api.environments().then(setEnvironments).catch(() => undefined)
  }, [])

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
          <p>حافظه‌های مالیاتی، گواهی امضا و وضعیت اتصال</p>
        </div>
      </div>

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

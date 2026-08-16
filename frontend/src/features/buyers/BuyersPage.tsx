import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { Buyer, ProfileView } from '../../api/types'
import { Banner, Card, Empty, Field } from '../../components/common'

const PERSON_TYPES = [
  { value: 1, label: 'حقیقی' },
  { value: 2, label: 'حقوقی' },
  { value: 3, label: 'مشارکت مدنی' },
  { value: 4, label: 'اتباع غیرایرانی' },
  { value: 5, label: 'مصرف‌کننده نهایی' },
]

export function BuyersPage({ profile }: { profile: ProfileView }) {
  const [buyers, setBuyers] = useState<Buyer[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState({
    name: '', national_id: '', economic_code: '', person_type: 2, postal_code: '',
  })

  const load = useCallback(() => {
    api.buyers(profile.name).then(setBuyers).catch((c) => setError(String(c)))
  }, [profile.name])

  useEffect(() => { setBuyers(null); load() }, [load])

  async function add() {
    setError(null)
    try {
      await api.addBuyer(profile.name, {
        name: draft.name,
        national_id: draft.national_id,
        economic_code: draft.economic_code || null,
        person_type: draft.person_type,
        postal_code: draft.postal_code || null,
      })
      setDraft({ name: '', national_id: '', economic_code: '', person_type: 2, postal_code: '' })
      load()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>خریداران</h1>
          <p>
            مخصوص این حافظه مالیاتی. خریدارِ ثبت‌شده در محیط آزمایشی روی صورتحساب
            عملیاتی ظاهر نمی‌شود.
          </p>
        </div>
      </div>

      {error && <Banner kind="err">{error}</Banner>}

      <div className="grid cols-2">
        <Card title="افزودن خریدار">
          <Field label="نام / نام تجاری" required>
            <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </Field>
          <Field
            label="شناسه ملی / شماره ملی"
            required
            hint="فقط رقم. صفرهای ابتدایی حفظ می‌شوند."
          >
            <input
              className="ltr"
              value={draft.national_id}
              onChange={(e) => setDraft({ ...draft, national_id: e.target.value })}
            />
          </Field>
          <Field label="شماره اقتصادی">
            <input
              className="ltr"
              value={draft.economic_code}
              onChange={(e) => setDraft({ ...draft, economic_code: e.target.value })}
            />
          </Field>
          <Field label="نوع شخص">
            <select
              value={draft.person_type}
              onChange={(e) => setDraft({ ...draft, person_type: Number(e.target.value) })}
            >
              {PERSON_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </Field>
          <Field label="کد پستی">
            <input
              className="ltr"
              value={draft.postal_code}
              onChange={(e) => setDraft({ ...draft, postal_code: e.target.value })}
            />
          </Field>
          <button
            className="btn primary"
            onClick={add}
            disabled={!draft.name.trim() || !draft.national_id.trim()}
          >
            افزودن
          </button>
        </Card>

        <Card title={`فهرست خریداران${buyers ? ` (${buyers.length.toLocaleString('fa-IR')})` : ''}`}>
          {!buyers ? (
            <Empty>در حال بارگذاری…</Empty>
          ) : buyers.length === 0 ? (
            <Empty>هنوز خریداری ثبت نشده است.</Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead>
                  <tr>
                    <th>نام</th>
                    <th>شناسه ملی</th>
                    <th>نوع</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {buyers.map((buyer) => (
                    <tr key={buyer.id}>
                      <td>{buyer.name}</td>
                      <td className="ltr">{buyer.national_id}</td>
                      <td className="small muted">
                        {PERSON_TYPES.find((t) => t.value === buyer.person_type)?.label}
                      </td>
                      <td>
                        <button
                          className="btn ghost"
                          onClick={async () => {
                            await api.deleteBuyer(profile.name, buyer.id)
                            load()
                          }}
                        >
                          حذف
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  )
}

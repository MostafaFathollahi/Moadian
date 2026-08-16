import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { GoodsService, ProfileView } from '../../api/types'
import { Banner, Card, Empty, Field, money } from '../../components/common'

export function GoodsPage({ profile }: { profile: ProfileView }) {
  const [goods, setGoods] = useState<GoodsService[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState({
    stuff_id: '', description: '', unit: '', vat_rate: '9', default_fee: '', is_default: false,
  })

  const load = useCallback(() => {
    api.goods(profile.name).then(setGoods).catch((c) => setError(String(c)))
  }, [profile.name])

  useEffect(() => { setGoods(null); load() }, [load])

  async function add() {
    setError(null)
    try {
      await api.addGoods(profile.name, {
        stuff_id: draft.stuff_id,
        description: draft.description,
        unit: draft.unit || null,
        vat_rate: draft.vat_rate === '' ? null : Number(draft.vat_rate),
        default_fee: draft.default_fee === '' ? null : Number(draft.default_fee),
        is_default: draft.is_default,
      })
      setDraft({ stuff_id: '', description: '', unit: '', vat_rate: '9', default_fee: '', is_default: false })
      load()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>کالا و خدمات</h1>
          <p>
            شناسه‌های کالا/خدمت که در فرم صورتحساب به صورت فهرست انتخابی ظاهر می‌شوند.
            یک مورد می‌تواند پیش‌فرض باشد و ردیف اول را از پیش پر کند.
          </p>
        </div>
      </div>

      {error && <Banner kind="err">{error}</Banner>}

      <div className="grid cols-2">
        <Card title="افزودن کالا/خدمت">
          <Field label="شناسه کالا/خدمت" required hint="شناسه اختصاص‌یافته توسط سازمان">
            <input
              className="ltr"
              value={draft.stuff_id}
              onChange={(e) => setDraft({ ...draft, stuff_id: e.target.value })}
            />
          </Field>
          <Field label="شرح کالا/خدمت" required>
            <input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
          </Field>
          <Field label="واحد اندازه‌گیری" hint="کد واحد، مثلاً ۱۶۴">
            <input
              className="ltr"
              value={draft.unit}
              onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
            />
          </Field>
          <Field label="نرخ مالیات بر ارزش افزوده (٪)">
            <input
              type="number"
              value={draft.vat_rate}
              onChange={(e) => setDraft({ ...draft, vat_rate: e.target.value })}
            />
          </Field>
          <Field label="مبلغ واحد پیش‌فرض">
            <input
              type="number"
              value={draft.default_fee}
              onChange={(e) => setDraft({ ...draft, default_fee: e.target.value })}
            />
          </Field>
          <label className="small" style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={draft.is_default}
              onChange={(e) => setDraft({ ...draft, is_default: e.target.checked })}
            />
            پیش‌فرض فرم صورتحساب باشد
          </label>
          <button
            className="btn primary"
            onClick={add}
            disabled={!draft.stuff_id.trim() || !draft.description.trim()}
          >
            افزودن
          </button>
        </Card>

        <Card title="فهرست کالا و خدمات">
          {!goods ? (
            <Empty>در حال بارگذاری…</Empty>
          ) : goods.length === 0 ? (
            <Empty>هنوز کالا یا خدمتی ثبت نشده است.</Empty>
          ) : (
            <div className="scroll-x">
              <table>
                <thead>
                  <tr>
                    <th>شرح</th>
                    <th>شناسه</th>
                    <th className="numeric">نرخ</th>
                    <th className="numeric">مبلغ واحد</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {goods.map((item) => (
                    <tr key={item.id}>
                      <td>
                        {item.description}
                        {item.is_default && <span className="chip accent" style={{ marginInlineStart: 6 }}>پیش‌فرض</span>}
                      </td>
                      <td className="ltr small">{item.stuff_id}</td>
                      <td className="numeric">{item.vat_rate ?? '—'}</td>
                      <td className="numeric">{money(item.default_fee)}</td>
                      <td>
                        <div className="btn-row">
                          {!item.is_default && (
                            <button
                              className="btn ghost"
                              onClick={async () => {
                                await api.makeGoodsDefault(profile.name, item.id)
                                load()
                              }}
                            >
                              پیش‌فرض
                            </button>
                          )}
                          <button
                            className="btn ghost"
                            onClick={async () => {
                              await api.deleteGoods(profile.name, item.id)
                              load()
                            }}
                          >
                            حذف
                          </button>
                        </div>
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

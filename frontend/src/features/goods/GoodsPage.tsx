import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { CatalogueEntry, CatalogueStatus, GoodsService } from '../../api/types'
import { Banner, Card, Empty, Field, money } from '../../components/common'

/** کالا و خدمات — one catalogue, shared by every fiscal memory.
 *
 * Takes no profile, for the same reason [BuyersPage] does not: a شناسه کالا/خدمت
 * is issued nationally and means the same thing in either environment.
 */
export function GoodsPage() {
  const [goods, setGoods] = useState<GoodsService[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState({
    stuff_id: '', description: '', unit: '', vat_rate: '9', default_fee: '', is_default: false,
  })

  const load = useCallback(() => {
    api.goods().then(setGoods).catch((c) => setError(String(c)))
  }, [])

  useEffect(() => { setGoods(null); load() }, [load])

  async function add() {
    setError(null)
    try {
      await api.addGoods({
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
            یک مورد می‌تواند پیش‌فرض باشد و ردیف اول را از پیش پر کند. این فهرست میان
            همه‌ی حافظه‌های مالیاتی مشترک است.
          </p>
        </div>
      </div>

      {error && <Banner kind="err">{error}</Banner>}

      <CatalogueLookup
        onPick={(entry) =>
          setDraft({
            ...draft,
            stuff_id: entry.stuffId,
            description: entry.description,
            // The catalogue publishes the rate; the unit and the price are the
            // operator's, which is the whole reason a favourite is worth saving.
            vat_rate: entry.vatRate === null ? '' : String(entry.vatRate),
          })
        }
      />

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
                                await api.makeGoodsDefault(item.id)
                                load()
                              }}
                            >
                              پیش‌فرض
                            </button>
                          )}
                          <button
                            className="btn ghost"
                            onClick={async () => {
                              await api.deleteGoods(item.id)
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

/** Where the شناسه کالا/خدمت actually comes from.
 *
 * The organization publishes the whole table, and once it has been imported
 * (tools/import_catalogue.py) it is searchable here — by number or by شرح, with
 * Persian/Arabic spelling and digits folded, so آشپزی finds rows stored as
 * اشپزی. Picking a result fills the form beside it; it is not saved until the
 * operator adds it, because the parts the catalogue does not know — unit,
 * default price — are exactly the parts worth entering once.
 *
 * Nothing here can *validate* a شناسه: only the tax service knows which codes
 * exist, and our copy of the list is as old as the last import. So an operator
 * may always type a code the search did not find.
 */
function CatalogueLookup({ onPick }: { onPick: (entry: CatalogueEntry) => void }) {
  const [status, setStatus] = useState<CatalogueStatus | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<CatalogueEntry[] | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void api.catalogueStatus().then(setStatus).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (query.trim().length < 2) {
      setHits(null)
      return
    }
    const timer = setTimeout(() => {
      setBusy(true)
      api
        .catalogueSearch(query, 20)
        .then(setHits)
        .catch(() => setHits([]))
        .finally(() => setBusy(false))
    }, 220)
    return () => clearTimeout(timer)
  }, [query])

  if (status?.empty) {
    return (
      <Card title="جست‌وجو در فهرست سازمان">
        <p className="small">
          فهرست شناسه‌های کالا و خدمات روی این سرور بارگذاری نشده است. فایل CSV را از
          کارپوشه دریافت کنید (اقلام کالا و خدمت ← دریافت فایل) و همه‌ی بخش‌ها را با یک
          فرمان وارد کنید:
        </p>
        <pre className="ltr small code-block">
          .venv/bin/python tools/import_catalogue.py ~/Downloads/product_service_*.csv
        </pre>
        <StuffIdPortalLink />
      </Card>
    )
  }

  return (
    <Card title="جست‌وجو در فهرست سازمان">
      <Field
        label="شناسه یا شرح کالا/خدمت"
        hint={
          status
            ? `${status.current.toLocaleString('fa-IR')} شناسه فعال — آخرین بارگذاری ${
                status.importedAt ? new Date(status.importedAt).toLocaleDateString('fa-IR') : '—'
              }`
            : 'در حال بارگذاری…'
        }
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="مثلاً: نرم افزار — یا ۲۳۳۰۰۰۴۵۶۷۴۱۳"
        />
      </Field>

      {busy && <p className="small muted">در حال جست‌وجو…</p>}

      {hits && hits.length === 0 && !busy && (
        <Empty>موردی یافت نشد. شناسه را می‌توانید دستی وارد کنید.</Empty>
      )}

      {hits && hits.length > 0 && (
        <div className="picker-static">
          {hits.map((hit) => (
            <button
              type="button"
              className="picker-row"
              key={hit.stuffId}
              onClick={() => onPick(hit)}
            >
              <span className="picker-desc">{hit.description}</span>
              <span className="picker-meta ltr">
                {hit.stuffId}
                {hit.vatRate !== null && ` · ${hit.vatRate}%`}
                {hit.taxable && <span className="rtl"> · {hit.taxable}</span>}
              </span>
            </button>
          ))}
        </div>
      )}

      <StuffIdPortalLink />
    </Card>
  )
}

function StuffIdPortalLink() {
  return (
    <p className="small muted" style={{ marginBlockEnd: 0, marginBlockStart: 12 }}>
      فهرست رسمی و به‌روز:{' '}
      <a
        className="ltr"
        href="https://stuffid.tax.gov.ir/"
        target="_blank"
        // noopener keeps the opened page from reaching back through window.opener
        // into a tab that can sign invoices.
        rel="noopener noreferrer"
      >
        stuffid.tax.gov.ir
      </a>
    </p>
  )
}

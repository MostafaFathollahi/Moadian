import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, ApiError } from '../../api/client'
import type { CatalogueEntry, GoodsService } from '../../api/types'

/** Choosing a شناسه کالا/خدمت: the operator's favourites, then all 200k of them.
 *
 * A `<select>` cannot do this. The organization's list runs to hundreds of
 * thousands of codes, so the only way in is to type — but the codes an operator
 * actually uses number in the dozens, and making them retype a search for the
 * same service every invoice would be worse than the select it replaced.
 *
 * So both, in one control and in that order: favourites are listed the moment
 * the field is focused and filtered locally as you type, and the full catalogue
 * is searched on the server underneath them. The operator never has to decide
 * which list they are looking in.
 *
 * Typing is matched either way — a number against the شناسه, words against the
 * شرح — and Persian/Arabic spelling and digits are folded on the server, so
 * آشپزی finds rows stored as اشپزی and ۱۲۳ finds 123. See moadian/persian.py.
 */
export function StuffPicker({
  value,
  favourites,
  onPick,
  onRaw,
  invalid,
  catalogueEmpty,
}: {
  value: string
  favourites: GoodsService[]
  /** A code was chosen. `vatRate` and `unit` are whatever the source knew. */
  onPick: (pick: { stuffId: string; description: string; vatRate: number | null; unit: string | null; fee: number | null }) => void
  /** Free text, for a code not in either list. Never blocked — the catalogue can
   *  be out of date or simply not imported, and the tax service is the only real
   *  authority on which codes exist. */
  onRaw: (text: string) => void
  invalid?: boolean
  catalogueEmpty?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<CatalogueEntry[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const [anchor, setAnchor] = useState<{ top: number; left: number; width: number } | null>(null)

  // The panel is portalled to <body> and positioned in viewport coordinates.
  //
  // It cannot simply be absolutely positioned inside the cell: this control sits
  // in the invoice lines table, which lives in a `.scroll-x` wrapper with
  // `overflow-x: auto`, and an ancestor with overflow clips absolutely
  // positioned descendants however deep they are. Inline, the panel was cut off
  // at the table's edge *and* widened its scroll region, which pushed the شرح
  // column out of view — the field looked as though it had been removed.
  useLayoutEffect(() => {
    if (!open) {
      setAnchor(null)
      return
    }
    const place = () => {
      const rect = box.current?.getBoundingClientRect()
      if (rect) setAnchor({ top: rect.bottom + 4, left: rect.left, width: rect.width })
    }
    place()
    // `true` for the capture phase: the table scrolls, not the window, so a
    // listener on window alone never fires and the panel detaches from its input.
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open])

  // Favourites filter locally: they are already in memory and a round trip per
  // keystroke for a list of twenty would only add latency.
  const matchingFavourites = useMemo(() => {
    const needle = fold(query)
    if (!needle) return favourites
    return favourites.filter(
      (f) => fold(f.description).includes(needle) || f.stuff_id.includes(foldDigits(needle)),
    )
  }, [favourites, query])

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setHits([])
      return
    }
    // Debounced: a search box that fires on every keystroke sends five requests
    // for a five-letter word and renders them out of order.
    const timer = setTimeout(() => {
      setSearching(true)
      setError(null)
      api
        .catalogueSearch(query, 25)
        .then(setHits)
        .catch((cause) => setError(cause instanceof ApiError ? cause.message : String(cause)))
        .finally(() => setSearching(false))
    }, 220)
    return () => clearTimeout(timer)
  }, [query, open])

  // Closing on outside click rather than on blur: blur fires before the click
  // that picked a row is delivered, so a blur-close swallows the selection.
  useEffect(() => {
    if (!open) return
    function onDown(event: MouseEvent) {
      const target = event.target as Node
      // The panel is portalled, so it is not inside `box` any more — a plain
      // contains() check would treat every click on a result as "outside" and
      // close the list before the click landed.
      if (box.current?.contains(target)) return
      if ((target as Element)?.closest?.('.picker-panel')) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const choose = useCallback(
    (pick: Parameters<typeof onPick>[0]) => {
      onPick(pick)
      setQuery('')
      setOpen(false)
    },
    [onPick],
  )

  // Already-chosen favourites are not offered again from the catalogue half.
  const favouriteIds = useMemo(() => new Set(favourites.map((f) => f.stuff_id)), [favourites])
  const catalogueHits = hits.filter((h) => !favouriteIds.has(h.stuffId))

  return (
    <div className="picker" ref={box}>
      <input
        className="ltr"
        value={open ? query : value}
        placeholder={value ? undefined : 'شناسه یا شرح…'}
        onFocus={() => {
          setQuery('')
          setOpen(true)
        }}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false)
          } else if (e.key === 'Enter' && query.trim()) {
            // Whatever was typed stands. A code missing from our copy of the
            // catalogue must not be unenterable.
            onRaw(query.trim())
            setOpen(false)
          }
        }}
        style={{ minWidth: 150, borderColor: invalid ? 'var(--danger)' : undefined }}
      />

      {open && anchor && createPortal(
        <div
          className="picker-panel"
          // Kept off the input's own width so a 340px panel is readable under a
          // narrow table column, while never spilling past the viewport edge.
          style={{
            top: anchor.top,
            left: Math.max(8, Math.min(anchor.left, window.innerWidth - 360)),
            minWidth: Math.max(anchor.width, 320),
          }}
          onMouseDown={(event) => event.preventDefault()}
        >
          {matchingFavourites.length > 0 && (
            <>
              <div className="picker-head">مورد‌های من</div>
              {matchingFavourites.map((f) => (
                <button
                  type="button"
                  className="picker-row"
                  key={`f${f.id}`}
                  onClick={() =>
                    choose({
                      stuffId: f.stuff_id,
                      description: f.description,
                      vatRate: f.vat_rate,
                      unit: f.unit,
                      fee: f.default_fee,
                    })
                  }
                >
                  <span className="picker-desc">
                    {f.description}
                    {f.is_default && <span className="chip accent">پیش‌فرض</span>}
                  </span>
                  <span className="picker-meta ltr">
                    {f.stuff_id}
                    {f.vat_rate !== null && ` · ${f.vat_rate}%`}
                  </span>
                </button>
              ))}
            </>
          )}

          <div className="picker-head">
            فهرست سازمان
            {searching && <span className="muted"> — در حال جست‌وجو…</span>}
          </div>

          {error ? (
            <div className="picker-note err">{error}</div>
          ) : catalogueEmpty ? (
            <div className="picker-note">
              فهرست شناسه‌های سازمان بارگذاری نشده است. راهنمای بارگذاری در بخش «کالا و
              خدمات».
            </div>
          ) : query.trim().length < 2 ? (
            <div className="picker-note">برای جست‌وجو دست‌کم دو نویسه بنویسید — شناسه یا شرح.</div>
          ) : catalogueHits.length === 0 && !searching ? (
            <div className="picker-note">موردی یافت نشد. می‌توانید شناسه را دستی وارد کنید.</div>
          ) : (
            catalogueHits.map((h) => (
              <button
                type="button"
                className="picker-row"
                key={h.stuffId}
                onClick={() =>
                  choose({
                    stuffId: h.stuffId,
                    description: h.description,
                    vatRate: h.vatRate,
                    unit: null,
                    fee: null,
                  })
                }
              >
                <span className="picker-desc">{h.description}</span>
                <span className="picker-meta ltr">
                  {h.stuffId}
                  {h.vatRate !== null && ` · ${h.vatRate}%`}
                  {h.taxable && <span className="rtl"> · {h.taxable}</span>}
                </span>
              </button>
            ))
          )}
        </div>,
        document.body,
      )}
    </div>
  )
}

/** The client half of the folding the server does in moadian/persian.py.
 *
 * Only needed for filtering the favourites, which never reach the server. Kept
 * to the collisions that actually bite — yeh, kaf, alef, ZWNJ and digits — rather
 * than reimplementing the whole table in TypeScript, where it would drift from
 * the Python that matters. */
export function fold(text: string): string {
  return (text ?? '')
    .normalize('NFC')
    .replace(/[يىےئ]/g, 'ی')
    .replace(/ك/g, 'ک')
    .replace(/[آأإٱ]/g, 'ا')
    .replace(/ة/g, 'ه')
    .replace(/ؤ/g, 'و')
    .replace(/[‌‍]/g, ' ')
    .replace(/[ً-ٰٕـ]/g, '')
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

export function foldDigits(text: string): string {
  return (text ?? '')
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
}

import type { ReactNode } from 'react'

export function Card({ title, actions, children }: {
  title?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="spread" style={{ marginBottom: 12 }}>
          {title && <h2 style={{ margin: 0 }}>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  )
}

export function Banner({ kind, children }: { kind: 'ok' | 'err' | 'warn' | 'info'; children: ReactNode }) {
  return <div className={`banner ${kind}`}>{children}</div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}

/** Persian digit grouping for rial amounts. */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString('fa-IR')
}

export function Field({
  label, required, conditional, error, hint, children,
}: {
  label: string
  required?: boolean
  conditional?: boolean
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className={`field${error ? ' invalid' : ''}`}>
      <label>
        {label}
        {required && <span className="req" title="اجباری">*</span>}
        {conditional && <span className="cond" title="در شرایط خاص اجباری">شرطی</span>}
      </label>
      {children}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span className="err">{error}</span>}
    </div>
  )
}

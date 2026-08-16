import type { InvoiceState } from '../../api/types'

/** Sent is not confirmed. The organization validates asynchronously, so these
 *  are genuinely different states and the UI must not collapse them. */
const LABELS: Record<InvoiceState, { text: string; tone: string }> = {
  draft: { text: 'پیش‌نویس', tone: '' },
  invalid: { text: 'دارای خطا', tone: 'warn' },
  sent: { text: 'ارسال‌شده', tone: 'accent' },
  confirmed: { text: 'ثبت‌شده', tone: 'ok' },
  rejected: { text: 'رد‌شده', tone: 'danger' },
  cancelled: { text: 'ابطال‌شده', tone: '' },
}

export function StateChip({ state }: { state: InvoiceState }) {
  const entry = LABELS[state] ?? { text: state, tone: '' }
  return <span className={`chip ${entry.tone}`}>{entry.text}</span>
}

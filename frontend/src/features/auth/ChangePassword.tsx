import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { UserInfo } from '../../api/types'
import { Banner, Card, Field } from '../../components/common'
import { replaceToken } from '../../lib/session'

export function ChangePassword({ user }: { user: UserInfo }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [message, setMessage] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const mismatch = repeat.length > 0 && next !== repeat

  async function submit() {
    setMessage(null)
    try {
      const result = await api.changePassword(current, next)
      // Changing a password ends every session for the account, including this
      // one; the server returns a replacement so the caller is not logged out.
      replaceToken(result.token)
      setCurrent('')
      setNext('')
      setRepeat('')
      setMessage({ kind: 'ok', text: 'گذرواژه تغییر کرد. سایر نشست‌های شما بسته شدند.' })
    } catch (cause) {
      setMessage({
        kind: 'err',
        text: cause instanceof ApiError ? cause.message : String(cause),
      })
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>حساب کاربری</h1>
          <p>
            {user.display_name || user.username} —{' '}
            {user.role === 'admin' ? 'مدیر سامانه' : 'کاربر'}
          </p>
        </div>
      </div>

      {message && <Banner kind={message.kind}>{message.text}</Banner>}

      <Card title="تغییر گذرواژه">
        <div style={{ maxWidth: 380 }}>
          <Field label="گذرواژه فعلی" required>
            <input
              type="password"
              className="ltr"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </Field>
          <Field label="گذرواژه جدید" required hint="دست‌کم ۸ نویسه">
            <input
              type="password"
              className="ltr"
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          </Field>
          <Field label="تکرار گذرواژه جدید" required error={mismatch ? 'مطابقت ندارد' : undefined}>
            <input
              type="password"
              className="ltr"
              value={repeat}
              onChange={(event) => setRepeat(event.target.value)}
            />
          </Field>
          <button
            className="btn primary"
            disabled={!current || next.length < 8 || next !== repeat}
            onClick={submit}
          >
            تغییر گذرواژه
          </button>
          <p className="small muted" style={{ marginTop: 10 }}>
            با تغییر گذرواژه، همه نشست‌های دیگر شما بسته می‌شوند و تنها همین مرورگر
            باز می‌ماند.
          </p>
        </div>
      </Card>
    </>
  )
}

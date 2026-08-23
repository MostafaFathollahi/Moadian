import { useState } from 'react'
import { api, ApiError } from '../../api/client'
import { setSession } from '../../lib/session'
import { ThemeSwitch } from '../../components/ThemeSwitch'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api.login(username.trim(), password)
      setSession(result.token, result.user)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'ورود ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      {/* Reachable before signing in. The theme is a property of this browser,
          not of an account, and the login screen is the first thing a
          dark-preferring operator sees. */}
      <div className="login-theme">
        <ThemeSwitch />
      </div>
      <form className="login-card" onSubmit={submit}>
        <h1>سامانه مودیان</h1>
        <p className="sub">صدور و ارسال صورتحساب الکترونیکی</p>

        {error && <div className="banner err">{error}</div>}

        <div className="field">
          <label>نام کاربری</label>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoFocus
            autoComplete="username"
            className="ltr"
          />
        </div>
        <div className="field">
          <label>گذرواژه</label>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            className="ltr"
          />
        </div>
        <button className="btn primary" style={{ width: '100%' }} disabled={busy || !username || !password}>
          {busy ? 'در حال ورود…' : 'ورود'}
        </button>
      </form>
    </div>
  )
}

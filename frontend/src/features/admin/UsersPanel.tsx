import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { UserInfo } from '../../api/types'
import { Banner, Card, Empty, Field } from '../../components/common'
import { replaceToken } from '../../lib/session'

const ROLE_LABEL: Record<string, string> = { admin: 'مدیر سامانه', user: 'کاربر' }

export function UsersPanel({ me }: { me: UserInfo }) {
  const [users, setUsers] = useState<UserInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [draft, setDraft] = useState({ username: '', password: '', display_name: '', role: 'user' })

  const load = useCallback(() => {
    api
      .users()
      .then(setUsers)
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : String(cause)))
  }, [])

  useEffect(load, [load])

  async function run(action: () => Promise<string>) {
    setError(null)
    setNotice(null)
    try {
      setNotice(await action())
      load()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : String(cause))
    }
  }

  const activeAdmins = (users ?? []).filter((u) => u.role === 'admin' && u.is_active).length

  return (
    <>
      {error && <Banner kind="err">{error}</Banner>}
      {notice && <Banner kind="ok">{notice}</Banner>}

      <Card title="افزودن کاربر">
        <div className="grid cols-2">
          <Field label="نام کاربری" required hint="۳ تا ۶۴ نویسه از حروف و ارقام انگلیسی و . _ -">
            <input
              className="ltr"
              value={draft.username}
              onChange={(e) => setDraft({ ...draft, username: e.target.value })}
            />
          </Field>
          <Field label="نام نمایشی">
            <input
              value={draft.display_name}
              onChange={(e) => setDraft({ ...draft, display_name: e.target.value })}
            />
          </Field>
          <Field label="گذرواژه" required hint="دست‌کم ۸ نویسه">
            <input
              type="password"
              className="ltr"
              value={draft.password}
              onChange={(e) => setDraft({ ...draft, password: e.target.value })}
            />
          </Field>
          <Field label="نقش" required>
            <select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
              <option value="user">کاربر</option>
              <option value="admin">مدیر سامانه</option>
            </select>
          </Field>
        </div>
        <button
          className="btn primary"
          disabled={draft.username.trim().length < 3 || draft.password.length < 8}
          onClick={() =>
            run(async () => {
              await api.createUser(draft)
              setDraft({ username: '', password: '', display_name: '', role: 'user' })
              return 'کاربر افزوده شد.'
            })
          }
        >
          افزودن
        </button>
      </Card>

      <Card
        title="کاربران"
        actions={
          <button
            className="btn"
            title="همه کاربران از سامانه خارج می‌شوند. نشست خودتان قطع نمی‌شود."
            onClick={() =>
              run(async () => {
                const result = await api.revokeAllSessions()
                // The sweep voids our own token too; the server hands back a
                // replacement so the admin does not log themselves out.
                replaceToken(result.token)
                return 'همه کاربران از سامانه خارج شدند.'
              })
            }
          >
            خروج همه کاربران
          </button>
        }
      >
        {!users ? (
          <Empty>در حال بارگذاری…</Empty>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>نام کاربری</th>
                  <th>نام نمایشی</th>
                  <th>نقش</th>
                  <th>وضعیت</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const isSelf = user.id === me.id
                  // Guarded on the server too; disabling here just avoids
                  // offering an action that is going to be refused.
                  const lastAdmin = user.role === 'admin' && user.is_active && activeAdmins <= 1
                  return (
                    <tr key={user.id}>
                      <td className="ltr">{user.username}</td>
                      <td>{user.display_name}</td>
                      <td>
                        <select
                          value={user.role}
                          disabled={isSelf || lastAdmin}
                          title={
                            isSelf
                              ? 'نقش حساب خودتان قابل تغییر نیست'
                              : lastAdmin
                                ? 'تنها مدیر فعال سامانه است'
                                : undefined
                          }
                          onChange={(e) =>
                            run(async () => {
                              await api.updateUser(user.id, { role: e.target.value })
                              return 'نقش به‌روزرسانی شد.'
                            })
                          }
                        >
                          {Object.entries(ROLE_LABEL).map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <span className={`chip ${user.is_active ? 'ok' : 'danger'}`}>
                          {user.is_active ? 'فعال' : 'غیرفعال'}
                        </span>
                        {isSelf && <span className="chip accent" style={{ marginInlineStart: 6 }}>شما</span>}
                      </td>
                      <td>
                        <div className="btn-row">
                          <button
                            className="btn ghost"
                            onClick={() =>
                              run(async () => {
                                const result = await api.revokeUserSessions(user.id)
                                if (result.token) replaceToken(result.token)
                                return 'نشست‌های این کاربر بسته شد.'
                              })
                            }
                          >
                            خروج از همه دستگاه‌ها
                          </button>
                          {user.is_active ? (
                            <button
                              className="btn ghost"
                              disabled={isSelf || lastAdmin}
                              onClick={() =>
                                run(async () => {
                                  await api.removeUser(user.id)
                                  return 'کاربر غیرفعال شد؛ داده‌هایش حفظ شده است.'
                                })
                              }
                            >
                              غیرفعال‌سازی
                            </button>
                          ) : (
                            <button
                              className="btn ghost"
                              onClick={() =>
                                run(async () => {
                                  await api.updateUser(user.id, { is_active: true })
                                  return 'کاربر دوباره فعال شد.'
                                })
                              }
                            >
                              فعال‌سازی
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="small muted" style={{ marginTop: 10 }}>
          «غیرفعال‌سازی» حساب را حذف نمی‌کند؛ ورود ممنوع می‌شود و نشست‌های باز بلافاصله
          بسته می‌شوند، ولی ردیف کاربر برای پیگیری‌های بعدی باقی می‌ماند.
        </p>
      </Card>
    </>
  )
}

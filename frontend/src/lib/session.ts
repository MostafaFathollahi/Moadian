/** Session state: the token, the signed-in user, and the 401 handler.
 *
 * The token lives in localStorage. That is a deliberate MVP choice with a known
 * trade-off — an XSS bug can read it, where an httpOnly cookie could not — and
 * it is acceptable here because the app is single-operator on localhost or
 * behind an authenticated proxy. Revisit it before this is ever exposed wider.
 */

import type { UserInfo } from '../api/types'

const TOKEN_KEY = 'moadian_token'
const USER_KEY = 'moadian_user'

type Listener = (user: UserInfo | null) => void
const listeners = new Set<Listener>()

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getUser(): UserInfo | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserInfo
  } catch {
    return null
  }
}

export function setSession(token: string, user: UserInfo): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  listeners.forEach((listener) => listener(user))
}

/** Replace the token without disturbing the user — after a password change or
 *  an admin's revoke-all, both of which hand back a fresh token. */
export function replaceToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  listeners.forEach((listener) => listener(null))
}

export function onSessionChange(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

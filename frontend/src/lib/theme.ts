/** Light, dark, or whatever the machine says.
 *
 * Three states rather than a boolean. "Follow the system" is a real answer and
 * the default one: an operator whose desktop switches at sunset expects this to
 * switch with it, and a two-way toggle can only pin the app to one side forever.
 *
 * The choice is written to `data-theme` on <html>, which is what the palette in
 * styles/app.css keys off. Following the system writes no attribute at all, so
 * the media query is left to answer — rather than this file reading the media
 * query and writing a concrete value, which would freeze the answer at load and
 * ignore a change made while the app is open.
 */

export type Theme = 'light' | 'dark' | 'system'

const KEY = 'moadian_theme'

export const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'سیستم' },
  { value: 'light', label: 'روشن' },
  { value: 'dark', label: 'تاریک' },
]

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark' || value === 'system'
}

export function getTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY)
    return isTheme(stored) ? stored : 'system'
  } catch {
    // Private windows and locked-down browsers throw on access, not on read.
    return 'system'
  }
}

/** Write the attribute. Exported so it can run before React mounts. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
}

export function setTheme(theme: Theme): void {
  applyTheme(theme)
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // A theme that cannot be remembered is still worth applying for this visit.
  }
}

/** Apply the stored choice. Call before the first paint to avoid a flash. */
export function initTheme(): Theme {
  const theme = getTheme()
  applyTheme(theme)
  return theme
}

import { useState } from 'react'
import { getTheme, setTheme, THEMES, type Theme } from '../lib/theme'

/** Light / dark / system, as three buttons rather than a cycling toggle.
 *
 * A single toggle can express two states, and there are three: an operator who
 * wants the app to follow their machine has no way back to that once a toggle
 * has pinned it. Three buttons also say what the current state *is* without
 * being clicked, which a toggle only implies.
 */
export function ThemeSwitch() {
  const [theme, setCurrent] = useState<Theme>(getTheme)

  function choose(next: Theme) {
    setTheme(next)
    setCurrent(next)
  }

  return (
    <div className="theme-switch" role="group" aria-label="نمایش">
      {THEMES.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => choose(option.value)}
          aria-pressed={theme === option.value}
          title={`نمایش ${option.label}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

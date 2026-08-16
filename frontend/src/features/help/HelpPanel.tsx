import { useState } from 'react'
import adminGuide from '../../../../docs/ADMIN_GUIDE.md?raw'
import userGuide from '../../../../docs/USER_GUIDE.md?raw'
import { Markdown } from '../../lib/markdown'

/** The guides, bundled from the same Markdown files that live in docs/.
 *
 * One source rather than two: a manual that drifts from the one on disk is
 * worse than no manual, because the reader cannot tell which is current.
 */
export function HelpPanel({ isAdmin }: { isAdmin: boolean }) {
  const [tab, setTab] = useState<'user' | 'admin'>('user')

  return (
    <>
      <div className="page-head">
        <div>
          <h1>راهنما</h1>
          <p>راهنمای کار با سامانه</p>
        </div>
        <div className="btn-row">
          <button
            className={`btn${tab === 'user' ? ' primary' : ''}`}
            onClick={() => setTab('user')}
          >
            راهنمای کاربر
          </button>
          {isAdmin && (
            <button
              className={`btn${tab === 'admin' ? ' primary' : ''}`}
              onClick={() => setTab('admin')}
            >
              راهنمای مدیر سامانه
            </button>
          )}
        </div>
      </div>

      <section className="card">
        <Markdown source={tab === 'admin' && isAdmin ? adminGuide : userGuide} />
      </section>
    </>
  )
}

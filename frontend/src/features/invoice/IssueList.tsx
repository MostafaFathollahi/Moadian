import type { VerifyResult, VerifyIssue } from '../../api/types'
import { money } from '../../components/common'

/** The اعتبارسنجی findings, each carrying the clause it came from.
 *
 * The citation is not decoration: when the tax service rejects something we
 * accepted (or vice versa) the first question is which document says otherwise,
 * and a message without a reference cannot answer it.
 */
export function IssueList({ result }: { result: VerifyResult }) {
  return (
    <ul className="issue-list">
      {result.errors.map((issue, index) => (
        <Issue key={`e${index}`} issue={issue} />
      ))}
      {result.warnings.map((issue, index) => (
        <Issue key={`w${index}`} issue={issue} warn />
      ))}
    </ul>
  )
}

function Issue({ issue, warn }: { issue: VerifyIssue; warn?: boolean }) {
  const where = issue.title || issue.field
  return (
    <li className={`issue${warn ? ' warn' : ''}`}>
      <span className="where">
        {where}
        {issue.line !== null && ` — ردیف ${(issue.line + 1).toLocaleString('fa-IR')}`}
      </span>
      {': '}
      {issue.message}
      {issue.expected !== null && issue.actual !== null && (
        <span className="delta">
          {' '}(انتظار {money(issue.expected)} · دریافت {money(issue.actual)})
        </span>
      )}
      {issue.reference && <div className="cite">{issue.reference}</div>}
    </li>
  )
}

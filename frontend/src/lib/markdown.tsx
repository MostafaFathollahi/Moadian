/** A small Markdown subset renderer for the bundled guides.
 *
 * Deliberately not a dependency. The guides are ours, written in a known
 * subset — headings, tables, lists, blockquotes, inline code and bold — so a
 * hundred lines here beats pulling a parser and a sanitiser into a page that
 * signs tax invoices. Raw HTML in the source is not supported, which is also
 * why it needs no sanitiser: nothing is ever set as innerHTML.
 */

import type { ReactNode } from 'react'

/** Inline: `code`, **bold**, and nothing else. */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = []
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g
  let last = 0
  let match: RegExpExecArray | null
  let index = 0
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-${index++}`
    if (token.startsWith('`')) {
      out.push(
        <code key={key} className="ltr">
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      out.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    }
    last = match.index + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function splitRow(line: string): string[] {
  return line.replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim())
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    // Fenced code — rendered verbatim, LTR, since it is always shell or config.
    if (line.startsWith('```')) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].startsWith('```')) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push(
        <pre key={key++} className="md-code ltr">
          <code>{body.join('\n')}</code>
        </pre>,
      )
      continue
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const Tag = (['h1', 'h2', 'h3', 'h4'] as const)[level - 1]
      blocks.push(<Tag key={key++}>{inline(heading[2], `h${key}`)}</Tag>)
      index += 1
      continue
    }

    if (line.startsWith('>')) {
      const body: string[] = []
      while (index < lines.length && lines[index].startsWith('>')) {
        body.push(lines[index].replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push(
        <blockquote key={key++} className="md-note">
          {inline(body.join(' '), `q${key}`)}
        </blockquote>,
      )
      continue
    }

    // Table: header row, separator, then body.
    if (line.includes('|') && index + 1 < lines.length && /^\|?[\s:|-]+\|/.test(lines[index + 1])) {
      const head = splitRow(line)
      index += 2
      const rows: string[][] = []
      while (index < lines.length && lines[index].includes('|')) {
        rows.push(splitRow(lines[index]))
        index += 1
      }
      blocks.push(
        <div key={key++} className="scroll-x">
          <table className="md-table">
            <thead>
              <tr>
                {head.map((cell, i) => (
                  <th key={i}>{inline(cell, `th${i}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c}>{inline(cell, `td${r}-${c}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = []
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ul key={key++}>
          {items.map((item, i) => (
            <li key={i}>{inline(item, `li${i}`)}</li>
          ))}
        </ul>,
      )
      continue
    }

    // Everything above either consumed a block or fell through to here, so this
    // branch has to consume at least one line — unconditionally, on the first
    // pass. It used to stop before any line starting with # > ` | - or *, which
    // is right for the *second* line of a paragraph and wrong for the first: a
    // line opening with inline code, or a `|` that begins no table, matched no
    // block above and was refused here too, so `index` never advanced and the
    // renderer spun forever. React never returns from a render that does not
    // terminate, so the symptom was a blank panel and a frozen tab — which is
    // exactly what the admin guide did, on one line of inline code.
    const paragraph: string[] = [lines[index]]
    index += 1
    while (index < lines.length && lines[index].trim() && !/^[#>`|]|^\s*[-*]\s/.test(lines[index])) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(<p key={key++}>{inline(paragraph.join(' '), `p${key}`)}</p>)
  }

  return <div className="md">{blocks}</div>
}

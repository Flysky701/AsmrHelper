import { Fragment, type ReactNode } from 'react'

// Deliberately small Markdown subset. React escapes all source text; HTML is never executed.
export function safeHelpUrl(value: string): string | null {
  if (/[\u0000-\u0020\u007f]/.test(value)) return null
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch { return null }
}

function inline(source: string, onDocument?: (href: string) => boolean): ReactNode[] {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g
  const output: ReactNode[] = []
  let cursor = 0
  for (const match of source.matchAll(pattern)) {
    output.push(source.slice(cursor, match.index))
    const token = match[0], key = match.index
    if (token.startsWith('`')) output.push(<code key={key}>{token.slice(1, -1)}</code>)
    else if (token.startsWith('**')) output.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token)!
      const href = link[2]!, external = safeHelpUrl(href)
      // Relative links remain inside the explicitly bundled documentation catalogue.
      const local = /^(?:\.\.\/)?[a-z0-9-]+\.md(?:#[^\s]*)?$/.test(href)
      output.push(external ? <a key={key} href={external} target="_blank" rel="noopener noreferrer">{link[1]}</a>
        : local && onDocument ? <button key={key} type="button" className="page-help-doc-link" onClick={() => onDocument(href)}>{link[1]}</button>
        : <span key={key}>{link[1]}</span>)
    }
    cursor = match.index! + token.length
  }
  output.push(source.slice(cursor))
  return output
}

export default function HelpMarkdown({ source, onDocument }: { source: string; onDocument?: (href: string) => boolean }) {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, '|'))
  let index = 0
  while (index < lines.length) {
    const line = lines[index]!
    if (!line.trim()) { index++; continue }
    const key = index, heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      const Tag = (`h${Math.min(heading[1]!.length + 2, 6)}`) as 'h3'
      blocks.push(<Tag key={key}>{inline(heading[2]!, onDocument)}</Tag>); index++; continue
    }
    if (/^\s*```/.test(line)) {
      const text: string[] = []; index++
      while (index < lines.length && !/^\s*```/.test(lines[index]!)) text.push(lines[index++]!)
      index++; blocks.push(<pre key={key}><code>{text.join('\n')}</code></pre>); continue
    }
    if (line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1] || '')) {
      const head = cells(line), rows: string[][] = []; index += 2
      while (index < lines.length && lines[index]!.includes('|') && lines[index]!.trim()) rows.push(cells(lines[index++]!))
      blocks.push(<div key={key} className="page-help-table-scroll" role="region" aria-label="Table" tabIndex={0}><table><thead><tr>{head.map((cell, i) => <th key={i} scope="col">{inline(cell, onDocument)}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{head.map((_, j) => <td key={j}>{inline(row[j] || '', onDocument)}</td>)}</tr>)}</tbody></table></div>); continue
    }
    const list = /^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(line)
    if (list) {
      const ordered = /^\s*\d+\./.test(line), start = ordered ? Number(/^\s*(\d+)\./.exec(line)![1]) : 1, items: ReactNode[] = []
      while (index < lines.length) {
        const item = /^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(lines[index]!)
        if (!item || /^\s*\d+\./.test(lines[index]!) !== ordered) break
        items.push(<li key={index}>{inline(item[1]!, onDocument)}</li>); index++
      }
      blocks.push(ordered ? <ol key={key} start={start}>{items}</ol> : <ul key={key}>{items}</ul>); continue
    }
    const paragraph = [line]; index++
    while (index < lines.length && lines[index]!.trim() && !/^(?:#{1,6}\s|\s*```|\s*(?:[-*]|\d+\.)\s)/.test(lines[index]!) && !(lines[index]!.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1] || ''))) paragraph.push(lines[index++]!)
    blocks.push(<p key={key}>{inline(paragraph.join(' '), onDocument)}</p>)
  }
  return <div className="page-help-markdown">{blocks.map((block, i) => <Fragment key={i}>{block}</Fragment>)}</div>
}

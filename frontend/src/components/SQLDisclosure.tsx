import { useState } from 'react'
import { Braces, Check, ClipboardCopy, ShieldCheck } from 'lucide-react'
import { highlightSql } from './SqlViewer'

interface SQLDisclosureProps {
  sql: string
}

export function SQLDisclosure({ sql }: SQLDisclosureProps) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="sql-disclosure">
      <div className="sql-disclosure-head">
        <span className="sql-disclosure-title">
          <Braces size={14} strokeWidth={1.75} />
          Generated SQL
        </span>
        <div className="sql-actions">
          <button className="sql-copy" onClick={copy}>
            {copied ? (
              <Check size={13} strokeWidth={1.75} />
            ) : (
              <ClipboardCopy size={13} strokeWidth={1.75} />
            )}
            {copied ? 'Copied' : 'Copy SQL'}
          </button>
        </div>
      </div>
      <pre className="sql-code">{highlightSql(sql)}</pre>
      <div className="sql-checks">
        <span className="sql-check">
          <ShieldCheck size={12} strokeWidth={1.75} />
          Read-only
        </span>
        <span className="sql-check">
          <ShieldCheck size={12} strokeWidth={1.75} />
          Schema validated
        </span>
        <span className="sql-check">
          <ShieldCheck size={12} strokeWidth={1.75} />
          Executed successfully
        </span>
      </div>
    </div>
  )
}
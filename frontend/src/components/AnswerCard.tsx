import { useRef, useState } from 'react'
import type { PipelineResult } from '../types'

interface AnswerCardProps {
  result: PipelineResult
}

const formatNumber = (n: unknown) => {
  if (n === null || n === undefined) return 'N/A'
  const num = Number(n)
  if (isNaN(num)) return String(n)
  if (num === Math.floor(num)) return num.toLocaleString()
  return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function AnswerCard({ result }: AnswerCardProps) {
  const [speaking, setSpeaking] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const speak = useRef(async (text: string) => {
    if (speaking) return
    setSpeaking(true)
    try {
      const res = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!res.ok) throw new Error(`TTS failed: ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      audioRef.current = new Audio(url)
      audioRef.current.onended = () => setSpeaking(false)
      audioRef.current.onerror = () => setSpeaking(false)
      await audioRef.current.play()
    } catch {
      // fallback to speechSynthesis
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'en-US'
      utterance.onend = () => setSpeaking(false)
      utterance.onerror = () => setSpeaking(false)
      speechSynthesis.speak(utterance)
    }
  })

  const handleSpeak = (text: string) => {
    speak.current(text)
  }

  const cols = result.execution?.columns ?? []
  const rows = result.final_result_rows ?? result.execution?.rows ?? []
  const sql = result.final_sql ?? result.generation?.generated_sql ?? ''

  const isKpi = rows.length === 1 && cols.length === 1
  const isTable = rows.length > 1 || cols.length > 1

  const primaryValue = isKpi ? rows[0]?.[cols[0]] : rows.length
  const primaryLabel = isKpi ? (cols[0]?.replace(/[()]/g, '') ?? 'Result') : 'Records'

  const answer = (result as any).answer
  const naturalText = answer?.natural || (isKpi ? `Result: ${formatNumber(primaryValue)}` : `Found ${rows.length} records.`)

  return (
    <section className="answer-card" role="region" aria-label="Answer">
      <div className="answer-header">
        <h2>Answer</h2>
        {speaking && <span className="speaking-badge">🔊 Speaking…</span>}
      </div>

      <div className="answer-main">
        {isKpi ? (
          <div className="answer-kpi">
            <div className="kpi-value">{formatNumber(primaryValue)}</div>
            <div className="kpi-label">{primaryLabel}</div>
          </div>
        ) : (
          <div className="answer-summary">
            <div className="summary-value">{formatNumber(rows.length)}</div>
            <div className="summary-label">{rows.length === 1 ? 'Record' : 'Records'}</div>
          </div>
        )}
      </div>

      <div className="answer-explanation">
        {naturalText}
      </div>

      <div className="answer-meta">
        <span className="meta-item">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
          Enterprise
        </span>
        <span className="meta-item">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          {result.execution?.execution_time_ms?.toFixed(1) ?? '?'} ms
        </span>
        <span className="meta-item">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
          {result.final_status === 'success' ? 'Success' : result.final_status === 'partial' ? 'Partial' : 'Error'}
        </span>
      </div>

      <div className="answer-actions">
        <button
          type="button"
          className="action-btn speak"
          onClick={() => handleSpeak(naturalText)}
          disabled={speaking}
          aria-label={speaking ? 'Stop speaking' : 'Listen to answer'}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" />
          </svg>
          {speaking ? 'Stop' : '🔊 Listen'}
        </button>

        {isTable && (
          <button
            type="button"
            className="action-btn view-results"
            onClick={() => window.dispatchEvent(new CustomEvent('open-results', { detail: result }))}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 3h18v18H3z" />
              <path d="M9 9h6v6H9z" />
            </svg>
            View results
          </button>
        )}

        <button
          type="button"
          className="action-btn how-it-worked"
          onClick={() => window.dispatchEvent(new CustomEvent('open-how-it-worked'))}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
          How it worked
        </button>
      </div>

      {isTable && (
        <div className="answer-table-wrapper">
          <table className="answer-table">
            <thead>
              <tr>
                {cols.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 10).map((row, i) => (
                <tr key={i}>
                  {cols.map((col) => (
                    <td key={col}>
                      {formatNumber(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
              {rows.length > 10 && (
                <tr>
                  <td colSpan={cols.length} className="table-more">
                    … and {rows.length - 10} more rows
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {sql && (
        <details className="sql-details">
          <summary>Show SQL</summary>
          <pre className="sql-code"><code>{sql}</code></pre>
        </details>
      )}
    </section>
  )
}
import { formatDistanceToNow } from 'date-fns'
import type { HistoryEntry } from '../history'

interface HistoryPanelProps {
  entries: HistoryEntry[]
  onRestore: (entry: HistoryEntry) => void
  onClear: () => void
}

export function HistoryPanel({ entries, onRestore, onClear }: HistoryPanelProps) {
  if (entries.length === 0) {
    return (
      <section className="history-panel">
        <div className="panel-header">
          <h3>Recent questions</h3>
        </div>
        <div className="empty-history">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
          <p>No questions yet</p>
          <p className="hint">Ask something to get started</p>
        </div>
      </section>
    )
  }

  return (
    <section className="history-panel">
      <div className="panel-header">
        <h3>Recent questions</h3>
        <button type="button" className="clear-btn" onClick={onClear} aria-label="Clear history">
          Clear
        </button>
      </div>
      <ul className="history-list" role="list">
        {entries.map((entry) => (
          <li key={entry.id} className="history-item">
            <button
              type="button"
              className="history-button"
              onClick={() => onRestore(entry)}
              aria-label={`Restore: ${entry.question}`}
            >
              <div className="history-question">{entry.question}</div>
              <div className="history-meta">
                <span className={`history-mode ${entry.mode}`}>
                  {entry.mode === 'voice' ? '🎙' : '⌨'} {entry.mode}
                </span>
                <span className="history-db">{entry.database}</span>
                <span className="history-time">{formatDistanceToNow(new Date(entry.timestamp), { addSuffix: true })}</span>
                {entry.result && entry.result.final_status && (
                  <span className={`history-status ${entry.result.final_status === 'success' ? 'ok' : entry.result.final_status === 'partial' ? 'warn' : 'error'}`}>
                    {entry.result.final_status}
                  </span>
                )}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
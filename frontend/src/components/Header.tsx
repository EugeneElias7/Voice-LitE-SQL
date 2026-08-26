import { useState, useRef, useEffect } from 'react'
import type { SystemStatus, DataSource } from '../types'

interface HeaderProps {
  status: SystemStatus | null
  activeModel: string
  activeDatasource: DataSource | null
  activeDatabaseId: string | null
  onModelClick: () => void
  onDatasourceClick: () => void
}

export function Header({
  status,
  activeModel,
  activeDatasource,
  activeDatabaseId,
  onModelClick,
  onDatasourceClick,
}: HeaderProps) {
  const [showStatus, setShowStatus] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowStatus(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const dbReady = status?.database?.state === 'ready'
  const ollamaReady = status?.ollama?.state === 'ready'
  const whisperReady = status?.whisper?.state === 'ready'

  return (
    <header className="app-header">
      <div className="header-brand">
        <span className="logo" aria-hidden="true">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
        </span>
        <div className="brand-text">
          <h1>Voice-LitE-SQL</h1>
          <p className="tagline">Ask your database anything.</p>
        </div>
      </div>

      <div className="header-center">
        <button
          className={`selector-btn datasource ${activeDatasource?.active ? 'active' : ''}`}
          onClick={onDatasourceClick}
          aria-label="Select data source"
        >
          <span className="selector-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <ellipse cx="12" cy="5" rx="9" ry="3" />
              <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
              <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
            </svg>
          </span>
          <span className="selector-label">
            {activeDatasource?.name ?? 'Data Source'}
            {activeDatabaseId && <span className="db-name"> / {activeDatabaseId}</span>}
          </span>
          <span className="chevron" aria-hidden="true">▼</span>
        </button>

        <button
          className={`selector-btn model ${ollamaReady ? 'ready' : 'offline'}`}
          onClick={onModelClick}
          aria-label="Select model"
        >
          <span className="selector-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="2" y="3" width="20" height="14" rx="2" />
              <path d="M8 21h8" />
              <path d="M12 17v4" />
            </svg>
          </span>
          <span className="selector-label">{activeModel}</span>
          <span className="chevron" aria-hidden="true">▼</span>
        </button>
      </div>

      <div className="header-right">
        <button
          className={`status-pill ${dbReady && ollamaReady && whisperReady ? 'ready' : 'degraded'}`}
          onClick={() => setShowStatus(!showStatus)}
          aria-expanded={showStatus}
          aria-label="System status"
        >
          <span className="status-dot" aria-hidden="true" />
          <span className="status-text">{dbReady && ollamaReady && whisperReady ? 'System ready' : 'Degraded'}</span>
        </button>

        {showStatus && (
          <div className="status-popover" ref={popoverRef} role="menu">
            <div className="popover-section">
              <h3>Components</h3>
              <div className="status-grid">
                {[
                  { key: 'backend', label: 'API Backend', state: status?.backend?.state },
                  { key: 'database', label: 'Database', state: status?.database?.state, detail: status?.database?.tables ? `${status.database.tables} tables` : undefined },
                  { key: 'ollama', label: 'Ollama', state: status?.ollama?.state, detail: status?.ollama?.model },
                  { key: 'model', label: 'Model', state: status?.model?.state, detail: status?.model?.name },
                  { key: 'whisper', label: 'Whisper ASR', state: status?.whisper?.state, detail: status?.whisper?.backend },
                  { key: 'chroma', label: 'ChromaDB', state: status?.chroma?.state },
                  { key: 'schema', label: 'Schema', state: status?.schema?.state },
                ].map((c) => (
                  <div key={c.key} className="status-item">
                    <span className={`status-indicator ${c.state === 'ready' ? 'ok' : c.state === 'not_built' ? 'warn' : 'error'}`} />
                    <div className="status-info">
                      <span className="status-label">{c.label}</span>
                      {c.detail && <span className="status-detail">{c.detail}</span>}
                    </div>
                    <span className={`status-badge ${c.state === 'ready' ? 'ok' : c.state === 'not_built' ? 'warn' : 'error'}`}>
                      {c.state}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </header>
  )
}
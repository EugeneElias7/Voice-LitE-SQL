import { useEffect, useRef, useState } from 'react'
import type { DataSource, DataSourceDatabase } from '../types'

interface DataSourceSelectorProps {
  datasources: DataSource[]
  activeId: string
  activeDatabaseId: string | null
  onSelect: (sourceId: string, databaseId?: string) => void
  onClose: () => void
}

export function DataSourceSelector({
  datasources,
  activeId,
  activeDatabaseId,
  onSelect,
  onClose,
}: DataSourceSelectorProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [selectedSource, setSelectedSource] = useState<DataSource | null>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onClose])

  const handleSourceClick = (source: DataSource) => {
    setSelectedSource(source)
    if (source.type === 'local' || !source.databases || source.databases.length === 0) {
      onSelect(source.id)
    }
  }

  const handleDatabaseClick = (database: DataSourceDatabase) => {
    if (selectedSource) {
      onSelect(selectedSource.id, database.id)
    }
  }

  return (
    <div className="datasource-selector-modal" role="dialog" aria-modal="true" aria-label="Select Data Source" ref={containerRef}>
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-content selector-modal">
        <div className="modal-header">
          <h2>Data Source</h2>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="selector-body">
          {selectedSource ? (
            <div className="database-list">
              <div className="selector-breadcrumb">
                <button type="button" className="breadcrumb-link" onClick={() => setSelectedSource(null)}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="19" y1="12" x2="5" y2="12" />
                    <polyline points="12 19 5 12 12 5" />
                  </svg>
                  Back to sources
                </button>
              </div>

              <h3>{selectedSource.name} Databases</h3>
              {selectedSource.databases && selectedSource.databases.length > 0 ? (
                <ul className="database-options">
                  {selectedSource.databases.map((db) => (
                    <li key={db.id}>
                      <button
                        type="button"
                        className={`database-option ${activeDatabaseId === db.id ? 'active' : ''}`}
                        onClick={() => handleDatabaseClick(db)}
                      >
                        <span className="db-name">{db.id}</span>
                        <span className="db-split">{db.split}</span>
                        {activeDatabaseId === db.id && (
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="no-databases">No databases available</p>
              )}

              <button type="button" className="back-btn" onClick={() => setSelectedSource(null)}>
                Back to sources
              </button>
            </div>
          ) : (
            <ul className="datasource-options">
              {datasources.map((source) => (
                <li key={source.id}>
                  <button
                    type="button"
                    className={`datasource-option ${activeId === source.id ? 'active' : ''} ${source.type}`}
                    onClick={() => handleSourceClick(source)}
                  >
                    <div className="source-icon">
                      {source.type === 'local' ? (
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="17 8 12 3 7 8" />
                          <line x1="12" y1="3" x2="12" y2="15" />
                        </svg>
                      ) : (
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <ellipse cx="12" cy="5" rx="9" ry="3" />
                          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                        </svg>
                      )}
                    </div>
                    <div className="source-info">
                      <span className="source-name">{source.name}</span>
                      <span className="source-meta">
                        {source.type === 'benchmark'
                          ? `${source.database_count ?? 0} databases`
                          : `${source.tables ?? 0} tables · ${(source.rows ?? 0).toLocaleString()} rows`}
                      </span>
                    </div>
                    {activeId === source.id && (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
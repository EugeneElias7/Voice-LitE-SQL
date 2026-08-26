import { useState } from 'react'
import type { SchemaPayload, DataSource } from '../types'

interface DatabaseExplorerProps {
  schema: SchemaPayload | null
  activeDatasource: DataSource | null
  activeDatabaseId: string | null
  onExplore?: () => void
  onClose?: () => void
  isDrawer?: boolean
  onDatabaseSelect?: (sourceId: string, databaseId?: string) => void
}

export function DatabaseExplorer({
  schema,
  activeDatasource,
  activeDatabaseId,
  onExplore,
  onClose,
  isDrawer = false,
  onDatabaseSelect,
}: DatabaseExplorerProps) {
  const [expandedTable, setExpandedTable] = useState<string | null>(null)

  const handleTableClick = (tableName: string) => {
    setExpandedTable(expandedTable === tableName ? null : tableName)
  }

  const renderDrawer = () => (
    <div className="db-explorer-drawer" role="dialog" aria-modal="true" aria-label="Database Explorer">
      <div className="drawer-header">
        <h2>Database Explorer</h2>
        <button type="button" className="close-btn" onClick={onClose} aria-label="Close">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
      <div className="drawer-content">{renderContent()}</div>
    </div>
  )

  const renderInline = () => (
    <div className="db-explorer-inline">
      <div className="explorer-header" onClick={onExplore}>
        <div className="explorer-title">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
          <span>
            {activeDatasource?.name ?? 'Database'}
            {activeDatabaseId && <span className="db-suffix"> / {activeDatabaseId}</span>}
          </span>
        </div>
        <span className="expand-hint">▼</span>
      </div>
      <div className="explorer-preview">
        {schema && (
          <>
            <div className="db-stats">
              <span>{schema.tables.length} tables</span>
              <span>{schema.total_rows.toLocaleString()} rows</span>
            </div>
            <div className="table-list-preview">
              {schema.tables.slice(0, 5).map((table) => (
                <div key={table.name} className="table-row-preview">
                  <span>{table.name}</span>
                  <span>{(table.row_count ?? 0).toLocaleString()} rows</span>
                </div>
              ))}
              {schema.tables.length > 5 && (
                <div className="more-tables">+{schema.tables.length - 5} more</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )

  const renderContent = () => {
    if (!schema) return <div className="empty-state">No database selected</div>

    return (
      <div className="db-explorer-content">
        <div className="db-header">
          <h3>{schema.database}</h3>
          <div className="db-stats">
            <span>{schema.tables.length} tables</span>
            <span>{schema.total_rows.toLocaleString()} rows</span>
          </div>
        </div>

        {activeDatasource?.type === 'benchmark' && activeDatasource.databases && onDatabaseSelect && (
          <div className="db-switcher">
            <label>Select database:</label>
            <select
              value={activeDatabaseId || ''}
              onChange={(e) => onDatabaseSelect(activeDatasource.id, e.target.value || undefined)}
            >
              <option value="">-- Choose database --</option>
              {activeDatasource.databases.map((db) => (
                <option key={db.id} value={db.id}>{db.id}</option>
              ))}
            </select>
          </div>
        )}

        <div className="tables-list">
          {schema.tables.map((table) => (
            <div key={table.name} className="table-card">
              <button
                type="button"
                className="table-header"
                onClick={() => handleTableClick(table.name)}
                aria-expanded={expandedTable === table.name}
              >
                <div className="table-info">
                  <span className="table-name">{table.name}</span>
                  <span className="table-stats">
                    {(table.row_count ?? 0).toLocaleString()} rows · {table.columns.length} columns
                  </span>
                </div>
                <span className={`expand-icon ${expandedTable === table.name ? 'open' : ''}`}>▼</span>
              </button>

              {expandedTable === table.name && (
                <div className="table-details">
                  <div className="table-meta">
                    {table.primary_keys.length && (
                      <div className="meta-item">
                        <strong>Primary Keys:</strong> {table.primary_keys.join(', ')}
                      </div>
                    )}
                    {table.foreign_keys.length && (
                      <div className="meta-item">
                        <strong>Foreign Keys:</strong>
                        <ul>
                          {table.foreign_keys.map((fk, i) => (
                            <li key={i}>{fk.source_column} → {fk.target_table}.{fk.target_column}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                  <div className="columns-table">
                    <table>
                      <thead>
                        <tr>
                          <th>Column</th>
                          <th>Type</th>
                          <th>Nullable</th>
                          <th>PK</th>
                          <th>FK</th>
                          <th>Default</th>
                        </tr>
                      </thead>
                      <tbody>
                        {table.columns.map((col) => (
                          <tr key={col.name}>
                            <td>{col.name}</td>
                            <td><code>{col.data_type}</code></td>
                            <td>{col.not_null ? 'No' : 'Yes'}</td>
                            <td>{col.primary_key_position > 0 ? 'Yes' : 'No'}</td>
                            <td>{table.foreign_keys.some((fk) => fk.source_column === col.name) ? 'Yes' : 'No'}</td>
                            <td>{col.default_value !== null ? String(col.default_value) : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (isDrawer) return renderDrawer()
  return renderInline()
}
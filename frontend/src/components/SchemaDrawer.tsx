import { useEffect, useState } from 'react'
import type { SchemaPayload, SchemaTable } from '../types'

interface SchemaDrawerProps {
  schema: SchemaPayload | null
  onClose: () => void
}

export function SchemaDrawer({ schema, onClose }: SchemaDrawerProps) {
  const [openTable, setOpenTable] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Schema explorer"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-head">
          <div>
            <div className="card-kicker">SCHEMA EXPLORER</div>
            {schema && (
              <h2>
                {schema.database} ·{' '}
                <span className="muted">
                  {schema.tables.length} tables · {schema.total_rows.toLocaleString()} rows
                </span>
              </h2>
            )}
          </div>
          <button type="button" className="btn btn-small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {!schema ? (
          <p className="muted">Loading schema…</p>
        ) : (
          <div className="drawer-list">
            {schema.tables.map((table) => (
              <SchemaTableRow
                key={table.name}
                table={table}
                open={openTable === table.name}
                onToggle={() => setOpenTable(openTable === table.name ? null : table.name)}
              />
            ))}
          </div>
        )}
      </aside>
    </div>
  )
}

function SchemaTableRow({
  table,
  open,
  onToggle,
}: {
  table: SchemaTable
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className={`schema-table ${open ? 'open' : ''}`}>
      <button type="button" className="schema-table-head" onClick={onToggle}>
        <span className="schema-table-name">{table.name}</span>
        <span className="schema-table-count">
          {table.columns.length} columns{table.row_count != null ? ` · ${table.row_count.toLocaleString()} rows` : ''}
        </span>
        <span className={`chevron ${open ? 'open' : ''}`}>▾</span>
      </button>
      {open && (
        <div className="schema-table-body">
          {table.columns.map((column) => {
            const fk = table.foreign_keys.find((foreign) => foreign.source_column === column.name)
            return (
              <div className="schema-column" key={column.name}>
                <span className="schema-col-name">
                  {column.name}
                  {column.primary_key_position > 0 && <span className="badge badge-pk">PK</span>}
                  {column.not_null && <span className="badge badge-nn">NN</span>}
                </span>
                <span className="schema-col-type">{column.data_type || '—'}</span>
                {fk && (
                  <span className="schema-col-fk mono">
                    → {fk.target_table}.{fk.target_column}
                  </span>
                )}
              </div>
            )
          })}
          {table.primary_keys.length > 0 && (
            <p className="schema-pk mono">Primary key: {table.primary_keys.join(', ')}</p>
          )}
        </div>
      )}
    </div>
  )
}
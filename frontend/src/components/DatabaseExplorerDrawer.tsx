import { useMemo, useState, useEffect } from 'react'
import { ChevronRight, Database, Search, X } from 'lucide-react'
import type { SchemaPayload, SchemaTable } from '../types'

interface DatabaseExplorerDrawerProps {
  open: boolean
  onClose: () => void
  schema: SchemaPayload | null
}

export function DatabaseExplorerDrawer({
  open,
  onClose,
  schema,
}: DatabaseExplorerDrawerProps) {
  const [openTable, setOpenTable] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  const tables = useMemo(() => {
    if (!schema) return []
    const q = search.trim().toLowerCase()
    if (!q) return schema.tables
    return schema.tables.filter(t => t.name.toLowerCase().includes(q))
  }, [schema, search])

  if (!open || !schema) return null

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Database explorer"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="drawer-head">
          <div>
            <h2>Database Explorer</h2>
            <div className="muted">
              {schema.database} · {schema.tables.length} tables · {schema.total_rows.toLocaleString()} rows
            </div>
          </div>
          <button type="button" className="drawer-close" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={1.75} />
          </button>
        </div>

        <div className="drawer-body">
          <div className="drawer-search">
            <Search size={14} strokeWidth={1.75} />
            <input
              type="text"
              placeholder="Search tables…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="drawer-content">
            {tables.map(table => (
              <SchemaTableRow
                key={table.name}
                table={table}
                open={openTable === table.name}
                onToggle={() => setOpenTable(openTable === table.name ? null : table.name)}
              />
            ))}
            {tables.length === 0 && <div className="popover-empty">No tables match</div>}
          </div>
        </div>
      </aside>
    </div>
  )
}

function SchemaTableRow({ table, open, onToggle }: { table: SchemaTable; open: boolean; onToggle: () => void }) {
  const rowCount = table.row_count != null ? ` · ${table.row_count.toLocaleString()} rows` : ''

  return (
    <div className={`schema-table ${open ? 'open' : ''}`}>
      <button type="button" className="schema-table-head" onClick={onToggle}>
        <Database size={14} strokeWidth={1.75} />
        <span className="schema-table-name">{table.name}</span>
        <span className="schema-table-count">
          {table.columns.length} columns{rowCount}
        </span>
        <ChevronRight size={14} strokeWidth={1.75} />
      </button>
      {open && (
        <div className="schema-table-body">
          {table.columns.map(column => {
            const fk = table.foreign_keys.find(f => f.source_column === column.name)
            return (
              <div className="schema-column" key={column.name}>
                <span className="schema-col-name">
                  {column.name}
                  {column.primary_key_position > 0 && <span className="badge badge-pk">PK</span>}
                  {column.not_null && <span className="badge badge-nn">NN</span>}
                </span>
                <span className="schema-col-type">{column.data_type || '—'}</span>
                {fk && (
                  <span className="schema-col-fk mono">→ {fk.target_table}.{fk.target_column}</span>
                )}
              </div>
            )
          })}
          {table.foreign_keys.length > 0 && (
            <div className="schema-fks">
              <strong>Foreign keys:</strong>
              {table.foreign_keys.map(fk => (
                <div key={`${fk.source_column}-${fk.target_table}`} className="mono">
                  {table.name}.{fk.source_column} → {fk.target_table}.{fk.target_column}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
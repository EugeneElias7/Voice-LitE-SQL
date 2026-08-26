import type { SchemaPayload } from '../types'

interface DatabaseCardProps {
  schema: SchemaPayload | null
  onExplore: () => void
}

export function DatabaseCard({ schema, onExplore }: DatabaseCardProps) {
  return (
    <section className="card database-card" aria-label="Database">
      <div className="card-kicker">DATABASE</div>
      <div className="database-line">
        <span className="status-dot ok" aria-hidden="true" />
        <span className="database-name">
          {schema?.database ? schema.database.charAt(0).toUpperCase() + schema.database.slice(1) : '—'}
        </span>
      </div>
      {schema && (
        <p className="database-meta">
          {schema.tables.length} tables · {schema.total_rows.toLocaleString()} rows
        </p>
      )}
      <button type="button" className="btn btn-small btn-ghost" onClick={onExplore}>
        Explore schema
      </button>
    </section>
  )
}
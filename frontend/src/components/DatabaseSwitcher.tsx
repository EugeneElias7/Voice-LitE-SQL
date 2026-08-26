import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Check,
  ChevronDown,
  Database,
  FileUp,
  Globe,
  Link,
  Loader2,
  Search,
  X,
} from 'lucide-react'
import type { DataSource } from '../types'

interface DatabaseSwitcherProps {
  activeSource: DataSource | null
  sources: DataSource[]
  onSelectSource: (source: DataSource, dbId?: string) => void
}

export function DatabaseSwitcher({
  activeSource,
  sources,
  onSelectSource,
}: DatabaseSwitcherProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [databases, setDatabases] = useState<{ id: string; source: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedBenchmark, setExpandedBenchmark] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const loadBenchmark = useCallback(async (sourceId: string) => {
    if (databases.some(d => d.source === sourceId)) return
    setLoading(true)
    try {
      const res = await fetch('/api/datasources')
      const data = await res.json()
      const source = data.sources.find((s: any) => s.id === sourceId)
      if (source?.databases) {
        setDatabases(prev => [
          ...prev.filter(d => d.source !== sourceId),
          ...source.databases.map((d: any) => ({ id: d.id, source: sourceId })),
        ])
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [databases])

  const handleSelect = useCallback(
    (source: DataSource, dbId?: string) => {
      onSelectSource(source, dbId)
      setOpen(false)
      setSearch('')
    },
    [onSelectSource]
  )

  const activeName = activeSource
    ? activeSource.database
      ? `${activeSource.name} / ${activeSource.database}`
      : activeSource.name
    : 'Select Database'

  const localSources = sources.filter(s => s.type === 'local')
  const benchmarkSources = sources.filter(s => s.type === 'benchmark')
  
  // Filter local sources by search
  const filteredLocalSources = localSources.filter(s => 
    s.name.toLowerCase().includes(search.toLowerCase())
  )
  
  // Filter benchmark databases by search
  

  return (
    <div className="popover-wrap" ref={ref}>
      <button
        className="pill"
        onClick={() => setOpen(v => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        title={activeName}
      >
        <Database size={15} strokeWidth={1.75} />
        <span>{activeName}</span>
        <ChevronDown className="pill-chevron" size={13} strokeWidth={1.75} />
      </button>

      {open && (
        <div className="popover popover-lg">
          <div className="popover-head">
            <span className="popover-head-label">Data source</span>
            <button
              className="popover-close"
              onClick={() => {
                setOpen(false)
                setSearch('')
              }}
              aria-label="Close"
            >
              <X size={14} strokeWidth={1.75} />
            </button>
          </div>

          <div className="popover-search">
            <Search size={14} strokeWidth={1.75} />
            <input
              type="text"
              placeholder="Search databases…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              autoFocus
            />
          </div>

          <div className="popover-body">
            {/* Local sources */}
            {filteredLocalSources.map(source => (
              <button
                key={source.id}
                className={`popover-item ${source.id === activeSource?.id ? 'active' : ''}`}
                onClick={() => handleSelect(source)}
                disabled={Boolean(source.error)}
              >
                <Database size={16} strokeWidth={1.75} />
                <div className="popover-item-main">
                  <span className="popover-item-name">{source.name}</span>
                  <span className="popover-item-sub">
                    Local SQLite
                    {source.database && ` · ${source.database}`}
                    {source.tables && source.rows && ` · ${source.tables} tables · ${source.rows.toLocaleString()} rows`}
                  </span>
                </div>
                {source.id === activeSource?.id && (
                  <Check className="popover-item-check" size={16} strokeWidth={1.75} />
                )}
              </button>
            ))}

            {/* Benchmark sources */}
            {benchmarkSources.map(source => {
              const isExpanded = expandedBenchmark === source.id
              const sourceDatabases = databases.filter(d => d.source === source.id && d.id.toLowerCase().includes(search.toLowerCase()))
              const isLoading = loading && !databases.some(d => d.source === source.id)

              return (
                <BenchmarkSection
                  key={source.id}
                  label={source.name}
                  subtitle={`Benchmark · ${source.database_count ?? source.databases?.length ?? 0} databases`}
                  open={isExpanded}
                  onToggle={() => {
                    setExpandedBenchmark(v => (v === source.id ? null : source.id))
                    if (!isExpanded) void loadBenchmark(source.id)
                  }}
                  loading={isLoading}
                  databases={sourceDatabases}
                  onSelect={id => {
                    const s = sources.find(src => src.id === source.id)
                    if (s) handleSelect(s, id)
                  }}
                />
              )
            })}

            <div className="popover-divider" />

            <button className="popover-action">
              <FileUp size={16} strokeWidth={1.75} />
              Upload SQLite database
            </button>
            <button className="popover-action">
              <Link size={16} strokeWidth={1.75} />
              Connect database
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

interface BenchmarkSectionProps {
  label: string
  subtitle?: string
  open: boolean
  onToggle: () => void
  loading: boolean
  databases: { id: string; source: string }[]
  onSelect: (dbId: string) => void
}

function BenchmarkSection({
  label,
  subtitle,
  open,
  onToggle,
  loading,
  databases,
  onSelect,
}: BenchmarkSectionProps) {
  return (
    <>
      <button className="popover-item popover-benchmark" onClick={onToggle}>
        <Globe size={16} strokeWidth={1.75} />
        <div className="popover-item-main" style={{ flex: 1 }}>
          <span className="popover-item-name">{label}</span>
          {subtitle && <span className="popover-item-sub">{subtitle}</span>}
        </div>
        {loading ? (
          <Loader2 size={14} className="spinner" strokeWidth={1.75} />
        ) : (
          <ChevronDown
            className="popover-item-chevron"
            size={14}
            strokeWidth={1.75}
            style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s ease' }}
          />
        )}
      </button>
      {open && (
        <>
          <div className="popover-body" style={{ maxHeight: 200 }}>
            {loading ? (
              <div className="popover-loading">
                <Loader2 className="spinner" size={14} strokeWidth={1.75} />
                Loading databases…
              </div>
            ) : databases.length === 0 ? (
              <div className="popover-empty">No matching databases</div>
            ) : (
              databases.map(db => (
                <button key={db.id} className="popover-item" onClick={() => onSelect(db.id)}>
                  <Database size={16} strokeWidth={1.75} />
                  <span className="popover-item-main">
                    <span className="popover-item-name mono" style={{ fontFamily: 'var(--mono)' }}>
                      {db.id}
                    </span>
                  </span>
                </button>
              ))
            )}
          </div>
        </>
      )}
    </>
  )
}
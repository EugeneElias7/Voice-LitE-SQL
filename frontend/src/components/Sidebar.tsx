import { useMemo, useState } from 'react'
import { Database, MessageSquare, MessageSquarePlus, Mic, PanelLeftClose, PanelLeftOpen, Table2, Trash2 } from 'lucide-react'
import type { DataSource, SchemaPayload } from '../types'
import type { HistoryEntry } from '../history'

interface SidebarProps {
  collapsed: boolean
  onToggleCollapse: () => void
  conversations: HistoryEntry[]
  currentConversationId: string | null
  onSelectConversation: (conv: HistoryEntry) => void
  onNewConversation: () => void
  activeSource: DataSource | null
  schema: SchemaPayload | null
  onOpenDatabaseExplorer: () => void
  onClearHistory: () => void
}

export function Sidebar({
  collapsed,
  onToggleCollapse,
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  activeSource,
  schema,
  onOpenDatabaseExplorer,
  onClearHistory,
}: SidebarProps) {
  const [expandedTable, setExpandedTable] = useState<string | null>(null)
  const [showAllTables, setShowAllTables] = useState(false)

  const visibleTables = useMemo(() => {
    if (!schema) return []
    return showAllTables ? schema.tables : schema.tables.slice(0, 8)
  }, [schema, showAllTables])

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        {collapsed ? (
          <span className="logo-mini">VL</span>
        ) : (
          <div className="logo">
            <span className="logo-mark">
              <Database size={14} strokeWidth={1.75} />
            </span>
            <span className="logo-text">Voice-LitE-SQL</span>
          </div>
        )}
        <button
          className="collapse-btn"
          onClick={onToggleCollapse}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
        </button>
      </div>

      <div className="sidebar-body">
        {!collapsed && (
          <button className="btn-new" onClick={onNewConversation}>
            <MessageSquarePlus size={16} strokeWidth={1.75} />
            New Query
          </button>
        )}

        {!collapsed && (
          <section>
            <div className="section-label">
              Recent
              {conversations.length > 0 && (
                <Trash2 size={14} onClick={onClearHistory} />
              )}
            </div>
            {conversations.length === 0 ? (
              <div className="history-empty">No conversations yet</div>
            ) : (
              <ul className="history-list">
                {conversations.map(conv => (
                  <li
                    key={conv.id}
                    className={`history-item ${conv.id === currentConversationId ? 'active' : ''}`}
                    onClick={() => onSelectConversation(conv)}
                  >
                    {conv.mode === 'voice' ? (
                      <Mic size={15} strokeWidth={1.75} />
                    ) : (
                      <MessageSquare size={15} strokeWidth={1.75} />
                    )}
                    <span className="history-item-title">{conv.question.slice(0, 40)}${conv.question.length > 40 ? '…' : ''}</span>
                    <span className="history-item-time">{formatTime(conv.timestamp)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {!collapsed && (
          <section>
            <div className="section-label">Database</div>
            {activeSource && schema ? (
              <>
                <div className="db-row">
                  <Database size={16} strokeWidth={1.75} />
                  <div className="db-meta">
                    <div className="db-name">{activeSource.name}</div>
                    <div className="db-stats">
                      {schema.tables.length} tables
                    </div>
                  </div>
                </div>
                <ul className="table-list">
                  {visibleTables.map(table => (
                    <li key={table.name}>
                      <button
                        className="table-item"
                        onClick={() => {
                          setExpandedTable(expandedTable === table.name ? null : table.name)
                          onOpenDatabaseExplorer()
                        }}
                      >
                        <span className="table-name">{table.name}</span>
                        <span className="table-count">
                          {table.row_count != null ? table.row_count.toLocaleString() : ''}
                        </span>
                      </button>
                    </li>
                  ))}
                  {schema.tables.length > 8 && (
                    <li>
                      <button className="table-more" onClick={() => setShowAllTables(v => !v)}>
                        {showAllTables ? 'Show fewer' : `+ ${schema.tables.length - 8} more`}
                      </button>
                    </li>
                  )}
                </ul>
              </>
            ) : (
              <div className="history-empty">No database loaded</div>
            )}
          </section>
        )}

      </div>

      <div className="sidebar-footer">
        <button className="footer-btn" onClick={onOpenDatabaseExplorer}>
          <Table2 size={16} strokeWidth={1.75} />
          <span className="footer-btn-label">Database Explorer</span>
        </button>
      </div>
    </aside>
  )
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  if (diff < 60000) return 'now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`
  return date.toLocaleDateString()
}
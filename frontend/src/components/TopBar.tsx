import { FlaskConical, RotateCcw } from 'lucide-react'
import type { DataSource, OllamaModel } from '../types'
import { DatabaseSwitcher } from './DatabaseSwitcher'
import { ModelSwitcher } from './ModelSwitcher'

interface TopBarProps {
  activeSource: DataSource | null
  sources: DataSource[]
  currentModel: string
  models: OllamaModel[]
  onSelectSource: (source: DataSource, dbId?: string) => void
  onSelectModel: (model: string) => void
  researchMode: boolean
  onToggleResearch: () => void
  backendReady: boolean
  conversationTitle: string | null
  onReconnect: () => void
}

export function TopBar({
  activeSource,
  sources,
  currentModel,
  models,
  onSelectSource,
  onSelectModel,
  researchMode,
  onToggleResearch,
  backendReady,
  conversationTitle,
  onReconnect,
}: TopBarProps) {
  return (
    <header className="top-bar" data-ui-version="VOICE-LITE-SQL-UI-V2">
      <div className="top-bar-left">
        {conversationTitle ? (
          <span className="conversation-title">{conversationTitle}</span>
        ) : (
          <span className="conversation-title-placeholder">New conversation</span>
        )}
      </div>

      <div className="top-bar-right">
        <DatabaseSwitcher
          activeSource={activeSource}
          sources={sources}
          onSelectSource={onSelectSource}
        />
        <ModelSwitcher
          currentModel={currentModel}
          models={models}
          onSelectModel={onSelectModel}
        />
        <button
          className={`pill pill-icon ${researchMode ? 'active' : ''}`}
          onClick={onToggleResearch}
          title={researchMode ? 'Exit research mode' : 'Enter research mode'}
          aria-pressed={researchMode}
        >
          <FlaskConical size={15} strokeWidth={1.75} />
          <span>Research</span>
        </button>
        <div className={`status-pill ${backendReady ? '' : 'offline'}`}>
          <span className="status-dot" />
          <span>{backendReady ? 'Ready' : 'Offline'}</span>
        </div>
        {!backendReady && (
          <button className="pill pill-icon" onClick={onReconnect} title="Reconnect to backend">
            <RotateCcw size={15} strokeWidth={1.75} />
            <span>Reconnect</span>
          </button>
        )}
      </div>
    </header>
  )
}
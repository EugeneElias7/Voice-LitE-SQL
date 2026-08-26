import { useMemo } from 'react'
import type { PipelineResult, StageStatus } from '../types'
import { FRIENDLY_META } from '../stages'

interface PipelineViewerProps {
  stages: StageStatus[]
  processing: boolean
  result: PipelineResult | null
  onAbort: () => void
}

const ICONS: Record<string, React.ReactNode> = {
  asked: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  understand: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  ),
  find: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
  create: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  ),
  check: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
  run: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  answer: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  ),
}

const SUB_LABELS: Record<string, (result: PipelineResult | null) => string | null> = {
  understand: (r) => r?.nlp?.intent?.primary_intent ?? null,
  find: (r) => r?.retrieval ? `${r.retrieval.retrieved_items.length} items` : null,
  create: (r) => r?.generation?.generated_sql ? 'SQL generated' : null,
  check: (r) => r?.validation?.is_valid !== undefined ? (r.validation.is_valid ? 'Valid' : 'Issues found') : null,
  run: (r) => r?.execution ? `${r.execution.rows?.length ?? 0} rows · ${r.execution.execution_time_ms?.toFixed(1) ?? '?'} ms` : null,
  answer: (r) => r?.final_status === 'success' ? 'Success' : r?.final_status === 'partial' ? 'Partial' : 'Error',
}

export function PipelineViewer({ stages, processing, result, onAbort }: PipelineViewerProps) {
  const friendlyStages = useMemo(() => {
    const keys = ['asked', 'understand', 'find', 'create', 'check', 'run', 'answer']
    return keys.map((key) => {
      const stage = stages.find((s) => s.key === key)
      const meta = FRIENDLY_META.find((m) => m.key === key)
      const isCompleted = stage?.state === 'done'
      const isFailed = stage?.state === 'error'
      const isActive = processing && stage?.state === 'active'
      const isSkipped = stage?.state === 'skipped'

      let state: 'pending' | 'active' | 'done' | 'error' | 'skipped' = 'pending'
      if (isSkipped) state = 'skipped'
      else if (isFailed) state = 'error'
      else if (isCompleted) state = 'done'
      else if (isActive) state = 'active'

      const subLabel = meta?.label ? SUB_LABELS[key]?.(result) ?? meta.label : null

      return {
        key,
        icon: ICONS[key] || null,
        label: meta?.label || key,
        subLabel,
        state,
        latency: stage?.latency_ms ?? null,
      }
    })
  }, [stages, result, processing])

  return (
    <section className="pipeline-viewer" aria-label="Processing pipeline">
      <div className="pipeline-header">
        <h2>Processing</h2>
        {processing && <span className="pipeline-live">● Live</span>}
      </div>

      <div className="pipeline-flow" role="list" aria-label="Pipeline stages">
        {friendlyStages.map((stage, index) => (
          <div key={stage.key} className={`pipeline-step ${stage.state}`} role="listitem">
            <div className="step-connector">
              {index > 0 && <span className={`connector-line ${friendlyStages[index - 1].state === 'done' ? 'done' : ''}`} />}
            </div>
            <div className="step-content">
              <div className={`step-icon ${stage.state}`} aria-hidden="true">
                {stage.icon}
              </div>
              <div className="step-info">
                <span className="step-label">{stage.label}</span>
                {stage.subLabel && <span className="step-sublabel">{stage.subLabel}</span>}
              </div>
              <div className="step-status">
                {stage.state === 'active' && (
                  <span className="working-indicator">
                    <span className="spinner" aria-hidden="true" />
                    Working…
                  </span>
                )}
                {stage.state === 'done' && (
                  <span className="done-indicator" aria-label="Completed">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  </span>
                )}
                {stage.state === 'error' && (
                  <span className="error-indicator" aria-label="Failed">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </span>
                )}
                {stage.state === 'skipped' && (
                  <span className="skipped-indicator" aria-label="Skipped">−</span>
                )}
                {stage.latency !== null && stage.state === 'done' && (
                  <span className="step-latency">{stage.latency.toFixed(1)} ms</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {processing && (
        <button className="abort-btn" onClick={onAbort} aria-label="Abort query">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
          Abort
        </button>
      )}
    </section>
  )
}
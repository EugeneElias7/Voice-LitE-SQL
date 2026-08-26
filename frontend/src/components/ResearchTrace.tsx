import { ChevronDown, FlaskConical } from 'lucide-react'
import type { PipelineResult } from '../types'
import { formatDuration } from '../stages'
import { SQLDisclosure } from './SQLDisclosure'

interface ResearchTraceProps {
  result: PipelineResult
  open: boolean
  onToggle: () => void
}

const STAGES = [
  { key: 'input', label: 'Input' },
  { key: 'normalization', label: 'Phonetic normalization' },
  { key: 'nlp', label: 'NLP intent + entity linking' },
  { key: 'retrieval', label: 'Schema retrieval' },
  { key: 'relationships', label: 'Relationship filtering' },
  { key: 'generation', label: 'SQL generation' },
  { key: 'validation', label: 'Structural validation' },
  { key: 'execution', label: 'Read-only execution' },
  { key: 'correction', label: 'Execution-guided correction' },
  { key: 'answer', label: 'Answer' },
]

function latencyFor(result: PipelineResult, key: string): string {
  const map: Record<string, string> = {
    input: 'received',
    normalization: 'normalization',
    nlp: 'nlp',
    retrieval: 'retrieval',
    relationships: 'nlp',
    generation: 'generation',
    validation: 'validation',
    execution: 'execution',
    correction: 'correction',
    answer: '',
  }
  const stageKey = map[key]
  const ms = stageKey ? result.stage_latencies?.[stageKey] : result.total_latency_ms
  return ms != null ? formatDuration(ms) : ''
}

export function ResearchTrace({ result, open, onToggle }: ResearchTraceProps) {
  const sql = result.final_sql || result.generation?.generated_sql || ''
  const intent = result.nlp?.intent.primary_intent ?? ''
  const entities = result.nlp?.linked_entities ?? []
  const retrieved = result.retrieval?.retrieved_items ?? []

  return (
    <div className="research-trace">
      <div className="research-head">
        <span className="research-head-label" onClick={onToggle} style={{ cursor: 'pointer', flex: 1 }}>
          <FlaskConical size={14} strokeWidth={1.75} />
          Research trace
          {result.total_latency_ms > 0 && (
            <span className="research-head-time">
              {formatDuration(result.total_latency_ms)}
            </span>
          )}
          <ChevronDown
            size={13}
            strokeWidth={1.75}
            style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s ease' }}
          />
        </span>
      </div>

      {open && (
        <div className="research-stages">
          {STAGES.map(stage => (
            <div className="research-stage" key={stage.key}>
              <span className="research-stage-icon">
                <FlaskConical size={14} strokeWidth={1.75} />
              </span>
              <span className="research-stage-label">{stage.label}</span>
              <span className="research-stage-time">{latencyFor(result, stage.key)}</span>
            </div>
          ))}
        </div>
      )}

      {open && (
        <div className="research-details">
          <div className="research-detail-grid">
            {intent && (
              <>
                <span className="research-detail-label">Intent</span>
                <span className="research-detail-value">
                  <span className="tag-chip intent">{intent.replace(/_/g, ' ')}</span>
                </span>
              </>
            )}
            {entities.length > 0 && (
              <>
                <span className="research-detail-label">Entities</span>
                <span className="research-detail-value">
                  {entities.slice(0, 6).map(e => (
                    <span className="tag-chip" key={`${e.table}.${e.column}`}>
                      {e.matched_text} → {e.table}.{e.column}
                    </span>
                  ))}
                </span>
              </>
            )}
            {retrieved.length > 0 && (
              <>
                <span className="research-detail-label">Schema</span>
                <span className="research-detail-value">
                  <span className="tag-chip">{retrieved.length} items retrieved</span>
                </span>
              </>
            )}
            {result.correction && result.correction.total_attempts > 0 && (
              <>
                <span className="research-detail-label">Corrections</span>
                <span className="research-detail-value">
                  <span className="tag-chip">
                    {result.correction.rescued
                      ? 'rescued'
                      : `${result.correction.total_attempts} attempt(s)`}
                  </span>
                </span>
              </>
            )}
          </div>
          {sql && <SQLDisclosure sql={sql} />}
        </div>
      )}
    </div>
  )
}
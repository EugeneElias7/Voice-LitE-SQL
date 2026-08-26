import { useEffect, useState } from 'react'
import { ChevronDown, CheckCircle2 } from 'lucide-react'
import type { PipelineResult, StageStatus } from '../types'
import { buildFriendlyFlow, formatDuration, type FriendlyStageState } from '../stages'

interface ProcessingTraceProps {
  stages: StageStatus[]
  processing: boolean
  mode: 'text' | 'voice'
  question: string
  result: PipelineResult | null
}

const STATE_ICON: Record<FriendlyStageState, string> = {
  waiting: '',
  processing: '…',
  success: '✓',
  failed: '✕',
}

const STAGE_ORDER = ['asked', 'normalization', 'nlp', 'retrieval', 'generation', 'validation', 'execution', 'correction']

export function ProcessingTrace({
  stages,
  processing,
  mode,
  question,
  result,
}: ProcessingTraceProps) {
  const [expanded, setExpanded] = useState(true)
  const [collapsed, setCollapsed] = useState(false)

  const flow = buildFriendlyFlow(stages, processing, mode, result, question)

  // Collapse once processing completes (pill stays).
  useEffect(() => {
    if (!processing && result) {
      setExpanded(false)
      setCollapsed(true)
    }
  }, [processing, result])

  const done = flow.every(s => s.state === 'success' || s.state === 'failed')
  const failed = flow.some(s => s.state === 'failed')
  const totalMs = result?.total_latency_ms ?? null

  // Get current active stage
  const activeStage = flow.find(s => s.state === 'processing')
  const activeIndex = activeStage ? STAGE_ORDER.indexOf(activeStage.key) : -1

  return (
    <div className="trace-wrap">
      {collapsed && done && !expanded && (
        <button className="trace-pill" onClick={() => setExpanded(true)}>
          <CheckCircle2 size={14} strokeWidth={1.75} />
          <span>
            {failed ? 'Answered with an issue' : 'Answered'}
            {result && ` · ${formatDuration(totalMs)}`}
          </span>
          <ChevronDown size={13} strokeWidth={1.75} />
        </button>
      )}

      {expanded && (
        <div className="trace-list">
          {flow.map((step) => {
            const isActive = step.state === 'processing'
            const isPast = STAGE_ORDER.indexOf(step.key) < (activeIndex === -1 ? flow.length : activeIndex)
            const isFuture = STAGE_ORDER.indexOf(step.key) > (activeIndex === -1 ? flow.length : activeIndex)

            return (
              <div
                key={step.key}
                className={`trace-stage ${step.state} ${isActive ? 'active' : ''} ${isPast ? 'done' : ''} ${isFuture ? 'waiting' : ''} ${step.key === 'asked' ? 'asked' : ''}`}
              >
                <span className="trace-dot" />
                <span className="trace-label">{step.label}</span>
                {step.sub && <span className="trace-sub">{step.sub}</span>}
                <span className="trace-state">
                  {isActive ? (
                    <span className="working">
                      <span className="working-dot" />
                      <span className="working-dot" />
                      <span className="working-dot" />
                    </span>
                  ) : (
                    STATE_ICON[step.state]
                  )}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
import { useState } from 'react'
import type { PipelineResult } from '../types'

interface HowItWorkedProps {
  result: PipelineResult
  onOpenTechnical: () => void
}

const STEP_DETAILS: Record<string, { title: string; description: string; getContent: (r: PipelineResult) => React.ReactNode }> = {
  understand: {
    title: '1. Understood your question',
    description: 'Analyzed intent and identified relevant entities',
    getContent: (r) => (
      <div className="step-content">
        <p><strong>Intent:</strong> {r.nlp?.intent?.primary_intent || 'Unknown'}</p>
        <p><strong>Entities found:</strong> {r.nlp?.linked_entities?.map((e) => `${e.table}${e.column ? `.${e.column}` : ''}`).join(', ') || 'None'}</p>
        <p><strong>Concepts:</strong> {r.nlp?.phrase_matches?.filter((p) => p.concept).map((p) => p.concept.replace('concept:', '')).join(', ') || 'None'}</p>
      </div>
    ),
  },
  find: {
    title: '2. Found relevant data',
    description: 'Retrieved schema items matching your question',
    getContent: (r) => (
      <div className="step-content">
        <p><strong>Items retrieved:</strong> {r.retrieval?.retrieved_items?.length ?? 0}</p>
        <ul>
          {r.retrieval?.retrieved_items?.slice(0, 5).map((item, i) => (
            <li key={i}>{item.table}.{item.column} ({item.doc_type})</li>
          ))}
        </ul>
      </div>
    ),
  },
  create: {
    title: '3. Generated SQL',
    description: 'Created a query from the retrieved schema',
    getContent: (r) => (
      <div className="step-content">
        <pre className="sql-preview"><code>{r.generation?.generated_sql || 'No SQL generated'}</code></pre>
      </div>
    ),
  },
  check: {
    title: '4. Validated query',
    description: 'Checked for safety and correctness',
    getContent: (r) => (
      <div className="step-content">
        <p><strong>Valid:</strong> {r.validation?.is_valid ? 'Yes' : 'No'}</p>
        {r.validation?.issues?.length && (
          <>
            <p><strong>Issues:</strong></p>
            <ul>
              {r.validation.issues.map((issue, i) => (
                <li key={i}>{issue.message}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    ),
  },
  run: {
    title: '5. Executed against database',
    description: 'Ran the query and retrieved results',
    getContent: (r) => (
      <div className="step-content">
        <p><strong>Rows returned:</strong> {r.execution?.rows?.length ?? 0}</p>
        <p><strong>Execution time:</strong> {r.execution?.execution_time_ms?.toFixed(1) ?? '?'} ms</p>
        {r.execution?.error && <p className="error"><strong>Error:</strong> {r.execution.error}</p>}
      </div>
    ),
  },
  answer: {
    title: '6. Formatted answer',
    description: 'Generated natural language response',
    getContent: (r) => (
      <div className="step-content">
        <p>{(r as any).answer?.natural || 'No answer generated'}</p>
      </div>
    ),
  },
}

export function HowItWorked({ result, onOpenTechnical }: HowItWorkedProps) {
  const [open, setOpen] = useState(false)

  const steps = [
    { key: 'understand', ...STEP_DETAILS.understand },
    { key: 'find', ...STEP_DETAILS.find },
    { key: 'create', ...STEP_DETAILS.create },
    { key: 'check', ...STEP_DETAILS.check },
    { key: 'run', ...STEP_DETAILS.run },
    { key: 'answer', ...STEP_DETAILS.answer },
  ]

  return (
    <section className="how-it-worked" aria-label="How the answer was generated">
      <button
        type="button"
        className="how-it-worked-trigger"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span className="trigger-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
        </span>
        <span>How did you get this answer?</span>
        <span className="trigger-chevron" aria-hidden="true">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="how-it-worked-panel" role="region" aria-label="Pipeline steps">
          <ol className="steps-list">
            {steps.map((step, index) => (
              <li key={step.key} className="step-item">
                <div className="step-header">
                  <span className="step-number">{index + 1}</span>
                  <div className="step-info">
                    <h4>{step.title}</h4>
                    <p className="step-desc">{step.description}</p>
                  </div>
                </div>
                <div className="step-body">{step.getContent(result)}</div>
              </li>
            ))}
          </ol>
          <div className="technical-link">
            <button type="button" onClick={onOpenTechnical}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="3" width="20" height="14" rx="2" />
                <path d="M8 21h8" />
                <path d="M12 17v4" />
              </svg>
              View technical details
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
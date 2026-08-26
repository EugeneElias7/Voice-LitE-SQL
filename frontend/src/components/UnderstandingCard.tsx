import type { PipelineResult } from '../types'

interface UnderstandingCardProps {
  result: PipelineResult
}

export function UnderstandingCard({ result }: UnderstandingCardProps) {
  if (!result.nlp) return null

  const intent = result.nlp.intent
  const entities = result.nlp.linked_entities ?? []
  const phrases = result.nlp.phrase_matches ?? []

  const intentLabels: Record<string, string> = {
    AGGREGATE: 'Aggregate',
    COUNT: 'Count',
    SUM: 'Sum',
    AVG: 'Average',
    MIN: 'Minimum',
    MAX: 'Maximum',
    LIST: 'List',
    FILTER: 'Filter',
    GROUP_BY: 'Group By',
    ORDER_BY: 'Order By',
    JOIN: 'Join',
    COMPLEX: 'Complex',
  }

  const intentLabel = intentLabels[intent?.primary_intent] || intent?.primary_intent || 'Unknown'

  const entityChips = entities
    .filter((e) => e.table)
    .map((e) => ({
      label: `${e.table}${e.column ? `.${e.column}` : ''}`,
      type: e.entity_type,
      confidence: e.confidence,
    }))
    .slice(0, 5)

  const phraseChips = phrases
    .filter((p) => p.concept)
    .map((p) => p.concept.replace('concept:', '').replace('aggregation:', ''))
    .slice(0, 3)

  return (
    <section className="understanding-card" aria-label="Query understanding">
      <div className="understanding-header">
        <h3>Understanding</h3>
        <span className="confidence-badge">{Math.round((intent?.confidence ?? 0) * 100)}% confident</span>
      </div>

      <div className="understanding-chips">
        <span className="chip intent">{intentLabel}</span>
        {entityChips.map((e, i) => (
          <span key={i} className={`chip entity ${e.type}`} title={`Confidence: ${Math.round(e.confidence * 100)}%`}>
            {e.label}
          </span>
        ))}
        {phraseChips.map((p, i) => (
          <span key={i} className="chip concept">{p}</span>
        ))}
      </div>

      {result.nlp.reranked && (
        <div className="rerank-badge">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="17 1 21 5 17 9" />
            <path d="M3 11V9a4 4 0 0 1 4-4h14" />
            <polyline points="7 23 3 19 7 15" />
            <path d="M21 13v2a4 4 0 0 1-4 4H3" />
          </svg>
          Reranked by relevance
        </div>
      )}

      {result.nlp.filtered_items_count !== undefined && result.nlp.filtered_items_count > 0 && (
        <div className="filter-badge">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
          </svg>
          {result.nlp.filtered_items_count} relevant items after relationship filtering
        </div>
      )}
    </section>
  )
}
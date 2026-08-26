import { useState } from 'react'
import type { PipelineResult } from '../types'
import { highlightSql } from './SqlViewer'

interface TechnicalDetailsProps {
  result: PipelineResult
  onClose: () => void
}

const TABS = [
  { id: 'overview', label: 'Overview', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 9h6v6H9z" /></svg> },
  { id: 'nlp', label: 'NLP', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg> },
  { id: 'schema', label: 'Schema', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" /></svg> },
  { id: 'sql', label: 'SQL', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" /></svg> },
  { id: 'validation', label: 'Validation', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg> },
  { id: 'execution', label: 'Execution', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3" /></svg> },
  { id: 'correction', label: 'Correction', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg> },
] as const

type TabId = typeof TABS[number]['id']

export function TechnicalDetails({ result, onClose }: TechnicalDetailsProps) {
  const [activeTab, setActiveTab] = useState<TabId>('overview')

  const renderTab = (tab: TabId) => {
    const exec = result.execution
    switch (tab) {
      case 'overview':
        return (
          <div className="tab-content">
            <div className="overview-grid">
              <div className="overview-item">
                <h4>Question</h4>
                <p>{result.input?.question || result.question_id || 'N/A'}</p>
              </div>
              <div className="overview-item">
                <h4>Mode</h4>
                <p>{result.input?.mode || 'text'}</p>
              </div>
              <div className="overview-item">
                <h4>Category</h4>
                <p>{result.category || 'N/A'}</p>
              </div>
              <div className="overview-item">
                <h4>Final Status</h4>
                <p><span className={`status-badge ${result.final_status === 'success' ? 'ok' : result.final_status === 'partial' ? 'warn' : 'error'}`}>{result.final_status}</span></p>
              </div>
              <div className="overview-item">
                <h4>Total Latency</h4>
                <p>{result.total_latency_ms.toFixed(1)} ms</p>
              </div>
              <div className="overview-item">
                <h4>Correction Attempts</h4>
                <p>{result.correction?.total_attempts ?? 0}</p>
              </div>
            </div>
            <div className="stage-latencies">
              <h4>Stage Latencies</h4>
              <table>
                <thead><tr><th>Stage</th><th>Latency (ms)</th></tr></thead>
                <tbody>
                  {Object.entries(result.stage_latencies).map(([stage, ms]) => (
                    <tr key={stage}>
                      <td>{stage}</td>
                      <td>{ms.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      case 'nlp':
        return (
          <div className="tab-content">
            {result.nlp && (
              <>
                <div className="detail-section">
                  <h4>Intent Classification</h4>
                  <pre>{JSON.stringify(result.nlp.intent, null, 2)}</pre>
                </div>
                <div className="detail-section">
                  <h4>Linked Entities</h4>
                  <pre>{JSON.stringify(result.nlp.linked_entities, null, 2)}</pre>
                </div>
                <div className="detail-section">
                  <h4>Phrase Matches</h4>
                  <pre>{JSON.stringify(result.nlp.phrase_matches, null, 2)}</pre>
                </div>
                {result.nlp.relationship_decisions?.length && (
                  <div className="detail-section">
                    <h4>Relationship Decisions</h4>
                    <pre>{JSON.stringify(result.nlp.relationship_decisions, null, 2)}</pre>
                  </div>
                )}
              </>
            )}
          </div>
        )
      case 'schema':
        return (
          <div className="tab-content">
            {result.retrieval && (
              <>
                <div className="detail-section">
                  <h4>Retrieved Items ({result.retrieval.retrieved_items.length})</h4>
                  <table>
                    <thead><tr><th>Table</th><th>Column</th><th>Type</th><th>Score</th><th>Distance</th></tr></thead>
                    <tbody>
                      {result.retrieval.retrieved_items.map((item, i) => (
                        <tr key={i}>
                          <td>{item.table}</td>
                          <td>{item.column}</td>
                          <td>{item.doc_type}</td>
                          <td>{item.score.toFixed(4)}</td>
                          <td>{item.distance.toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )
      case 'sql':
        return (
          <div className="tab-content">
            <div className="detail-section">
              <h4>Generated SQL</h4>
              <pre className="sql-code"><code>{highlightSql(result.generation?.generated_sql || '')}</code></pre>
            </div>
            <div className="detail-section">
              <h4>Final SQL</h4>
              <pre className="sql-code"><code>{highlightSql(result.final_sql || '')}</code></pre>
            </div>
            <div className="detail-section">
              <h4>Prompt Length</h4>
              <p>{result.generation?.prompt_length || 0} characters</p>
            </div>
          </div>
        )
      case 'validation':
        return (
          <div className="tab-content">
            {result.validation && (
              <>
                <div className="detail-section">
                  <h4>Validation Result</h4>
                  <p><strong>Valid:</strong> {result.validation.is_valid ? 'Yes' : 'No'}</p>
                  {result.validation.issues?.length && (
                    <>
                      <h4>Issues</h4>
                      <ul>
                        {result.validation.issues.map((issue, i) => (
                          <li key={i}><strong>{issue.severity}:</strong> {issue.message} {issue.location && `(${issue.location})`}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  <p><strong>Tables used:</strong> {result.validation.tables_used?.join(', ')}</p>
                  <p><strong>Has aggregation:</strong> {result.validation.has_aggregation ? 'Yes' : 'No'}</p>
                  <p><strong>Has GROUP BY:</strong> {result.validation.has_group_by ? 'Yes' : 'No'}</p>
                </div>
              </>
            )}
          </div>
        )
      case 'execution':
        return (
          <div className="tab-content">
            {exec && (
              <>
                <div className="detail-section">
                  <h4>Execution Result</h4>
                  <p><strong>Success:</strong> {exec.success ? 'Yes' : 'No'}</p>
                  <p><strong>Rows:</strong> {exec.rows?.length ?? 0}</p>
                  <p><strong>Columns:</strong> {exec.columns?.join(', ')}</p>
                  <p><strong>Execution time:</strong> {exec.execution_time_ms?.toFixed(1) ?? '?'} ms</p>
                  {exec.error && <p className="error"><strong>Error:</strong> {exec.error} ({exec.error_type})</p>}
                </div>
                {(exec.rows?.length ?? 0) > 0 && exec.columns && exec.columns.length > 0 && (
                  <div className="detail-section">
                    <h4>Result Rows (first 20)</h4>
                    <table>
                      <thead>
                        <tr>{exec.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                      </thead>
                      <tbody>
                        {exec.rows.slice(0, 20).map((row, i) => (
                          <tr key={i}>
                            {exec.columns.map((c) => <td key={c}>{JSON.stringify(row[c])}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        )
      case 'correction':
        return (
          <div className="tab-content">
            {result.correction && (
              <>
                <div className="detail-section">
                  <h4>Correction Summary</h4>
                  <p><strong>Total attempts:</strong> {result.correction.total_attempts}</p>
                  <p><strong>Rescued:</strong> {result.correction.rescued ? 'Yes' : 'No'}</p>
                  <p><strong>Harmed:</strong> {result.correction.harmed ? 'Yes' : 'No'}</p>
                  <p><strong>Final correct:</strong> {result.correction.final_correct ? 'Yes' : 'No'}</p>
                </div>
                {result.correction.attempts?.length && (
                  <div className="detail-section">
                    <h4>Correction Attempts</h4>
                    {result.correction.attempts.map((attempt, i) => (
                      <div key={i} className="attempt-card">
                        <div className="attempt-header">
                          <span>Attempt {attempt.attempt_number}</span>
                          <span className={`attempt-status ${attempt.is_correct ? 'correct' : 'incorrect'}`}>
                            {attempt.is_correct ? '✓ Correct' : '✗ Incorrect'}
                          </span>
                        </div>
                        <pre className="sql-code"><code>{highlightSql(attempt.sql)}</code></pre>
                        {attempt.execution_error && (
                          <p className="error">Error: {attempt.execution_error} ({attempt.execution_error_type})</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )
      default:
        return <div>Select a tab</div>
    }
  }

  return (
    <div className="technical-details-modal" role="dialog" aria-modal="true" aria-labelledby="technical-title">
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-content">
        <div className="modal-header">
          <h2 id="technical-title">Technical Details</h2>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="modal-tabs">
          <nav className="tabs-nav" role="tablist">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                role="tab"
                aria-selected={activeTab === tab.id}
                aria-controls={`panel-${tab.id}`}
                id={`tab-${tab.id}`}
                className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.icon}
                <span>{tab.label}</span>
              </button>
            ))}
          </nav>
          <div className="tabs-panels">
            {TABS.map((tab) => (
              <div
                key={tab.id}
                role="tabpanel"
                id={`panel-${tab.id}`}
                aria-labelledby={`tab-${tab.id}`}
                hidden={activeTab !== tab.id}
                className="tab-panel"
              >
                {renderTab(tab.id)}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
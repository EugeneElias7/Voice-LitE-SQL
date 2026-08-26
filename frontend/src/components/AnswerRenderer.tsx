import { useEffect, useRef, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import type { AnswerViewModel } from '../types'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

interface AnswerRendererProps {
  answer: AnswerViewModel
}

function useCountUp(value: number, duration = 700): number {
  const [display, setDisplay] = useState(0)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    const start = performance.now()
    const tick = (now: number) => {
      const progress = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(value * eased))
      if (progress < 1) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [value, duration])

  return display
}

export function AnswerRenderer({ answer }: AnswerRendererProps) {
  const counted = useCountUp(answer.numericValue ?? 0, 700)

  if (answer.type === 'error') {
    return (
      <div className="answer-error">
        <AlertCircle size={16} strokeWidth={1.75} />
        <div className="answer-error-body">
          <h4>{answer.title}</h4>
          <p>{answer.explanation}</p>
        </div>
      </div>
    )
  }

  if (answer.type === 'empty') {
    return (
      <div className="answer-renderer">
        <div className="answer-empty">
          <AlertCircle size={16} strokeWidth={1.75} />
          <p>{answer.explanation}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="answer-renderer">
      {answer.type === 'count' && (
        <div className="answer-kpi">
          <span className="kpi-value highlight">
            {answer.numericValue !== undefined
              ? counted.toLocaleString()
              : answer.title}
          </span>
          {answer.label && <span className="kpi-label">{answer.label}</span>}
        </div>
      )}

      {answer.type === 'single_value' && (
        <div className="answer-kpi">
          <span className="kpi-value highlight">{answer.title}</span>
          {answer.label && <span className="kpi-label">{answer.label}</span>}
        </div>
      )}

      {answer.type === 'top_record' && (
        <div className="answer-kpi top-record">
          <span className="kpi-value">{answer.title}</span>
          {answer.label && <span className="kpi-label">{answer.label}</span>}
        </div>
      )}

      {answer.type === 'multi_value' && (
        <div className="answer-multi">
          {answer.values?.map((entry, index) => (
            <div className="answer-kpi" key={index}>
              <span className="kpi-value highlight">{entry.value}</span>
              {entry.label && <span className="kpi-label">{entry.label}</span>}
            </div>
          ))}
        </div>
      )}

      <p className="answer-explanation">{answer.explanation}</p>

      {answer.type === 'top_record' && answer.primaryValue && (
        <div className="answer-primary-value">{answer.primaryValue}</div>
      )}

      {answer.caption &&
        (answer.type === 'table' ||
          answer.type === 'grouped' ||
          answer.type === 'single_record') && (
          <div className="answer-caption">{answer.caption}</div>
        )}

      {answer.type === 'grouped' && answer.chart && (
        <div className="answer-chart">
          <span className="chart-title">Visualization</span>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={answer.chart.data} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1c2537" />
                <XAxis type="number" tick={{ fill: '#8b96ac', fontSize: 11 }} />
                <YAxis type="category" dataKey={answer.chart.xKey} tick={{ fill: '#8b96ac', fontSize: 11 }} width={140} />
                <Tooltip
                  contentStyle={{
                    background: '#171f2e',
                    border: '1px solid rgba(245,247,252,0.16)',
                    borderRadius: '8px',
                    color: '#f5f7fc',
                    fontSize: '12px',
                  }}
                />
                <Bar dataKey={answer.chart.yKey} fill="#27d3c2" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {(answer.type === 'table' || answer.type === 'grouped' || answer.type === 'single_record') &&
        answer.rows.length > 0 && (
          <div className="answer-table">
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {answer.columns.map(column => (
                      <th key={column}>{column.replace(/_/g, ' ')}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {answer.rows.slice(0, 50).map((row, index) => (
                    <tr key={index}>
                      {answer.columns.map(column => (
                        <td key={column}>{String(row[column] ?? '')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {answer.rows.length > 50 && (
              <div className="table-note">
                Showing first 50 of {answer.rows.length.toLocaleString()} records
              </div>
            )}
          </div>
        )}
    </div>
  )
}
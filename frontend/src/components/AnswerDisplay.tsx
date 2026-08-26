import { useMemo, useState } from 'react'
import type { PipelineResult } from '../types'
import { formatDuration, stageErrorFor } from '../stages'
import { BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'

interface AnswerDisplayProps {
  result: PipelineResult
  onPlayTTS?: (text: string) => void
}

type ResultType = 
  | 'count' 
  | 'sum' 
  | 'avg' 
  | 'min' 
  | 'max' 
  | 'top_record' 
  | 'single_record' 
  | 'grouped' 
  | 'table' 
  | 'empty'
  | 'unknown'

interface ClassifiedResult {
  type: ResultType
  title: string
  primaryValue?: string | number
  primaryLabel?: string
  secondaryValue?: string | number
  secondaryLabel?: string
  summary: string
  columns: string[]
  rows: Record<string, unknown>[]
  showAsKpi: boolean
  showTable: boolean
}

function prettifyColumn(column: string): string {
  const cleaned = column.replace(/_/g, ' ').replace(/\bat\b/g, '')
  return cleaned
    .split(' ')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function formatNumber(val: unknown): string {
  const num = Number(val)
  if (isNaN(num)) return String(val)
  if (num >= 1e6) return (num / 1e6).toFixed(1) + 'M'
  if (num >= 1e3) return (num / 1e3).toFixed(1) + 'K'
  return num.toLocaleString()
}

function detectSqlIntent(sql: string): { 
  hasCount: boolean; 
  hasSum: boolean; 
  hasAvg: boolean; 
  hasMin: boolean; 
  hasMax: boolean; 
  hasGroupBy: boolean; 
  hasOrderBy: boolean; 
  hasLimit: boolean 
} {
  const upper = sql.toUpperCase()
  return {
    hasCount: upper.includes('COUNT('),
    hasSum: upper.includes('SUM('),
    hasAvg: upper.includes('AVG('),
    hasMin: upper.includes('MIN('),
    hasMax: upper.includes('MAX('),
    hasGroupBy: upper.includes('GROUP BY'),
    hasOrderBy: upper.includes('ORDER BY'),
    hasLimit: upper.includes('LIMIT'),
  }
}

function asValue(val: unknown): string | number {
  const num = Number(val)
  return isNaN(num) ? String(val) : num
}

function classifyResult(result: PipelineResult): ClassifiedResult {
  const exec = result.execution
  const columns = exec?.columns ?? []
  const rows = exec?.rows ?? []
  const sql = result.final_sql || result.generation?.generated_sql || ''
  const question = (result.input?.question ?? result.asr?.raw_transcript ?? '').toLowerCase()

  if (!exec || exec.success === false || !rows.length) {
    return {
      type: 'empty',
      title: 'ANSWER',
      summary: 'Your question returned no results.',
      columns,
      rows,
      showAsKpi: false,
      showTable: false,
    }
  }

  const sqlIntent = detectSqlIntent(sql)
  const firstRow = rows[0]
  const colNames = columns

  if (rows.length === 1) {
    if (sqlIntent.hasCount || question.includes('how many') || question.includes('count')) {
      const count = Number(firstRow[colNames[0]]) || 0
      const tableMatch = sql.match(/FROM\s+(\w+)/i)
      const tableName = tableMatch ? tableMatch[1] : colNames[0]?.split('_')[0] || 'records'
      return {
        type: 'count',
        title: 'ANSWER',
        primaryValue: count,
        primaryLabel: tableName.charAt(0).toUpperCase() + tableName.slice(1).replace(/_/g, ' '),
        summary: `There are ${count.toLocaleString()} ${tableName} in the database.`,
        columns,
        rows,
        showAsKpi: true,
        showTable: false,
      }
    }

    if (sqlIntent.hasSum) {
      const sum = Number(firstRow[colNames[0]]) || 0
      const colLabel = prettifyColumn(colNames[0])
      return {
        type: 'sum',
        title: 'ANSWER',
        primaryValue: sum,
        primaryLabel: colLabel,
        summary: `Total ${colLabel.toLowerCase()} is ${formatNumber(sum)}.`,
        columns,
        rows,
        showAsKpi: true,
        showTable: false,
      }
    }

    if (sqlIntent.hasAvg) {
      const avg = Number(firstRow[colNames[0]]) || 0
      const colLabel = prettifyColumn(colNames[0])
      return {
        type: 'avg',
        title: 'ANSWER',
        primaryValue: Math.round(avg),
        primaryLabel: colLabel,
        summary: `The average ${colLabel.toLowerCase()} is ${formatNumber(avg)}.`,
        columns,
        rows,
        showAsKpi: true,
        showTable: false,
      }
    }

    if (sqlIntent.hasMin) {
      const min = Number(firstRow[colNames[0]]) || 0
      const colLabel = prettifyColumn(colNames[0])
      return {
        type: 'min',
        title: 'ANSWER',
        primaryValue: min,
        primaryLabel: colLabel,
        summary: `The lowest ${colLabel.toLowerCase()} is ${formatNumber(min)}.`,
        columns,
        rows,
        showAsKpi: true,
        showTable: false,
      }
    }

    const isTopRecord = sqlIntent.hasMax || (sqlIntent.hasOrderBy && sqlIntent.hasLimit && sql.toUpperCase().includes('DESC'))
    const isBottomRecord = sqlIntent.hasOrderBy && sqlIntent.hasLimit && sql.toUpperCase().includes('ASC') && !sql.toUpperCase().includes('DESC')

    if (isTopRecord || isBottomRecord) {
      let nameCol = colNames.find(c => 
        c.toLowerCase().includes('name') || 
        c.toLowerCase().includes('title') ||
        c.toLowerCase().includes('product') ||
        c.toLowerCase().includes('employee') ||
        c.toLowerCase().includes('customer') ||
        c.toLowerCase().includes('department')
      ) || colNames[0]
      
      let valueCol = colNames.find(c => 
        c !== nameCol && (
          c.toLowerCase().includes('salary') ||
          c.toLowerCase().includes('price') ||
          c.toLowerCase().includes('amount') ||
          c.toLowerCase().includes('avg') ||
          c.toLowerCase().includes('sum') ||
          c.toLowerCase().includes('count') ||
          c.toLowerCase().includes('max') ||
          c.toLowerCase().includes('min') ||
          c.toLowerCase().includes('revenue') ||
          c.toLowerCase().includes('total')
        )
      ) || (colNames[1] || colNames[0])

      const nameVal = asValue(firstRow[nameCol])
      const valueVal = asValue(firstRow[valueCol])
      const nameLabel = prettifyColumn(nameCol)
      const valueLabel = prettifyColumn(valueCol)

      const isSalary = nameCol.toLowerCase().includes('employee') || valueCol.toLowerCase().includes('salary')
      const isProduct = nameCol.toLowerCase().includes('product') || valueCol.toLowerCase().includes('price')
      const isDepartment = nameCol.toLowerCase().includes('department')
      const titlePrefix = isSalary ? 'HIGHEST-PAID EMPLOYEE' : 
                          isProduct ? 'MOST EXPENSIVE PRODUCT' :
                          isDepartment ? 'HIGHEST AVERAGE SALARY' :
                          'TOP RESULT'

      return {
        type: 'top_record',
        title: titlePrefix,
        primaryValue: nameVal,
        primaryLabel: nameLabel,
        secondaryValue: valueVal,
        secondaryLabel: valueLabel,
        summary: `${nameVal} has the ${isTopRecord ? 'highest' : 'lowest'} ${valueLabel.toLowerCase()} at ${typeof valueVal === 'number' ? formatNumber(valueVal) : valueVal}.`,
        columns,
        rows,
        showAsKpi: true,
        showTable: false,
      }
    }

    if (colNames.length > 1) {
      return {
        type: 'single_record',
        title: 'ANSWER',
        primaryValue: asValue(firstRow[colNames[0]]),
        primaryLabel: prettifyColumn(colNames[0]),
        secondaryValue: asValue(firstRow[colNames[1]]),
        secondaryLabel: prettifyColumn(colNames[1]),
        summary: `Found ${colNames.length} columns for this record.`,
        columns,
        rows,
        showAsKpi: false,
        showTable: true,
      }
    }

    return {
      type: 'unknown',
      title: 'ANSWER',
      primaryValue: asValue(firstRow[colNames[0]]),
      primaryLabel: prettifyColumn(colNames[0]),
      summary: `Result: ${formatNumber(firstRow[colNames[0]])}.`,
      columns,
      rows,
      showAsKpi: true,
      showTable: false,
    }
  }

  if (sqlIntent.hasGroupBy) {
    return {
      type: 'grouped',
      title: 'ANSWER',
      summary: `Found ${rows.length} groups.`,
      columns,
      rows,
      showAsKpi: false,
      showTable: true,
    }
  }

  return {
    type: 'table',
    title: 'ANSWER',
    summary: `Found ${rows.length.toLocaleString()} matching record${rows.length === 1 ? '' : 's'}.`,
    columns,
    rows,
    showAsKpi: false,
    showTable: true,
  }
}

function shouldChart(result: PipelineResult): { type: 'bar' | 'line' | 'pie'; xKey: string; yKey: string; data: any[] } | null {
  const exec = result.execution
  if (!exec || exec.success === false || exec.rows.length < 2 || exec.rows.length > 50) return null
  if (exec.columns.length < 2) return null

  const sql = (result.final_sql || result.generation?.generated_sql || '').toUpperCase()
  const hasGroupBy = sql.includes('GROUP BY')
  const hasOrderBy = sql.includes('ORDER BY')

  if (hasGroupBy || (exec.columns.length === 2 && isNaN(Number(exec.rows[0][exec.columns[0]])))) {
    return {
      type: 'bar',
      xKey: exec.columns[0],
      yKey: exec.columns[1],
      data: exec.rows.slice(0, 20),
    }
  }

  if (hasOrderBy && exec.columns.length === 2 && !isNaN(Number(exec.rows[0][exec.columns[0]]))) {
    return {
      type: 'line',
      xKey: exec.columns[0],
      yKey: exec.columns[1],
      data: exec.rows.slice(0, 50),
    }
  }

  if (exec.columns.length === 2 && exec.rows.length <= 8) {
    return {
      type: 'pie',
      xKey: exec.columns[0],
      yKey: exec.columns[1],
      data: exec.rows,
    }
  }

  return null
}

const COLORS = ['#6c8cff', '#9b7cff', '#25d9c2', '#ffb84d', '#ff647c', '#4fd1c5', '#f6ad55', '#9f7aea']

export function AnswerDisplay({ result, onPlayTTS }: AnswerDisplayProps) {
  const [page, setPage] = useState(0)
  const [showChart, setShowChart] = useState(true)
  const [ttsState, setTtsState] = useState<'idle' | 'speaking' | 'paused'>('idle')
  const pageSize = 50

  const execution = result.execution
  const columns = execution?.columns ?? []
  const rows = result?.execution?.rows ?? []
  const failed = execution?.success === false
  const error = stageErrorFor(result)

  const asked = result.input?.question ?? result.asr?.raw_transcript ?? ''
  const classified = useMemo(() => classifyResult(result), [result])
  const chartConfig = useMemo(() => shouldChart(result), [result])

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize))
  const pageRows = rows.slice(page * pageSize, page * pageSize + pageSize)

  const speak = (text: string) => {
    if ('speechSynthesis' in window) {
      speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = 1
      utterance.pitch = 1
      utterance.onstart = () => setTtsState('speaking')
      utterance.onend = () => setTtsState('idle')
      utterance.onerror = () => setTtsState('idle')
      speechSynthesis.speak(utterance)
    } else if (onPlayTTS) {
      onPlayTTS(text)
    }
  }

  const pauseResume = () => {
    if ('speechSynthesis' in window) {
      if (speechSynthesis.speaking && !speechSynthesis.paused) {
        speechSynthesis.pause()
        setTtsState('paused')
      } else if (speechSynthesis.paused) {
        speechSynthesis.resume()
        setTtsState('speaking')
      }
    }
  }

  const stop = () => {
    if ('speechSynthesis' in window) {
      speechSynthesis.cancel()
      setTtsState('idle')
    }
  }

  if (failed || error) {
    return (
      <section className="answer-card" aria-label="Answer">
        {asked && <p className="answer-asked">"{asked}"</p>}
        <div className="answer-failed">
          <div className="answer-kicker">ANSWER</div>
          <h2 className="answer-failed-title">We couldn't get that answer</h2>
          <p className="answer-failed-detail">
            {execution?.error_type ? `${execution.error_type}: ` : ''}
            {execution?.error ?? error}
          </p>
        </div>
      </section>
    )
  }

  const isTopRecord = classified.type === 'top_record'
  const isKpi = classified.showAsKpi

  return (
    <section className="answer-card" aria-label="Answer">
      {asked && <p className="answer-asked">"{asked}"</p>}

      <div className="answer-kicker">{classified.title}</div>

      {isKpi && (
        <div className="answer-hero">
          {isTopRecord ? (
            <>
              <div className="kpi-primary">
                <div className="kpi-primary-value">{classified.primaryValue}</div>
                <div className="kpi-primary-label">{classified.primaryLabel}</div>
              </div>
              {classified.secondaryValue !== undefined && (
                <div className="kpi-secondary">
                  <div className="kpi-secondary-value">{typeof classified.secondaryValue === 'number' ? formatNumber(classified.secondaryValue) : classified.secondaryValue}</div>
                  <div className="kpi-secondary-label">{classified.secondaryLabel}</div>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="kpi-value">{typeof classified.primaryValue === 'number' ? classified.primaryValue.toLocaleString() : classified.primaryValue}</div>
              <div className="kpi-label">{classified.primaryLabel}</div>
            </>
          )}
        </div>
      )}

      <p className="answer-summary">{classified.summary}</p>

      {execution && (
        <p className="answer-meta">
          Real database result · executed in {formatDuration(execution.execution_time_ms)}
        </p>
      )}

      {classified.summary && (
        <div className="answer-tts">
          {ttsState === 'idle' && (
            <button type="button" className="btn btn-tts" onClick={() => speak(classified.summary!)}>
              🔊 Listen
            </button>
          )}
          {ttsState === 'speaking' && (
            <div className="tts-playing">
              <button type="button" className="btn btn-tts playing" onClick={pauseResume}>
                ⏸ Pause
              </button>
              <button type="button" className="btn btn-small btn-ghost" onClick={stop}>
                ■ Stop
              </button>
            </div>
          )}
          {ttsState === 'paused' && (
            <div className="tts-playing">
              <button type="button" className="btn btn-tts" onClick={pauseResume}>
                ▶ Resume
              </button>
              <button type="button" className="btn btn-small btn-ghost" onClick={stop}>
                ■ Stop
              </button>
            </div>
          )}
        </div>
      )}

      {chartConfig && showChart && (
        <div className="chart-container">
          <div className="chart-header">
            <span className="chart-title">Visualization</span>
            <button
              type="button"
              className="btn btn-small btn-ghost"
              onClick={() => setShowChart(false)}
            >
              Hide chart
            </button>
          </div>
          <div className="chart-wrapper" style={{ height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              {chartConfig.type === 'bar' && (
                <BarChart data={chartConfig.data} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#232e45" />
                  <XAxis type="number" tick={{ fill: '#9aa7c2', fontSize: 11 }} />
                  <YAxis
                    type="category"
                    dataKey={chartConfig.xKey}
                    tick={{ fill: '#9aa7c2', fontSize: 11 }}
                    width={120}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#141b2c',
                      border: '1px solid #232e45',
                      borderRadius: '8px',
                      color: '#e9eef7',
                    }}
                  />
                  <Bar dataKey={chartConfig.yKey} fill="#6c8cff" radius={[0, 4, 4, 0]} />
                </BarChart>
              )}
              {chartConfig.type === 'line' && (
                <LineChart data={chartConfig.data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#232e45" />
                  <XAxis dataKey={chartConfig.xKey} tick={{ fill: '#9aa7c2', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#9aa7c2', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      background: '#141b2c',
                      border: '1px solid #232e45',
                      borderRadius: '8px',
                      color: '#e9eef7',
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey={chartConfig.yKey}
                    stroke="#6c8cff"
                    strokeWidth={2}
                    dot={{ fill: '#6c8cff', strokeWidth: 2 }}
                    activeDot={{ r: 6, fill: '#6c8cff' }}
                  />
                </LineChart>
              )}
              {chartConfig.type === 'pie' && (
                <PieChart>
                  <Pie
                    data={chartConfig.data}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    dataKey={chartConfig.yKey}
                    nameKey={chartConfig.xKey}
                    label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
                    labelLine={false}
                  >
                    {chartConfig.data.map((_, i) => (
                      <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: '#141b2c',
                      border: '1px solid #232e45',
                      borderRadius: '8px',
                      color: '#e9eef7',
                    }}
                  />
                  <Legend />
                </PieChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {classified.showTable && rows.length > 0 && (
        <div className="table-wrap">
          <div className="table-header">
            <span className="table-info">{rows.length.toLocaleString()} {rows.length === 1 ? 'record' : 'records'}</span>
            <span className="table-info">Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, rows.length)}</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row, index) => (
                <tr key={index}>
                  {columns.map((column) => (
                    <td key={column}>{String(row[column] ?? '')}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!failed && rows.length > 0 && totalPages > 1 && (
        <div className="pagination">
          <button
            type="button"
            className="btn btn-small"
            disabled={page === 0}
            onClick={() => setPage((v) => v - 1)}
          >
            ‹ Prev
          </button>
          <span>Page {page + 1} of {totalPages}</span>
          <button
            type="button"
            className="btn btn-small"
            disabled={page >= totalPages - 1}
            onClick={() => setPage((v) => v + 1)}
          >
            Next ›
          </button>
        </div>
      )}

      {!failed && rows.length === 0 && (
        <p className="answer-empty">Your question returned no rows.</p>
      )}
    </section>
  )
}
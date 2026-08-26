// One canonical answer presentation model.
// The raw PipelineResult (rows + columns + sql) is converted here into a single
// AnswerViewModel. The UI renders ONLY this model — it never concatenates the
// raw cell, the column label and generated text into multiple answers.

import type { ChartConfig, PipelineResult } from './types'

export type AnswerType =
  | 'count'
  | 'single_value'
  | 'top_record'
  | 'single_record'
  | 'grouped'
  | 'table'
  | 'multi_value'
  | 'empty'
  | 'error'

export interface AnswerViewModel {
  type: AnswerType
  title: string
  primaryValue?: string
  label?: string
  explanation: string
  speechText: string
  caption?: string
  numericValue?: number
  values?: Array<{ label: string; value: string }>
  columns: string[]
  rows: Record<string, unknown>[]
  sql: string
  databaseName: string
  error?: string
  chart?: ChartConfig | null
}

const ROLE_RULES: Array<[RegExp, string]> = [
  [/employee_name|^employee$/i, 'Employee'],
  [/department_name|^department$/i, 'Department'],
  [/product_name|^product$/i, 'Product'],
  [/customer_name|^customer$/i, 'Customer'],
  [/manager_name|^manager$/i, 'Manager'],
  [/city/i, 'City'],
  [/country/i, 'Country'],
  [/region/i, 'Region'],
  [/salary/i, 'Salary'],
  [/price/i, 'Price'],
  [/amount/i, 'Amount'],
  [/revenue/i, 'Revenue'],
  [/cost/i, 'Cost'],
  [/budget/i, 'Budget'],
  [/fee/i, 'Fee'],
  [/^name$/i, 'Name'],
  [/^title$/i, 'Title'],
  [/^count\(/i, 'Count'],
]

const MONEY_RE = /salary|price|amount|revenue|cost|budget|fee|pay|earn/i
const NAME_RE = /name|title|product|employee|customer|department|manager|city/i
const VALUE_RE = /salary|price|amount|revenue|cost|budget|fee|count|avg|sum|total|pay|earn/i

export function prettifyColumn(column: string): string {
  const cleaned = column.replace(/_/g, ' ').replace(/count\(\*\)/i, 'count')
  return cleaned
    .split(' ')
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

export function roleFor(column: string): string {
  for (const [pattern, role] of ROLE_RULES) {
    if (pattern.test(column)) return role
  }
  return prettifyColumn(column)
}

function tableFromSql(sql: string): string {
  const match = sql.match(/FROM\s+(?:["'`]?)([A-Za-z_]\w*)/i)
  return match ? match[1] : ''
}

function tablesFromSql(sql: string): string[] {
  const tables: string[] = []
  const re = /FROM\s+(?:["'`]?)([A-Za-z_]\w*)/gi
  let match: RegExpExecArray | null
  while ((match = re.exec(sql)) !== null) {
    const name = match[1]
    if (!tables.includes(name)) tables.push(name)
  }
  return tables
}

function pluralize(word: string): string {
  if (!word) return 'records'
  if (/s$|ss$|x$|ch$|sh$|y$/i.test(word)) return word
  return `${word}s`
}

function singularize(word: string): string {
  if (word.length > 3 && /s$/.test(word)) return word.slice(0, -1)
  return word
}

function isMoney(column: string): boolean {
  return MONEY_RE.test(column)
}

function formatCell(column: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  const num = Number(value)
  if (Number.isNaN(num) || String(value).trim() === '') return String(value)
  const fractionDigits = num % 1 === 0 ? 0 : 2
  const formatted = num.toLocaleString(undefined, { maximumFractionDigits: fractionDigits })
  return isMoney(column) ? `$${formatted}` : formatted
}

function toSpeech(text: string): string {
  return text
    .replace(/\$([\d,]+(?:\.\d+)?)/g, '$1 dollars')
    .replace(/(\d+(?:\.\d+)?)%/g, '$1 percent')
}

interface SqlIntent {
  hasCount: boolean
  hasAvg: boolean
  hasSum: boolean
  hasMin: boolean
  hasMax: boolean
  hasGroupBy: boolean
  hasOrderBy: boolean
  hasLimit: boolean
}

function detectIntent(sql: string): SqlIntent {
  const upper = sql.toUpperCase()
  return {
    hasCount: upper.includes('COUNT('),
    hasAvg: upper.includes('AVG('),
    hasSum: upper.includes('SUM('),
    hasMin: upper.includes('MIN('),
    hasMax: upper.includes('MAX('),
    hasGroupBy: upper.includes('GROUP BY'),
    hasOrderBy: upper.includes('ORDER BY'),
    hasLimit: upper.includes('LIMIT'),
  }
}

function valueRoleLabel(valueCol: string, intent: SqlIntent): string {
  const role = roleFor(valueCol)
  if (intent.hasAvg) return `Average ${role.toLowerCase()}`
  if (intent.hasSum) return `Total ${role.toLowerCase()}`
  if (intent.hasMin) return `Lowest ${role.toLowerCase()}`
  if (intent.hasMax) return `Highest ${role.toLowerCase()}`
  return role
}

function aggregateExplanation(valueCol: string, value: string, intent: SqlIntent, db: string, table: string): string {
  const role = roleFor(valueCol)
  const entity = singularize(table)
  if (intent.hasAvg) {
    const subject = entity && entity !== role.toLowerCase() ? `${entity} ${role.toLowerCase()}` : role.toLowerCase()
    return `The average ${subject} is ${value}.`
  }
  if (intent.hasSum) return `The total ${role.toLowerCase()} is ${value}.`
  if (intent.hasMin) return `The lowest ${role.toLowerCase()} is ${value}.`
  if (intent.hasMax) return `The highest ${role.toLowerCase()} in ${db} is ${value}.`
  return `${role} is ${value}.`
}

function topRecordExplanation(
  name: string,
  valueCol: string,
  value: string,
  highLow: 'highest' | 'lowest',
  db: string,
): string {
  const role = roleFor(valueCol).toLowerCase()
  return `${name} has the ${highLow} ${role} in the ${db} database, at ${value}.`
}

function topRecordLabel(valueCol: string, highLow: 'highest' | 'lowest'): string {
  const role = roleFor(valueCol).toLowerCase()
  if (role === 'salary') return highLow === 'highest' ? 'Highest-paid employee' : 'Lowest-paid employee'
  if (role === 'price') return highLow === 'highest' ? 'Most expensive product' : 'Cheapest product'
  if (highLow === 'highest') return `Highest ${role}`
  return `Lowest ${role}`
}

function orderByColumn(sql: string): string {
  const match = sql.match(/ORDER\s+BY\s+(?:["'`]?[A-Za-z_]\w*\.)?(["'`]?)([A-Za-z_]\w*)\1/i)
  return match ? match[2] : ''
}

export function buildAnswerViewModel(result: PipelineResult, databaseName: string): AnswerViewModel {
  const exec = result.execution
  const columns = exec?.columns ?? []
  const rows = exec?.rows ?? []
  const sql = result.final_sql || result.generation?.generated_sql || ''
  const db = databaseName || 'your database'
  const table = tableFromSql(sql)

  const base = {
    columns,
    rows,
    sql,
    databaseName: db,
  }

  const failed =
    result.final_status === 'error' || !exec || exec.success === false

  if (failed) {
    const message =
      exec?.error || result.generation?.generated_sql ? '' : 'SQL generation failed'
    return {
      ...base,
      type: 'error' as const,
      title: "Couldn't get that answer",
      explanation: exec?.error || message || 'The pipeline could not produce an answer.',
      speechText: '',
      error: exec?.error || message || undefined,
    }
  }

  if (!rows.length) {
    return {
      ...base,
      type: 'empty' as const,
      title: 'No results',
      explanation: `Your question returned no results in the ${db} database.`,
      speechText: `Your question returned no results in the ${db} database.`,
    }
  }

  const intent = detectIntent(sql)
  const firstRow = rows[0]
  const firstValue = (firstRow[columns[0]] ?? '') as unknown

  // ------------------------------------------------------------------ MULTI
  // A "double question" (e.g. "how many nurses and how many patients")
  // returns several aggregate values: either multiple aggregate columns in a
  // single row, or multiple count rows (UNION). Present all of them instead of
  // only the first.
  const aggregateColumn = (col: string): boolean =>
    /count|total|avg|sum|min|max|number/i.test(col) || /^count\s*\(/i.test(col)
  const multiColumnCase =
    rows.length === 1 && columns.length >= 2 && columns.every(aggregateColumn)
  const multiRowCase =
    rows.length >= 2 && columns.length === 1 && aggregateColumn(columns[0] ?? '')

  if (multiColumnCase || multiRowCase) {
    const tableNames = tablesFromSql(sql)
    const entries: Array<{ label: string; value: string }> = []
    if (multiColumnCase) {
      for (const col of columns) {
        const raw = firstRow[col]
        const value = formatCell(col, raw)
        const label = prettifyColumn(col).replace(/^(Total|Count|Number of)\s+/i, '')
        entries.push({ label, value })
      }
    } else {
      for (let i = 0; i < rows.length; i++) {
        const raw = rows[i][columns[0]]
        const value = formatCell(columns[0], raw)
        const label = pluralize(tableNames[i] || (columns[0] ? columns[0].replace(/[^a-z]/gi, '') : 'records'))
        entries.push({ label, value })
      }
    }

    const labeled = entries.map((e, index) => {
      const lower = e.label.toLowerCase()
      const count = Number(e.value.replace(/[^0-9.]/g, '')) || 0
      const noun = count === 1 ? singularize(lower) : lower
      return index === entries.length - 1 && entries.length > 1
        ? `and ${e.value} ${noun}`
        : `${e.value} ${noun}`
    })
    const explanation = `There are ${labeled.join(' ')} in the ${db} database.`
    const title = entries.length > 1 ? `${entries.length} values` : entries[0]?.value || ''
    return {
      ...base,
      type: 'multi_value' as const,
      title,
      values: entries,
      explanation,
      speechText: toSpeech(explanation),
      caption: entries.map(e => `${e.value} ${e.label.toLowerCase()}`).join(' · '),
    }
  }

  // ------------------------------------------------------------------ COUNT
  if (intent.hasCount || (rows.length === 1 && /^count\(/.test(columns[0] ?? ''))) {
    const count = Number(firstValue) || 0
    const entity = table || (columns[0] ? columns[0].replace(/[^a-z]/gi, '') : 'records')
    const plural = pluralize(entity)
    const label = plural.charAt(0).toUpperCase() + plural.slice(1)
    const explanation = `There are ${count.toLocaleString()} ${plural} in the ${db} database.`
    return {
      ...base,
      type: 'count' as const,
      title: count.toLocaleString(),
      label,
      explanation,
      speechText: toSpeech(explanation),
      numericValue: count,
    }
  }

  // ------------------------------------------- single aggregate value (avg/sum/min/max)
  const isAggregate = intent.hasAvg || intent.hasSum || intent.hasMin || intent.hasMax
  if (isAggregate && rows.length === 1) {
    const value = formatCell(columns[0], firstValue)
    const num = Number(firstValue)
    const label = valueRoleLabel(columns[0], intent)
    const explanation = aggregateExplanation(columns[0], value, intent, db, table)
    return {
      ...base,
      type: 'single_value' as const,
      title: value,
      label,
      explanation,
      speechText: toSpeech(explanation),
      numericValue: Number.isNaN(num) ? undefined : num,
    }
  }

  // ------------------------------------------------------------------ top record
  if (rows.length === 1 && columns.length > 1) {    const hasOrderDesc =
      intent.hasOrderBy && intent.hasLimit && sql.toUpperCase().includes('DESC')
    const hasOrderAsc =
      intent.hasOrderBy && intent.hasLimit && !sql.toUpperCase().includes('DESC')
    const isTop = intent.hasMax || hasOrderDesc
    const isBottom = intent.hasMin || (hasOrderAsc && !hasOrderDesc)

    if (isTop || isBottom) {
      const nameCol =
        columns.find(c => NAME_RE.test(c)) || columns[0]
      const valueCol =
        columns.find(c => c !== nameCol && VALUE_RE.test(c)) || columns.find(c => c !== nameCol) || columns[0]

      const name = String(firstRow[nameCol] ?? '')
      const value = formatCell(valueCol, firstRow[valueCol])
      const highLow: 'highest' | 'lowest' = isTop ? 'highest' : 'lowest'
      const explanation = topRecordExplanation(name, valueCol, value, highLow, db)
      return {
        ...base,
        type: 'top_record' as const,
        title: name,
        primaryValue: value,
        label: topRecordLabel(valueCol, highLow),
        explanation,
        speechText: toSpeech(explanation),
      }
    }
  }

  // --------------------------------------------- top record, single-column result
  // The backend may return only the name column (e.g. SELECT employee_name ... ORDER BY salary DESC LIMIT 1).
  // Infer the ordered value column from the SQL so the record is still presented as a top record.
  if (rows.length === 1 && columns.length === 1 && intent.hasOrderBy && intent.hasLimit) {
    const hasOrderDesc = sql.toUpperCase().includes('DESC')
    const isTop = intent.hasMax || hasOrderDesc
    const isBottom = intent.hasMin || !hasOrderDesc
    const valueCol = orderByColumn(sql)
    const name = String(firstValue ?? '')

    if (isTop || isBottom) {
      const highLow: 'highest' | 'lowest' = isTop ? 'highest' : 'lowest'
      const role = roleFor(valueCol).toLowerCase()
      const explanation = valueCol
        ? `${name} has the ${highLow} ${role} in the ${db} database.`
        : `${name} is the ${highLow}-ranked result in the ${db} database.`
      return {
        ...base,
        type: 'top_record' as const,
        title: name,
        label: valueCol ? topRecordLabel(valueCol, highLow) : `${highLow === 'highest' ? 'Top' : 'Bottom'} result`,
        explanation,
        speechText: toSpeech(explanation),
      }
    }
  }

  // ------------------------------------------------------------------ grouped
  if (intent.hasGroupBy) {
    const caption = `${rows.length.toLocaleString()} ${rows.length === 1 ? 'group' : 'groups'}`
    return {
      ...base,
      type: 'grouped' as const,
      title: caption,
      explanation: `${caption} by ${roleFor(columns[0]).toLowerCase()}.`,
      speechText: `${caption} by ${roleFor(columns[0]).toLowerCase()}.`,
      caption,
      chart: groupedChart(columns, rows),
    }
  }

  // ------------------------------------------------------------------ single record
  if (rows.length === 1) {
    return {
      ...base,
      type: 'single_record' as const,
      title: String(firstRow[columns[0]] ?? ''),
      explanation: `Here is the record you asked about in the ${db} database.`,
      speechText: `Here is the record you asked about in the ${db} database.`,
      caption: '1 record',
    }
  }

  // ------------------------------------------------------------------ table
  const entity = table || (columns[0] ? columns[0].split('_')[0] : 'records')
  const caption = `${rows.length.toLocaleString()} ${pluralize(entity)}`
  const explanation = `Found ${rows.length.toLocaleString()} matching ${pluralize(entity)} in the ${db} database.`
  return {
    ...base,
    type: 'table' as const,
    title: caption,
    explanation,
    speechText: toSpeech(explanation),
    caption,
  }
}

function groupedChart(columns: string[], rows: Record<string, unknown>[]): ChartConfig | null {
  if (columns.length < 2 || rows.length < 2 || rows.length > 50) return null
  const xKey = columns[0]
  const yKey = columns[1]
  const numeric = rows.every(row => !Number.isNaN(Number(row[yKey])))
  if (!numeric) return null
  return { type: 'bar', xKey, yKey, data: rows.slice(0, 20) }
}
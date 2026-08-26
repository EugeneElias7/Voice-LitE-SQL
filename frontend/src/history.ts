export interface HistoryEntry {
  id: string
  mode: 'text' | 'voice'
  question: string
  result: any
  timestamp: string
  database: string
  executionTime?: number
}

const STORAGE_KEY = 'voice-lite-sql-history'

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw)
  } catch {
    return []
  }
}

export function clearHistory(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

export function makeHistoryEntry(
  mode: 'text' | 'voice',
  result: any
): HistoryEntry {
  const question = result.input?.question || result.question_id || 'Unknown'
  const timestamp = new Date().toISOString()
  const database = result.database_name || 'enterprise'
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    mode,
    question,
    result,
    timestamp,
    database,
    executionTime: result.execution?.execution_time_ms,
  }
}
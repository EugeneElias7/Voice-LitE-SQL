import type {
  CorrectionStageData,
  PipelineResult,
  StageState,
  StageStatus,
  ValidationStageData,
} from './types'
import { STAGE_ICONS } from './stageDefs'

export { STAGE_ICONS }

export function stageErrorFor(result: Pick<
  PipelineResult,
  'execution' | 'generation' | 'validation'
>): string | null {
  const execution = result.execution
  const generation = result.generation
  const validation = result.validation
  if (generation && !generation.generated_sql) return 'SQL generation failed'
  if (execution && execution.success === false) return execution.error || 'SQL execution failed'
  if (validation && validation.is_valid === false) return 'SQL validation found issues'
  return null
}

export function correctionSummary(correction: CorrectionStageData | null): string {
  if (!correction) return ''
  if (correction.rescued) return 'rescued'
  if (correction.total_attempts > 0) return `${correction.total_attempts} attempt(s)`
  return ''
}

export function validationChecks(validation: ValidationStageData | null): Array<{
  label: string
  ok: boolean
}> {
  if (!validation) return []
  const unknownTable = validation.issues.some((issue) => issue.code === 'unknown_table')
  const unknownColumn = validation.issues.some((issue) => issue.code === 'unknown_column')
  return [
    { label: 'SELECT / WITH statement', ok: true },
    { label: 'Known tables', ok: !unknownTable },
    { label: 'Known columns', ok: !unknownColumn },
    { label: 'Safe read-only operations', ok: validation.is_valid },
  ]
}

// Derive sequential stage state from completion data.
export function buildStageStatuses(
  stagedefs: Array<{ key: string; label: string; level: string }>,
  completed: Set<string>,
  latencies: Record<string, number>,
  failedKeys: Set<string>,
  running: boolean,
  skipped: Set<string>,
): StageStatus[] {
  const statuses: StageStatus[] = stagedefs.map((def) => ({
    ...def,
    state: 'pending',
    latency_ms: null,
  }))
  const activeIndex = (() => {
    for (let i = 0; i < statuses.length; i++) {
      if (!completed.has(statuses[i].key) && !failedKeys.has(statuses[i].key)) return i
    }
    return -1
  })()
  statuses.forEach((status) => {
    if (failedKeys.has(status.key)) {
      status.state = 'error'
    } else if (completed.has(status.key)) {
      status.state = 'done'
      status.latency_ms = latencies[status.key] ?? null
    } else if (skipped.has(status.key)) {
      status.state = 'skipped'
    } else if (running && status.key === statuses[activeIndex]?.key && activeIndex >= 0) {
      status.state = 'active'
    }
  })
  return statuses
}

// ---------------------------------------------------------------- friendly flow
// Maps the real L9 backend stages onto a small set of user-friendly steps.
// Every state below is derived from the actual pipeline stage states.

export type FriendlyStageState = 'waiting' | 'processing' | 'success' | 'failed'

export interface FriendlyFlowStage {
  key: string
  icon: string
  label: string
  state: FriendlyStageState
  sub?: string
}

export const FRIENDLY_META: Array<{ key: string; icon: string; label: string; level: string; subLabel?: string }> = [
  { key: 'asked', icon: '🎙', label: 'You asked', level: 'L0' },
  { key: 'understand', icon: '🧠', label: 'Understanding', level: 'L6/L8.1' },
  { key: 'find', icon: '🔎', label: 'Finding data', level: 'L7' },
  { key: 'create', icon: '🤖', label: 'Creating SQL', level: 'L3' },
  { key: 'check', icon: '🛡', label: 'Checking', level: 'L4' },
  { key: 'run', icon: '⚡', label: 'Running', level: 'L4' },
  { key: 'answer', icon: '✨', label: 'Answer', level: 'L9' },
]

export const FRIENDLY_STAGES = FRIENDLY_META.map(m => m.key)

export const FRIENDLY_GROUP_KEYS: Record<string, string[]> = {
  asked: [],
  understand: ['normalization', 'nlp'],
  find: ['retrieval'],
  create: ['generation'],
  check: ['validation'],
  run: ['execution'],
  answer: ['correction'],
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return ''
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`
  return `${Math.round(ms)} ms`
}

function humanIntent(intent: string): string {
  const words = intent.toLowerCase().split(/[\s_]+/).filter(Boolean)
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}

function groupState(states: StageState[], empty: 'success' | 'waiting'): FriendlyStageState {
  if (states.length === 0) return empty
  if (states.includes('error')) return 'failed'
  if (states.includes('active')) return 'processing'
  if (states.every((state) => state === 'done' || state === 'skipped')) return 'success'
  return states.some((state) => state === 'done') ? 'processing' : 'waiting'
}

export function buildFriendlyFlow(
  stageStatuses: StageStatus[],
  processing: boolean,
  mode: 'text' | 'voice',
  result: PipelineResult | null,
  question: string,
): FriendlyFlowStage[] {
  const byKey = new Map(stageStatuses.map((stage) => [stage.key, stage.state]))

  const askedKeys = mode === 'voice' ? ['audio', 'asr'] : []
  let answerState: FriendlyStageState = 'waiting'
  if (result) {
    answerState = result.final_status === 'error' ? 'failed' : 'success'
  } else if (processing) {
    const runState = byKey.get('execution') ?? 'pending'
    answerState = runState === 'active' || runState === 'done' ? 'processing' : 'waiting'
  }

  const subFor = (key: string): string | undefined => {
    switch (key) {
      case 'asked': {
        const transcript =
          result?.input?.transcript ?? result?.asr?.raw_transcript ?? ''
        return question || transcript || (mode === 'voice' && !result ? 'Speaking…' : '') || undefined
      }
      case 'understand':
        return result?.nlp
          ? `Intent: ${humanIntent(result.nlp.intent.primary_intent)}`
          : undefined
      case 'find':
        return result?.retrieval
          ? `${result.retrieval.retrieved_items.length} schema item${result.retrieval.retrieved_items.length === 1 ? '' : 's'} found`
          : undefined
      case 'create':
        return result?.generation?.generated_sql ? 'SQL generated' : undefined
      case 'check':
        return result?.validation
          ? result.validation.is_valid
            ? 'Safety checks passed'
            : 'Safety checks flagged an issue'
          : undefined
      case 'run': {
        const execution = result?.execution
        if (!execution) return undefined
        if (execution.success === false) return 'Execution failed'
        const rows = execution.rows.length
        return `${rows} row${rows === 1 ? '' : 's'} · ${formatDuration(execution.execution_time_ms)}`
      }
      case 'answer':
        return result
          ? result.final_status === 'error'
            ? 'Could not produce an answer'
            : `Ready · ${formatDuration(result.total_latency_ms)}`
          : undefined
      default:
        return undefined
    }
  }

  return FRIENDLY_META.map((meta) => {
    const keys =
      meta.key === 'asked' ? askedKeys : FRIENDLY_GROUP_KEYS[meta.key] ?? []
    let state: FriendlyStageState
    if (meta.key === 'answer') {
      state = answerState
    } else {
      const states = keys.map((key) => byKey.get(key) ?? 'pending')
      state = groupState(states, meta.key === 'asked' ? 'success' : 'waiting')
    }
    return {
      key: meta.key,
      icon: meta.icon,
      label: meta.label,
      state,
      sub: subFor(meta.key),
    }
  })
}

export function flowStateText(state: FriendlyStageState): string {
  switch (state) {
    case 'processing':
      return 'Working…'
    case 'success':
      return '✓'
    case 'failed':
      return '✕'
    default:
      return ''
  }
}
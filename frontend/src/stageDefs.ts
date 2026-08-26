import type { StageMeta } from './types'

export const STAGE_META: StageMeta[] = [
  { key: 'audio', label: 'Audio', level: 'L5' },
  { key: 'asr', label: 'Speech Recognition', level: 'L5' },
  { key: 'normalization', label: 'Phonetic Normalization', level: 'L6' },
  { key: 'nlp', label: 'NLP + Intent', level: 'L8.1' },
  { key: 'retrieval', label: 'Schema Retrieval', level: 'L7' },
  { key: 'generation', label: 'Qwen 2.5 SQL Generation', level: 'L3' },
  { key: 'validation', label: 'SQL Validation', level: 'L4' },
  { key: 'execution', label: 'Database Execution', level: 'L4' },
  { key: 'correction', label: 'Execution-Guided Correction', level: 'L8' },
]

export const TEXT_STAGES: StageMeta[] = STAGE_META.filter(
  (stage) => stage.key !== 'audio' && stage.key !== 'asr',
)

export const STAGE_ICONS: Record<string, string> = {
  audio: '🎤',
  asr: '🗣',
  normalization: '🔤',
  nlp: '🧠',
  retrieval: '📚',
  generation: '🤖',
  validation: '🛡',
  execution: '⚡',
  correction: '🔧',
}

export function stageIcon(key: string): string {
  return STAGE_ICONS[key] || '▫'
}
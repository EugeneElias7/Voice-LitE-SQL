// Types mirroring backend.pipeline.pipeline_result.PipelineResult.

export interface TokenDecision {
  original: string
  replacement: string
  confidence: number
  applied: boolean
  strategy: string
  reason: string
  scores: Record<string, unknown>
  candidate: string | null
}

export interface NormalizationStageData {
  original_text: string
  normalized_text: string
  token_decisions: TokenDecision[]
  latency_ms: number
}

export interface IntentData {
  primary_intent: string
  join_required: boolean
  aggregation_required: boolean
  grouping_required: boolean
  ordering_required: boolean
  subquery_likely: boolean
  confidence: number
}

export interface LinkedEntity {
  entity_type: string
  table: string
  column: string
  match_type: string
  matched_text: string
  confidence: number
}

export interface PhraseMatch {
  phrase: string
  entity_type: string
  table: string
  column: string
  match_type: string
  score: number
  concept: string
}

export interface RelationshipDecision {
  source_table: string
  source_column: string
  target_table: string
  target_column: string
  required: boolean
  reason: string
  confidence: number
}

export interface NLPStageData {
  intent: IntentData
  linked_entities: LinkedEntity[]
  phrase_matches: PhraseMatch[]
  reranked: boolean
  relationship_decisions: RelationshipDecision[]
  filtered_items_count: number
  latency_ms: number
}

export interface RetrievedItem {
  doc_type: string
  doc_id: string
  table: string
  column: string
  fk_source_table: string
  fk_source_column: string
  fk_target_table: string
  fk_target_column: string
  text: string
  score: number
  distance: number
  source: string
}

export interface RetrievalStageData {
  query_text: string
  retrieved_items: RetrievedItem[]
  top_k: number
  latency_ms: number
}

export interface GenerationStageData {
  raw_response: string
  generated_sql: string
  prompt_length: number
  latency_ms: number
}

export interface ValidationIssue {
  severity: string
  code: string
  message: string
  location: string | null
}

export interface ValidationStageData {
  is_valid: boolean
  issues: ValidationIssue[]
  tables_used: string[]
  columns_used: string[]
  joins: unknown[]
  has_aggregation: boolean
  has_group_by: boolean
  latency_ms: number
}

export interface ExecutionStageData {
  success: boolean
  rows: Record<string, unknown>[]
  columns: string[]
  error: string | null
  error_type: string | null
  execution_time_ms: number
  latency_ms: number
}

export interface CorrectionAttempt {
  attempt_number: number
  sql: string
  execution_success: boolean
  execution_error: string | null
  execution_error_type: string | null
  execution_time_ms: number
  is_correct: boolean
}

export interface CorrectionStageData {
  attempts: CorrectionAttempt[]
  total_attempts: number
  rescued: boolean
  harmed: boolean
  final_correct: boolean
  latency_ms: number
}

export interface ASRStageData {
  raw_transcript: string
  model_name: string
  wer: number | null
  reference_transcript: string | null
  latency_ms: number
}

export interface AudioStageData {
  audio_path: string
  duration_seconds: number | null
  capture_status: string
  latency_ms: number
}

export interface PipelineResult {
  question_id: string | null
  category: string | null
  reference_sql: string | null
  audio: AudioStageData | null
  asr: ASRStageData | null
  normalization: NormalizationStageData | null
  nlp: NLPStageData | null
  retrieval: RetrievalStageData | null
  generation: GenerationStageData | null
  validation: ValidationStageData | null
  execution: ExecutionStageData | null
  correction: CorrectionStageData | null
  final_sql: string | null
  final_result_rows: Record<string, unknown>[]
  final_correct: boolean
  final_status: string
  stage_latencies: Record<string, number>
  total_latency_ms: number
  started_at: string
  input?: {
    mode: string
    question: string
    transcript: string
    category: string
    received_at: number
  }
}

export interface StageMeta {
  key: string
  label: string
  level: string
}

export type StageState = 'pending' | 'active' | 'done' | 'skipped' | 'error'

export interface StageStatus extends StageMeta {
  state: StageState
  latency_ms: number | null
  error?: string
}

export interface StreamEvent {
  event: string
  [key: string]: unknown
}

export interface SystemStatus {
  backend: { state: string; detail?: string }
  database: { state: string; tables?: number; rows?: number; error?: string }
  ollama: { state: string; host?: string; model?: string; model_loaded?: boolean; models?: string[]; error?: string }
  model: { state: string; name: string; loaded?: boolean }
  whisper: { state: string; model?: string; backend?: string; detail?: string; error?: string }
  chroma: { state: string; index_dir?: string; built?: boolean }
  schema: { state: string }
}

export interface SchemaColumn {
  name: string
  data_type: string
  not_null: boolean
  default_value: unknown
  primary_key_position: number
}

export interface SchemaForeignKey {
  source_column: string
  target_table: string
  target_column: string
  sequence: number
}

export interface SchemaTable {
  name: string
  columns: SchemaColumn[]
  primary_keys: string[]
  foreign_keys: SchemaForeignKey[]
  row_count: number | null
}

export interface SchemaPayload {
  database: string
  path: string
  tables: SchemaTable[]
  total_rows: number
}

export interface DemoQuestion {
  question: string
  category: string
}

// Data Source types
export interface DataSourceDatabase {
  id: string
  path: string
  split: string
}

export interface DataSource {
  id: string
  name: string
  type: 'local' | 'benchmark'
  database?: string
  tables?: number
  rows?: number
  path?: string
  databases?: DataSourceDatabase[]
  database_count?: number
  active: boolean
  error?: string
}

export interface DataSourcesResponse {
  sources: DataSource[]
}

// Model types
export interface OllamaModel {
  name: string
  size: number
  modified_at: string
}

export interface ModelsResponse {
  models: OllamaModel[]
}

// Suggestions
export interface SuggestionsResponse {
  questions: string[]
}

// Upload
export interface UploadResponse {
  ok: boolean
  path: string
  schema: SchemaPayload
}

// Answer formatting types
export interface AnswerData {
  type: 'kpi' | 'table' | 'list' | 'empty'
  title: string
  value?: string | number
  label?: string
  summary?: string
  rows?: Record<string, unknown>[]
  columns?: string[]
  chart?: ChartConfig
}

export type ConversationRole = 'user' | 'assistant'

export interface ConversationMessage {
  id: string
  role: ConversationRole
  question?: string
  answer?: AnswerViewModel
  timestamp: string
  database: string
  executionTime?: number
  result?: PipelineResult
  sql?: string
  mode?: 'text' | 'voice'
}

export interface AnswerViewModel {
  type: 'count' | 'single_value' | 'top_record' | 'single_record' | 'grouped' | 'table' | 'multi_value' | 'empty' | 'error'
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

export interface Conversation {
  id: string
  title: string
  result: PipelineResult | null
  question: string
  timestamp: string
  mode: 'text' | 'voice'
}

export interface ChartConfig {
  type: 'bar' | 'line' | 'pie'
  xKey: string
  yKey: string
  data: Record<string, unknown>[]
}

// TTS
export interface TTSResponse {
  audioUrl: string
}
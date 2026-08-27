// API client for the Voice-LitE-SQL FastAPI backend.
// All processing happens server side: the browser only ever sends a
// natural-language question or audio. SQL is NEVER sent from the browser.

import type {
  DataSourcesResponse,
  DemoQuestion,
  ModelsResponse,
  PipelineResult,
  SchemaPayload,
  StreamEvent,
  SuggestionsResponse,
  SystemStatus,
  UploadResponse,
} from './types'

// Configurable API base with fallback support
const API_BASE = '/api'
let apiBaseOverride: string | null = null

export function setApiBase(base: string | null) {
  apiBaseOverride = base
}

function getApiBase(): string {
  return apiBaseOverride || API_BASE
}

/** Health check with fallback URLs */
async function checkHealth(base: string): Promise<boolean> {
  try {
    const res = await fetch(`${base}/status`, { method: 'GET', signal: AbortSignal.timeout(3000) })
    return res.ok
  } catch {
    return false
  }
}

/** Try multiple base URLs, return first healthy one */
export async function discoverApiBase(fallbacks: string[] = []): Promise<string> {
  const candidates = [getApiBase(), ...fallbacks].filter(Boolean)
  for (const base of candidates) {
    if (await checkHealth(base)) return base
  }
  return getApiBase() // fallback to default even if unhealthy
}

export { getApiBase, checkHealth }

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, init)
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body && body.detail) detail = String(body.detail)
    } catch {
      /* keep default detail */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export function fetchStatus(): Promise<SystemStatus> {
  return fetchJSON<SystemStatus>('/status')
}

export function fetchSchema(): Promise<SchemaPayload> {
  return fetchJSON<SchemaPayload>('/schema')
}

export function fetchDemoQuestions(): Promise<{ questions: DemoQuestion[] }> {
  return fetchJSON<{ questions: DemoQuestion[] }>('/demo-questions')
}

export function runTextQuerySync(question: string): Promise<PipelineResult> {
  return fetchJSON<PipelineResult>('/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

export function runVoiceQuerySync(file: File): Promise<PipelineResult> {
  const form = new FormData()
  form.append('file', file, file.name || 'audio.webm')
  return fetchJSON<PipelineResult>('/voice-query', {
    method: 'POST',
    body: form,
  })
}

function parseSSELine(line: string): StreamEvent | null {
  const text = line.trim()
  if (!text.startsWith('data:')) return null
  const payload = text.slice(5).trim()
  if (!payload) return null
  try {
    return JSON.parse(payload) as StreamEvent
  } catch {
    return null
  }
}

async function streamSSE(
  response: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const body = response.body
  if (!body) throw new Error('streaming unsupported in this browser')
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let newline = buffer.indexOf('\n')
    while (newline >= 0) {
      const line = buffer.slice(0, newline)
      buffer = buffer.slice(newline + 1)
      const event = parseSSELine(line)
      if (event) onEvent(event)
      newline = buffer.indexOf('\n')
    }
  }
  const event = parseSSELine(buffer)
  if (event) onEvent(event)
}

export interface StreamHandle {
  abort: () => void
}

/** Reconnection manager for SSE streams with exponential backoff */
export class StreamReconnector {
  private attempt = 0
  private maxAttempts: number
  private baseDelay: number
  private maxDelay: number
  private running = false
  private abortController: AbortController | null = null

  constructor(
    private readonly connect: (signal: AbortSignal) => Promise<void>,
    private readonly onError: (error: Error) => void,
    options: { maxAttempts?: number; baseDelay?: number; maxDelay?: number } = {}
  ) {
    this.maxAttempts = options.maxAttempts ?? 10
    this.baseDelay = options.baseDelay ?? 1000
    this.maxDelay = options.maxDelay ?? 30000
  }

  start() {
    if (this.running) return
    this.running = true
    this.attempt = 0
    this.loop()
  }

  stop() {
    this.running = false
    this.abortController?.abort()
  }

  private async loop() {
    while (this.running && this.attempt < this.maxAttempts) {
      this.abortController = new AbortController()
      try {
        await this.connect(this.abortController.signal)
        // Connection completed normally
        this.attempt = 0
        break
      } catch (error) {
        if (!this.running || this.abortController?.signal.aborted) break
        this.attempt++
        if (this.attempt >= this.maxAttempts) {
          this.onError(new Error('Max reconnection attempts reached'))
          break
        }
        const delay = Math.min(this.baseDelay * 2 ** (this.attempt - 1), this.maxDelay)
        await this.sleep(delay)
      }
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }
}

export function runTextStream(
  question: string,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Error) => void,
): StreamHandle {
  const controller = new AbortController()
  const run = async () => {
    try {
      const response = await fetch(`${getApiBase()}/query/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await streamSSE(response, onEvent)
    } catch (error) {
      if (controller.signal.aborted) return
      onError(error instanceof Error ? error : new Error(String(error)))
    }
  }
  void run()
  return { abort: () => controller.abort() }
}

export function runVoiceStream(
  file: File,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Error) => void,
): StreamHandle {
  const controller = new AbortController()
  const form = new FormData()
  form.append('file', file, file.name || 'audio.webm')
  const run = async () => {
    try {
      const response = await fetch(`${getApiBase()}/voice-query/stream`, {
        method: 'POST',
        body: form,
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await streamSSE(response, onEvent)
    } catch (error) {
      if (controller.signal.aborted) return
      onError(error instanceof Error ? error : new Error(String(error)))
    }
  }
  void run()
  return { abort: () => controller.abort() }
}

// --- Data Sources ---
export function fetchDataSources(): Promise<DataSourcesResponse> {
  return fetchJSON<DataSourcesResponse>('/datasources')
}

export function selectDataSource(sourceId: string, databaseId?: string): Promise<{ ok: boolean; schema: SchemaPayload }> {
  return fetchJSON<{ ok: boolean; schema: SchemaPayload }>(`/datasources/${sourceId}/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ database_id: databaseId }),
  })
}

export function uploadDatabase(file: File): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file, file.name || 'database.sqlite')
  return fetchJSON<UploadResponse>('/datasources/upload', {
    method: 'POST',
    body: form,
  })
}

// --- Models ---
export function fetchModels(): Promise<ModelsResponse> {
  return fetchJSON<ModelsResponse>('/models')
}

export function selectModel(modelName: string): Promise<{ ok: boolean; model: string }> {
  return fetchJSON<{ ok: boolean; model: string }>('/models/select', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelName }),
  })
}

// --- Suggestions ---
export function fetchSuggestions(): Promise<SuggestionsResponse> {
  return fetchJSON<SuggestionsResponse>('/suggestions')
}

// --- TTS ---
export function textToSpeech(text: string, voice?: string): Promise<Blob> {
  return fetch(`${getApiBase()}/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice }),
  }).then(async (res) => {
    if (!res.ok) throw new Error(`TTS failed: ${res.status}`)
    return res.blob()
  })
}
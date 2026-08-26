import type { StreamEvent } from '../types'

export interface ControlledStream {
  push: (event: StreamEvent) => void
  close: () => void
  response: Response
}

// Returns a Response whose stream is driven imperatively by the test.
export function controllableSSE(): ControlledStream {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })
  const push = (event: StreamEvent) => {
    const payload = `data: ${JSON.stringify(event)}\n\n`
    controller.enqueue(new TextEncoder().encode(payload))
  }
  const close = () => controller.close()
  return { push, close, response: new Response(stream, { status: 200 }) }
}

export function instantSSE(events: StreamEvent[]): Response {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export type FetchMockRoute =
  | { kind: 'json'; body: unknown; status?: number }
  | { kind: 'sse'; events: StreamEvent[] }
  | { kind: 'controlled'; stream: ControlledStream }
  | { kind: 'reject'; error: Error }

export class FetchMock {
  private routes = new Map<string, FetchMockRoute>()

  register(path: string, route: FetchMockRoute) {
    this.routes.set(path, route)
  }

  rejectAll(error: Error) {
    this.routes.set('*', { kind: 'reject', error })
  }

  call = (input: RequestInfo | URL, _init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const path = new URL(url, 'http://localhost').pathname
    let route = this.routes.get(path)
    if (!route) route = this.routes.get('*')
    if (!route) return Promise.reject(new Error(`no mock for ${path}`))
    if (route.kind === 'json') return Promise.resolve(jsonResponse(route.body, route.status))
    if (route.kind === 'sse') return Promise.resolve(instantSSE(route.events))
    if (route.kind === 'controlled') return Promise.resolve(route.stream.response)
    return Promise.reject(route.error)
  }
}

export function flushAsync(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

export async function flushAndWait(ms = 0): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms))
}

export const TEXT_STAGE_KEYS = [
  'normalization',
  'nlp',
  'retrieval',
  'generation',
  'validation',
  'execution',
  'correction',
]

export const STAGE_LABELS: Record<string, string> = {
  normalization: 'Phonetic Normalization',
  nlp: 'NLP + Intent',
  retrieval: 'Schema Retrieval',
  generation: 'Qwen 2.5 SQL Generation',
  validation: 'SQL Validation',
  execution: 'Database Execution',
  correction: 'Execution-Guided Correction',
}
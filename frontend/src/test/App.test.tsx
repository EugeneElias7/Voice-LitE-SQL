import { act, render } from '@testing-library/react'
import { waitFor, screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import {
  averageSalaryResult,
  buildTextRunEvents,
  demoQuestions,
  doubleCountColumnsResult,
  doubleCountRowsResult,
  listEmployeesResult,
  sampleResultResult,
  schemaPayload,
  statusPayload,
  topRecordResult,
  topRecordSingleColumnResult,
} from './fixtures'
import { controllableSSE, FetchMock } from './helpers'

let fetchMock: FetchMock

function standardMocks() {
  fetchMock = new FetchMock()
  fetchMock.register('/api/status', { kind: 'json', body: statusPayload })
  fetchMock.register('/api/schema', { kind: 'json', body: schemaPayload })
  fetchMock.register('/api/demo-questions', { kind: 'json', body: { questions: demoQuestions } })
  fetchMock.register('/api/datasources', {
    kind: 'json',
    body: {
      sources: [
        { id: 'enterprise', name: 'Enterprise', type: 'local', active: true, tables: 2, rows: 9295 },
        { id: 'spider', name: 'Spider', type: 'benchmark', active: false, databases: [{ id: 'concert_singer', path: '', split: 'test' }] },
      ],
    },
  })
  fetchMock.register('/api/models', { kind: 'json', body: { models: [{ name: 'qwen2.5-coder:1.5b', size: 1.5e9, modified_at: '' }] } })
  fetchMock.register('/api/suggestions', { kind: 'json', body: { questions: demoQuestions.map(d => d.question) } })
  vi.stubGlobal('fetch', fetchMock.call)
}

beforeEach(() => {
  window.localStorage.clear()
  standardMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('application shell', () => {
  it('renders the app title, composer and system status', async () => {
    render(<App />)
    expect(screen.getByText('Voice-LitE-SQL')).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/Ask anything about/),
    ).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Ready')).toBeInTheDocument())
  })

it('renders suggestions, database info and tables from the API', async () => {
    render(<App />)
    // Wait for demos to load and suggestions to render
    await waitFor(() => {
      const allText = document.body.textContent || ''
      expect(allText).toContain('How many employees are there')
    }, { timeout: 5000 })
    await waitFor(() => expect(screen.getByText('employees')).toBeInTheDocument(), { timeout: 5000 })
    expect(screen.getByText('departments')).toBeInTheDocument()
  })
})

describe('text query flow', () => {
  it('runs a real pipeline via SSE and renders a semantic answer and SQL', async () => {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })

    render(<App />)
    await user.type(
      screen.getByPlaceholderText(/Ask anything about/),
      'How many employees are there?',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))

await waitFor(() => expect(screen.getByText('You asked')).toBeInTheDocument())

    await act(async () => {
      buildTextRunEvents(sampleResultResult()).forEach((event) => controlled.push(event))
      controlled.close()
    })

    await waitFor(() => {
      const answers = screen.getAllByText('500').filter(el => el.closest('.answer-renderer'))
      expect(answers.length).toBeGreaterThan(0)
    })
    await waitFor(() => {
      const elements = screen.getAllByText(/Employees/i)
      expect(elements.length).toBeGreaterThan(0)
    })
    // Check for explanation text in the answer area
    await waitFor(() => {
      const answerContainer = screen.getAllByText('500').find(el => el.closest('.answer-renderer'))?.closest('.answer-renderer')
      if (answerContainer) {
        expect(answerContainer.textContent).toContain('500 employees')
      }
    })

    await user.click(screen.getByRole('button', { name: 'View SQL' }))
    expect(screen.getByText('Generated SQL')).toBeInTheDocument()
    const sqlCode = screen.getByText('Generated SQL').closest('.sql-disclosure')?.querySelector('.sql-code')
    expect(sqlCode?.textContent).toContain('count(*)')
  })

  it('clears the composer immediately after submitting', async () => {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })

    render(<App />)
    const input = screen.getByPlaceholderText(/Ask anything about/)
    await user.type(input, 'How many employees are there?')
    expect(input).toHaveValue('How many employees are there?')

    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(input).toHaveValue(''))
    expect(screen.getByText('You asked')).toBeInTheDocument()

    await act(async () => controlled.close())
  })

  it('shows a loading trace while the pipeline is running', async () => {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })
    const events = buildTextRunEvents(sampleResultResult())

    render(<App />)
    await user.type(
      screen.getByPlaceholderText(/Ask anything about/),
      'How many employees are there?',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByText('You asked')).toBeInTheDocument())

    await act(async () => {
      controlled.push(events[0]) // pipeline_started with real stage definitions
      controlled.push({ event: 'stage_completed', stage: 'normalization', latency_ms: 5 })
    })

    expect(screen.getByText('Understanding')).toBeInTheDocument()
    expect(document.querySelector('.trace-stage.processing .working')).toBeTruthy()

    await act(async () => controlled.close())
  })

  it('displays an error banner when the pipeline fails', async () => {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })

    render(<App />)
    await user.type(
      screen.getByPlaceholderText(/Ask anything about/),
      'show me the moon',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await act(async () => {
      controlled.push({ event: 'pipeline_error', error: 'SQL generation failed' })
      controlled.close()
    })

    await waitFor(() => expect(screen.getByText('Pipeline error')).toBeInTheDocument())
    expect(screen.getByText('SQL generation failed')).toBeInTheDocument()
  })

  it('spam-clicking Send only submits one request', async () => {
    const user = userEvent.setup()
const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })
    fetchMock.register('/api/voice-query', {
      kind: 'json',
      body: {
        asr: { raw_transcript: 'How many employees are there?', model_name: 'whisper', latency_ms: 100 },
        input: { transcript: 'How many employees are there?' },
        final_status: 'success',
      },
    })
    const fetchSpy = vi.fn(fetchMock.call)
    vi.stubGlobal('fetch', fetchSpy)

    render(<App />)
    await user.type(
      screen.getByPlaceholderText(/Ask anything about/),
      'How many employees are there?',
    )
    const send = screen.getByRole('button', { name: 'Send' })
    await user.click(send)
    await user.click(send)
    await user.click(send)

    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/query/stream',
        expect.anything(),
      ),
    )
    expect(
      fetchSpy.mock.calls.filter(([url]) => url === '/api/query/stream').length,
    ).toBe(1)

    await act(async () => controlled.close())
  })
})

describe('suggestion chips', () => {
  it('inserts question into composer on click, then user clicks Send', async () => {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })

    render(<App />)
    const chip = await screen.findByText('How many employees are there?')
    await user.click(chip)

    // Question should be in composer, not executed yet
    expect(screen.getByPlaceholderText(/Ask anything about/)).toHaveValue('How many employees are there?')
    expect(screen.queryByText('You asked')).not.toBeInTheDocument()

    // User clicks Send
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByText('You asked')).toBeInTheDocument())
    expect(
      screen.getByPlaceholderText(/Ask anything about/),
    ).toHaveValue('')

await act(async () => {
      buildTextRunEvents(sampleResultResult()).forEach((event) => controlled.push(event))
      controlled.close()
    })

    await waitFor(() => {
      const answers = screen.getAllByText('500').filter(el => el.closest('.answer-renderer'))
      expect(answers.length).toBeGreaterThan(0)
    })
  })
})

describe('answer types', () => {
  async function submitResult(result: ReturnType<typeof sampleResultResult>, question: string) {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })
    render(<App />)
    await user.type(
      screen.getByPlaceholderText(/Ask anything about/),
      question,
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await act(async () => {
      buildTextRunEvents(result, question).forEach((event) => controlled.push(event))
      controlled.close()
    })
    return { user, controlled }
  }

it('TOP_RECORD renders a single canonical answer', async () => {
    await submitResult(topRecordResult(), 'Which employee has the highest salary?')

    await waitFor(() => {
      const elements = screen.getAllByText(/Mary Wright/i)
      expect(elements.length).toBeGreaterThan(0)
    })
    expect(screen.getByText('$142,500')).toBeInTheDocument()
    expect(screen.getByText('Highest-paid employee')).toBeInTheDocument()
    expect(
      screen.getByText(/Mary Wright has the highest salary in the Enterprise database/),
    ).toBeInTheDocument()
  })

  it('TOP_RECORD with a single-column result still renders the top record', async () => {
    await submitResult(topRecordSingleColumnResult(), 'Which employee has the highest salary?')

    await waitFor(() => {
      const elements = screen.getAllByText(/Mary Wright/i)
      expect(elements.length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Highest-paid employee')).toBeInTheDocument()
    expect(
      screen.getByText(/Mary Wright has the highest salary in the Enterprise database/),
    ).toBeInTheDocument()
  })

  it('AVG renders a single KPI', async () => {
    await submitResult(averageSalaryResult(), 'What is the average salary?')

    await waitFor(() => expect(screen.getByText('$68,420')).toBeInTheDocument())
    expect(screen.getByText('Average salary')).toBeInTheDocument()
    expect(
      screen.getByText(/The average employee salary is \$68,420/),
    ).toBeInTheDocument()
  })

  it('LIST renders a table, not a count as the headline', async () => {
    await submitResult(listEmployeesResult(), 'List all employees')

    await waitFor(() => expect(screen.getByText('3 employees')).toBeInTheDocument())
expect(screen.getByText('Mary Wright')).toBeInTheDocument()
    expect(screen.getByText('John Smith')).toBeInTheDocument()
    expect(screen.getByText('Alice Johnson')).toBeInTheDocument()
  })

  it('double question with two COUNT columns shows both values in natural language', async () => {
    await submitResult(doubleCountColumnsResult(), 'how many total number of nurses and total patients are there')

    await waitFor(() => {
      const values = screen.getAllByText(/^[34]$/).filter(el => el.closest('.answer-renderer'))
      expect(values.length).toBe(2)
    })
    expect(
      screen.getByText(/There are 3 nurses and 4 patients in the Enterprise database/),
    ).toBeInTheDocument()
  })

  it('double question with UNION count rows shows both values in natural language', async () => {
    await submitResult(doubleCountRowsResult(), 'how many nurses and patients are there')

    await waitFor(() => {
      const values = screen.getAllByText(/^[34]$/).filter(el => el.closest('.answer-renderer'))
      expect(values.length).toBe(2)
    })
    expect(
      screen.getByText(/There are 3 nurses and 4 patients in the Enterprise database/),
    ).toBeInTheDocument()
  })

  it('renders only one Mary Wright title for TOP_RECORD', async () => {
    await submitResult(topRecordResult(), 'Which employee has the highest salary?')
    await waitFor(() => expect(screen.getAllByText('Mary Wright').length).toBe(1))
  })

it('Listen button speaks the clean natural-language answer via backend TTS', async () => {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })
    // Mock TTS endpoint to return an audio blob
    fetchMock.register('/api/tts', {
      kind: 'json',
      body: new Blob(['fake-audio-data'], { type: 'audio/mpeg' }),
    })
    const fetchSpy = vi.fn(fetchMock.call)
    vi.stubGlobal('fetch', fetchSpy)

    render(<App />)
    await user.type(
      screen.getByPlaceholderText(/Ask anything about/),
      'How many employees are there?',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await act(async () => {
      buildTextRunEvents(sampleResultResult()).forEach((event) => controlled.push(event))
      controlled.close()
    })

    await waitFor(() => {
      const answers = screen.getAllByText('500').filter(el => el.closest('.answer-renderer'))
      expect(answers.length).toBeGreaterThan(0)
    })

    await user.click(screen.getByRole('button', { name: 'Listen' }))

    // Verify /api/tts was called with the clean answer text
    await waitFor(() => {
      const ttsCalls = fetchSpy.mock.calls.filter(([url]) => url === '/api/tts')
      expect(ttsCalls.length).toBe(1)
      const init = ttsCalls[0][1] as RequestInit | undefined
      expect(init).toBeDefined()
      const body = init?.body
      expect(body).toBeDefined()
      // The body is a JSON string with the text
      const bodyStr = body ? (body instanceof FormData ? '' : String(body)) : ''
      expect(bodyStr).toContain('500 employees')
    })
  })
})

describe('microphone handling', () => {
  it('shows a clear error when microphone permission is denied', async () => {
    const denied = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    Object.defineProperty(window.navigator, 'mediaDevices', {
      value: { getUserMedia: denied },
      configurable: true,
    })

    const user = userEvent.setup()
    render(<App />)
    const mic = screen.getByRole('button', { name: 'Voice input' })
    await user.click(mic)

    await waitFor(() =>
      expect(screen.getByText(/Microphone permission denied/)).toBeInTheDocument(),
    )
    expect(screen.getByPlaceholderText(/Ask anything about/)).toBeEnabled()
  })

  it('records and transcribes to composer, then user clicks Send', async () => {
    class FakeMediaRecorder {
      static isTypeSupported() {
        return true
      }
      state = 'inactive'
      mimeType = 'audio/webm'
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      start() {
        this.state = 'recording'
      }
      stop() {
        this.state = 'inactive'
        this.ondataavailable?.({ data: new Blob(['audio-bytes'], { type: this.mimeType }) })
        this.onstop?.()
      }
    }

    class FakeSpeechRecognition {
      continuous = false
      interimResults = false
      lang = ''
      maxAlternatives = 1
      onresult: ((event: unknown) => void) | null = null
      onerror: ((event: unknown) => void) | null = null
      onstart: (() => void) | null = null
      onend: (() => void) | null = null
      start() {
        this.onstart?.()
        const event = {
          resultIndex: 0,
          results: [
            {
              isFinal: true,
              0: { transcript: 'How many employees are there?', confidence: 0.9 },
            },
          ],
        }
        this.onresult?.(event)
        this.onend?.()
      }
      stop() {}
    }

    const streamMock = { getTracks: () => [{ stop: vi.fn() }] }
    const getUserMedia = vi.fn().mockResolvedValue(streamMock)
    Object.defineProperty(window.navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
    })
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    Object.defineProperty(window, 'SpeechRecognition', {
      writable: true,
      configurable: true,
      value: FakeSpeechRecognition,
    })

    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })
    const fetchSpy = vi.fn(fetchMock.call)
    vi.stubGlobal('fetch', fetchSpy)

    const user = userEvent.setup()
    render(<App />)
    const mic = screen.getByRole('button', { name: 'Voice input' })
    await user.click(mic)
    await waitFor(() => expect(screen.getByText(/Listening/)).toBeInTheDocument())

    // Stop & Send only stops recording; transcript stays in the composer
    await user.click(screen.getByRole('button', { name: /Stop & Send/ }))

    // The transcript appears in the composer, not auto-submitted
    await waitFor(() => expect(screen.getByPlaceholderText(/Ask anything about/)).toHaveValue('How many employees are there?'))

    // User clicks Send to submit
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/query/stream',
        expect.anything(),
      ),
    )
    await waitFor(() => expect(screen.getByText('You asked')).toBeInTheDocument())
    expect(fetchSpy.mock.calls.filter(([url]) => url === '/api/query/stream').length).toBe(1)

    await act(async () => controlled.close())
  })

  it('pressing Enter while recording stops, then Enter again submits', async () => {
    class FakeMediaRecorder2 {
      static isTypeSupported() {
        return true
      }
      state = 'inactive'
      mimeType = 'audio/webm'
      ondataavailable: ((event: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      start() {
        this.state = 'recording'
      }
      stop() {
        this.state = 'inactive'
        this.ondataavailable?.({ data: new Blob(['audio-bytes'], { type: this.mimeType }) })
        this.onstop?.()
      }
    }

    class FakeSpeechRecognition2 {
      continuous = false
      interimResults = false
      lang = ''
      maxAlternatives = 1
      onresult: ((event: unknown) => void) | null = null
      onerror: ((event: unknown) => void) | null = null
      onstart: (() => void) | null = null
      onend: (() => void) | null = null
      start() {
        this.onstart?.()
        const event = {
          resultIndex: 0,
          results: [
            {
              isFinal: true,
              0: { transcript: 'How many employees are there?', confidence: 0.9 },
            },
          ],
        }
        this.onresult?.(event)
        this.onend?.()
      }
      stop() {}
    }

    const streamMock = { getTracks: () => [{ stop: vi.fn() }] }
    const getUserMedia = vi.fn().mockResolvedValue(streamMock)
    Object.defineProperty(window.navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
    })
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder2)
    Object.defineProperty(window, 'SpeechRecognition', {
      writable: true,
      configurable: true,
      value: FakeSpeechRecognition2,
    })

    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })
    fetchMock.register('/api/voice-query', {
      kind: 'json',
      body: {
        asr: { raw_transcript: 'How many employees are there?', model_name: 'whisper', latency_ms: 100 },
        input: { transcript: 'How many employees are there?' },
        final_status: 'success',
      },
    })
    const fetchSpy = vi.fn(fetchMock.call)
    vi.stubGlobal('fetch', fetchSpy)

    const user = userEvent.setup()
    render(<App />)
    const mic = screen.getByRole('button', { name: 'Voice input' })
    await user.click(mic)
    await waitFor(() => expect(screen.getByText(/Listening/)).toBeInTheDocument())

    // First Enter stops the recording and leaves the transcript in the composer
    await user.keyboard('{Enter}')
    await waitFor(() => expect(screen.getByPlaceholderText(/Ask anything about/)).toHaveValue('How many employees are there?'))
    expect(fetchSpy).not.toHaveBeenCalledWith('/api/query/stream', expect.anything())

    // Second Enter in the composer submits
    await user.keyboard('{Enter}')

    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/query/stream',
        expect.anything(),
      ),
    )
    await waitFor(() => expect(screen.getByText('You asked')).toBeInTheDocument())

    await act(async () => controlled.close())
  })
})

describe('history', () => {
  it('persists a completed query and restores it on click', async () => {
    const user = userEvent.setup()
    const controlled = controllableSSE()
    fetchMock.register('/api/query/stream', { kind: 'controlled', stream: controlled })

    render(<App />)
    await user.type(
      screen.getByPlaceholderText(/Ask anything about/),
      'How many employees are there?',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await act(async () => {
      buildTextRunEvents(sampleResultResult()).forEach((event) => controlled.push(event))
      controlled.close()
    })

    await waitFor(() => expect(screen.getByText('Recent')).toBeInTheDocument())
    const historyItem = (
      await screen.findAllByText(/How many employees are there/)
    ).find(el => el.closest('.history-item'))!
await user.click(historyItem)
    expect(screen.getByText('You')).toBeInTheDocument()
    await waitFor(() => {
      const answers = screen.getAllByText('500').filter(el => el.closest('.answer-renderer'))
      expect(answers.length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Employees')).toBeInTheDocument()
  })
})

describe('api failures', () => {
  it('shows an offline banner when the backend is unreachable', async () => {
    fetchMock = new FetchMock()
    fetchMock.rejectAll(new Error('ECONNREFUSED'))
    vi.stubGlobal('fetch', fetchMock.call)

    render(<App />)
    await waitFor(() => expect(screen.getByText('Backend offline')).toBeInTheDocument())
  })
})

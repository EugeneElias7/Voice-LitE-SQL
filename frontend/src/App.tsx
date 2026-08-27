import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchDataSources, fetchDemoQuestions, fetchModels, fetchSchema, fetchStatus, runTextStream, selectDataSource, selectModel, type StreamHandle, getApiBase } from './api'
import type { DataSource, DemoQuestion, ModelsResponse, PipelineResult, SchemaPayload, StageStatus, StageState, StreamEvent, SystemStatus } from './types'
import { buildAnswerViewModel } from './answerModel'
import { loadHistory, makeHistoryEntry, type HistoryEntry } from './history'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import { ConversationView } from './components/ConversationView'
import { QueryComposer } from './components/QueryComposer'
import { DatabaseExplorerDrawer } from './components/DatabaseExplorerDrawer'
import { ErrorBanner } from './components/ErrorBanner'
import { ProcessingTrace } from './components/ProcessingTrace'
import { TechnicalDetails } from './components/TechnicalDetails'
import { ModelSwitcher } from './components/ModelSwitcher'
import { DatabaseSwitcher } from './components/DatabaseSwitcher'
import { FRIENDLY_STAGES, FRIENDLY_META } from './stages'

const HISTORY_STORAGE_KEY = 'voice-lite-sql-history'

export default function App() {
  const [question, setQuestion] = useState('')
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [schema, setSchema] = useState<SchemaPayload | null>(null)
  const [demos, setDemos] = useState<DemoQuestion[]>([])
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [datasources, setDatasources] = useState<DataSource[]>([])
  const [processing, setProcessing] = useState(false)
  const [completed, setCompleted] = useState<Set<string>>(new Set())
  const [latencies, setLatencies] = useState<Record<string, number>>({})
  const [failedKeys, setFailedKeys] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [permissionError, setPermissionError] = useState<string | null>(null)
  const [showExplorer, setShowExplorer] = useState(false)
  const [showTechnical, setShowTechnical] = useState(false)
  const [showModelSelector, setShowModelSelector] = useState(false)
  const [showDatasourceSelector, setShowDatasourceSelector] = useState(false)
  const [dismissedBackendOffline, setDismissedBackendOffline] = useState(false)
  const [activeDatasourceId, setActiveDatasourceId] = useState<string>('enterprise')
  const [activeDatabase, setActiveDatabase] = useState<string>('')
  const [activeModel, setActiveModel] = useState<string>('qwen2.5-coder:1.5b')
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory())
  const handleRef = useRef<StreamHandle | null>(null)
  const modeRef = useRef<'text' | 'voice'>('text')
  const [pipelineState, setPipelineState] = useState<'idle' | 'listening' | 'understanding' | 'retrieval' | 'generation' | 'validation' | 'execution' | 'answer' | 'error'>('idle')
  const [submitting, setSubmitting] = useState(false)
  const [selectedConversation, setSelectedConversation] = useState<HistoryEntry | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const transition = (newState: typeof pipelineState) => {
    setPipelineState(newState)
  }

  const refreshStatus = useCallback(() => {
    fetchStatus().then(setStatus).catch(() => setStatus(null))
    fetchSchema().then(setSchema).catch(() => undefined)
  }, [])

  const refreshDemos = useCallback(() => {
    fetchDemoQuestions().then((data) => setDemos(data.questions)).catch(() => undefined)
  }, [])

  const refreshModels = useCallback(() => {
    fetchModels().then(setModels).catch(() => undefined)
  }, [])

  const refreshDatasources = useCallback(() => {
    fetchDataSources().then((res) => setDatasources(res.sources)).catch(() => undefined)
  }, [])

  useEffect(() => {
    refreshStatus()
    refreshDemos()
    refreshModels()
    refreshDatasources()
    const timer = window.setInterval(refreshStatus, 15000)
    return () => window.clearInterval(timer)
  }, [refreshStatus, refreshDemos, refreshModels, refreshDatasources])

  const persistHistoryLocal = useCallback((next: HistoryEntry[]) => {
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(next.slice(0, 50)))
    } catch {
      /* storage unavailable */
    }
  }, [])

  const saveHistoryEntry = useCallback(
    (entry: HistoryEntry) => {
      setHistory((previous) => {
        const next = [entry, ...previous.filter((item) => item.id !== entry.id)]
        persistHistoryLocal(next)
        return next
      })
    },
    [persistHistoryLocal],
  )

  const clearHistory = useCallback(() => {
    setHistory([])
    persistHistoryLocal([])
  }, [persistHistoryLocal])

  const resetRun = useCallback(() => {
    setCompleted(new Set())
    setLatencies({})
    setFailedKeys(new Set())
    setResult(null)
    setStreamError(null)
    setPermissionError(null)
    transition('idle')
  }, [transition])

  const handleStreamEvent = useCallback(
    (event: StreamEvent) => {
      switch (event.event) {
        case 'pipeline_started': {
          setCompleted(new Set())
          setLatencies({})
          setFailedKeys(new Set())
          transition('listening')
          break
        }
        case 'stage_completed': {
          const key = event.stage as string
          setCompleted((previous) => {
            const next = new Set(previous)
            next.add(key)
            return next
          })
          setLatencies((previous) => ({ ...previous, [key]: (event.latency_ms as number) ?? 0 }))
          transition(key as any)
          break
        }
        case 'pipeline_completed': {
          const payload = event.result as PipelineResult
          setResult(payload)
          saveHistoryEntry(makeHistoryEntry(modeRef.current, payload))
          setSubmitting(false)
          transition('answer')
          break
        }
        case 'pipeline_error': {
          setStreamError(String(event.error ?? 'pipeline failed'))
          setSubmitting(false)
          transition('error')
          break
        }
        default:
          break
      }
    },
    [saveHistoryEntry, transition],
  )

  const beginTextRun = useCallback(
    (text: string) => {
      if (!text.trim() || processing || submitting) return
      resetRun()
      setSubmitting(true)
      modeRef.current = 'text'
      setProcessing(true)
      setQuestion('') // Clear input immediately after submit
      handleRef.current = runTextStream(
        text.trim(),
        handleStreamEvent,
        (error) => {
          setStreamError(error.message)
          setProcessing(false)
          setSubmitting(false)
          transition('error')
        },
      )
    },
    [handleStreamEvent, processing, resetRun, transition],
  )

  // Transcribe voice file using backend Whisper (sync, returns full pipeline result but we only need ASR transcript)
  const transcribeVoiceFile = useCallback(async (file: File) => {
    try {
      const form = new FormData()
      form.append('file', file, file.name || 'audio.webm')
      const response = await fetch(`${getApiBase()}/voice-query`, {
        method: 'POST',
        body: form,
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const pipelineResult = await response.json() as PipelineResult
      // Extract transcript from ASR stage
      const transcript = pipelineResult.asr?.raw_transcript || pipelineResult.input?.transcript || ''
      return transcript
    } catch (e) {
      console.error('Transcription failed:', e)
      return ''
    }
  }, [])

  // Handle voice file from QueryComposer - transcribe only, don't run full pipeline
  const handleVoiceFile = useCallback(async (file: File) => {
    if (!file || file.size === 0) {
      console.warn('Voice file is empty, skipping transcription')
      return
    }
    console.log('[Voice] Transcribing file:', { size: file.size, type: file.type, name: file.name })
    const transcript = await transcribeVoiceFile(file)
    if (transcript) {
      console.log('[Voice] Transcript received:', transcript)
      setQuestion(transcript)
    } else {
      console.warn('[Voice] No transcript returned from Whisper')
    }
  }, [transcribeVoiceFile])

  useEffect(() => {
    if (processing && (result || streamError)) {
      setProcessing(false)
    }
  }, [result, streamError, processing])

  useEffect(() => {
    if (result && result.final_status === 'error') {
      const keys = new Set<string>()
      if (result.generation && !result.generation.generated_sql) keys.add('generation')
      if (result.execution && result.execution.success === false) keys.add('execution')
      if (keys.size) {
        setFailedKeys((previous) => {
          const next = new Set(previous)
          keys.forEach((key) => next.add(key))
          return next
        })
      }
    }
  }, [result])

  const RAW_STAGE_KEYS = ['normalization', 'nlp', 'retrieval', 'generation', 'validation', 'execution', 'correction'] as const

  const rawStageStatuses: StageStatus[] = useMemo(() => {
    const skipped = new Set<string>()
    if (!processing && result && !result.correction && !completed.has('correction')) {
      skipped.add('correction')
    }
    return RAW_STAGE_KEYS.map((key) => {
      const isCompleted = completed.has(key)
      const isFailed = failedKeys.has(key)
      const isActive = processing && !isCompleted && !isFailed && !skipped.has(key)
      let state: StageState = 'pending'
      if (skipped.has(key)) state = 'skipped'
      else if (isFailed) state = 'error'
      else if (isCompleted) state = 'done'
      else if (isActive) state = 'active'
      return {
        key,
        label: key,
        level: '',
        state,
        latency_ms: latencies[key] ?? null,
        error: isFailed ? 'Failed' : undefined,
      }
    })
  }, [completed, latencies, failedKeys, processing, result])

  const stageStatuses: StageStatus[] = useMemo(() => {
    const skipped = new Set<string>()
    if (!processing && result && !result.correction && !completed.has('correction')) {
      skipped.add('correction')
    }
    return FRIENDLY_STAGES.map((key) => {
      const meta = FRIENDLY_META.find((m) => m.key === key)
      const isCompleted = completed.has(key)
      const isFailed = failedKeys.has(key)
      const isActive = processing && !isCompleted && !isFailed && !skipped.has(key)
      let state: StageState = 'pending'
      if (skipped.has(key)) state = 'skipped'
      else if (isFailed) state = 'error'
      else if (isCompleted) state = 'done'
      else if (isActive) state = 'active'
      return {
        key,
        label: meta?.label || key,
        level: meta?.level || '',
        state,
        latency_ms: latencies[key] ?? null,
        error: isFailed ? 'Failed' : undefined,
      }
    })
  }, [completed, latencies, failedKeys, processing, result])

  const onAbort = useCallback(() => {
    handleRef.current?.abort()
    setProcessing(false)
    setSubmitting(false)
    transition('idle')
  }, [transition])

  const handleSelectConversation = useCallback((entry: HistoryEntry) => {
    setSelectedConversation(entry)
    setQuestion(entry.question)
  }, [])

  const handleNewConversation = useCallback(() => {
    setSelectedConversation(null)
    setQuestion('')
    resetRun()
  }, [resetRun])

  const handleDatasourceSelect = useCallback(async (source: DataSource, databaseId?: string) => {
    try {
      const res = await selectDataSource(source.id, databaseId)
      if (res.ok) {
        setSchema(res.schema)
        setActiveDatasourceId(source.id)
        setActiveDatabase(res.schema.database || '')
        setShowDatasourceSelector(false)
      }
    } catch (e) {
      setStreamError(e instanceof Error ? e.message : 'Failed to switch datasource')
    }
  }, [])

  const handleModelSelect = useCallback(async (modelName: string) => {
    try {
      const res = await selectModel(modelName)
      if (res.ok) {
        setActiveModel(modelName)
        setShowModelSelector(false)
      }
    } catch (e) {
      setStreamError(e instanceof Error ? e.message : 'Failed to switch model')
    }
  }, [])

  const onReconnect = useCallback(() => {
    refreshStatus()
    refreshDemos()
    refreshModels()
    refreshDatasources()
    setDismissedBackendOffline(false)
  }, [refreshStatus, refreshDemos, refreshModels, refreshDatasources])

  const currentDatasource = useMemo(
    () => datasources.find((d) => d.id === activeDatasourceId) ?? datasources[0] ?? null,
    [datasources, activeDatasourceId],
  )

  const activeSource = useMemo(() => {
    if (!currentDatasource) return null
    return {
      ...currentDatasource,
      database: activeDatabase || currentDatasource.database,
    }
  }, [currentDatasource, activeDatabase])
  const backendReady = status?.backend?.state === 'ready'

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(v => !v)}
        conversations={history}
        currentConversationId={selectedConversation?.id ?? null}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        activeSource={activeSource}
        schema={schema}
        onOpenDatabaseExplorer={() => setShowExplorer(true)}
        onClearHistory={clearHistory}
      />

      <main className="main">
        <div className="main-area">
          <TopBar
            activeSource={activeSource}
            sources={datasources}
            currentModel={activeModel}
            models={models?.models ?? []}
            onSelectSource={handleDatasourceSelect}
            onSelectModel={handleModelSelect}
            researchMode={false}
            onToggleResearch={() => {}}
            backendReady={backendReady}
            conversationTitle={selectedConversation ? selectedConversation.question.slice(0, 50) : null}
            onReconnect={() => {}}
          />

          {!backendReady && !dismissedBackendOffline && (
            <div className="backend-offline-banner" role="alert">
              <div className="banner-content">
                <svg className="banner-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="15" y1="9" x2="9" y2="15" />
                  <line x1="9" y1="9" x2="15" y2="15" />
                </svg>
                <div className="banner-text">
                  <strong>Backend offline</strong>
                  <span>Cannot reach the Voice-LitE-SQL API. Start the FastAPI backend on port 8000.</span>
                </div>
                <div className="banner-actions">
                  <button className="banner-dismiss" onClick={() => setDismissedBackendOffline(true)} aria-label="Dismiss">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                  <button className="banner-reconnect" onClick={onReconnect}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 12a9 9 0 0 1-9 9c2.52 0 4.93-1.04 6.74-2.73L3 8l2.27-2.27C7.06 7.13 9.57 8 12 8c4.97 0 9 4.03 9 9z" />
                    </svg>
                    Reconnect
                  </button>
                </div>
              </div>
            </div>
          )}

          {streamError && (
            <ErrorBanner
              title="Pipeline error"
              message={streamError}
              dismissible
              onDismiss={() => setStreamError(null)}
            />
          )}

          <div className="conversation-view-wrapper">
            <ConversationView
              messages={selectedConversation
                ? [
                    { id: `${selectedConversation.id}-user`, role: 'user' as const, question: selectedConversation.question, timestamp: selectedConversation.timestamp, mode: selectedConversation.mode },
                    { id: `${selectedConversation.id}-assistant`, role: 'assistant' as const, question: selectedConversation.question, answer: buildAnswerViewModel(selectedConversation.result, selectedConversation.database), timestamp: selectedConversation.timestamp, database: selectedConversation.database, executionTime: selectedConversation.executionTime, result: selectedConversation.result, sql: selectedConversation.result.final_sql, mode: selectedConversation.mode },
                  ] as import('./types').ConversationMessage[]
                : result
                ? [{ id: String(crypto.randomUUID()), role: 'assistant' as const, question: question, answer: buildAnswerViewModel({ ...result, execution: result.execution }, activeSource?.name ?? ''), timestamp: new Date().toISOString(), database: activeSource?.name ?? '', executionTime: result.execution?.execution_time_ms, result: result, sql: result.final_sql, mode: modeRef.current } as import('./types').ConversationMessage]
                : []}
              processing={processing}
              mode={modeRef.current}
              stageStatuses={rawStageStatuses}
              activeQuestion={question}
              researchMode={false}
              suggestions={demos.map(d => d.question)}
              onAsk={(q: string) => setQuestion(q)}
            />

            {result && (
              <>
                <ProcessingTrace
                  stages={stageStatuses}
                  processing={processing}
                  mode={modeRef.current}
                  question={question}
                  result={result}
                />
              </>
            )}
          </div>

          <QueryComposer
            value={question}
            onChange={setQuestion}
            onSubmit={() => beginTextRun(question)}
            onVoiceFile={handleVoiceFile}
            disabled={processing || submitting}
            processing={processing}
            onAbort={onAbort}
            onPermissionDenied={setPermissionError}
            permissionError={permissionError}
            onPermissionDismiss={() => setPermissionError(null)}
            activeSourceName={activeSource?.database ? `${activeSource.name} / ${activeSource.database}` : activeSource?.name}
          />
        </div>
      </main>

      {showExplorer && (
        <DatabaseExplorerDrawer
          open={showExplorer}
          onClose={() => setShowExplorer(false)}
          schema={schema}
        />
      )}

      {showTechnical && result && (
        <TechnicalDetails result={result} onClose={() => setShowTechnical(false)} />
      )}

      {showModelSelector && (
        <ModelSwitcher
          currentModel={activeModel}
          models={models?.models ?? []}
          onSelectModel={handleModelSelect}
        />
      )}

      {showDatasourceSelector && (
        <DatabaseSwitcher
          activeSource={activeSource}
          sources={datasources}
          onSelectSource={handleDatasourceSelect}
        />
      )}
    </div>
  )
}
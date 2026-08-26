import { useCallback, useEffect, useRef, useState } from 'react'
import { useRecorder } from '../useRecorder'

interface WaveformData {
  data: Float32Array
  sampleRate: number
}

interface QueryInputProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  onVoiceFile: (file: File) => void
  disabled: boolean
  processing: boolean
  onAbort: () => void
  onPermissionDenied: (message: string) => void
  mode: 'text' | 'voice'
  onModeChange: (mode: 'text' | 'voice') => void
  transcript?: string
  activeSource?: string
  currentModel?: string
  isEmptyState?: boolean
}

export function QueryInput({
  value,
  onChange,
  onSubmit,
  onVoiceFile,
  disabled,
  processing,
  onAbort,
  onPermissionDenied,
  mode,
  onModeChange,
  transcript,
  activeSource,
  currentModel,
  isEmptyState = false,
}: QueryInputProps) {
  const recorder = useRecorder(onPermissionDenied)
  const guardRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number | null>(null)
  const [waveform, setWaveform] = useState<WaveformData | null>(null)
  const [showTranscript, setShowTranscript] = useState(false)

  useEffect(() => {
    if (recorder.recording) {
      textareaRef.current?.focus()
      startWaveformAnimation()
    } else {
      stopWaveformAnimation()
    }
  }, [recorder.recording])

  const startWaveformAnimation = useCallback(() => {
    if (!recorder.stream) return
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
    const source = audioContext.createMediaStreamSource(recorder.stream)
    const analyser = audioContext.createAnalyser()
    analyser.fftSize = 256
    const bufferLength = analyser.frequencyBinCount
    const dataArray = new Float32Array(bufferLength)
    source.connect(analyser)

    const draw = () => {
      if (!recorder.recording) return
      analyser.getFloatTimeDomainData(dataArray)
      setWaveform({ data: new Float32Array(dataArray), sampleRate: audioContext.sampleRate })
      ;(window as any).__setAudioAmplitude?.(Math.max(...Array.from(dataArray).map(Math.abs)))
      animationRef.current = requestAnimationFrame(draw)
    }
    draw()
  }, [recorder.recording, recorder.stream])

  const stopWaveformAnimation = useCallback(() => {
    if (animationRef.current) {
      cancelAnimationFrame(animationRef.current)
      animationRef.current = null
    }
    ;(window as any).__setAudioAmplitude?.(0)
    setWaveform(null)
  }, [])

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        if (!disabled) onSubmit()
      }
    },
    [disabled, onSubmit],
  )

  const onPointerDown = useCallback(() => {
    if (disabled) return
    guardRef.current = false
    void recorder.start()
  }, [disabled, recorder])

  const onPointerUp = useCallback(async () => {
    if (guardRef.current) return
    guardRef.current = true
    const file = await recorder.stop()
    if (file) onVoiceFile(file)
  }, [recorder, onVoiceFile])

  const onPointerLeave = useCallback(() => {
    if (recorder.recording) {
      guardRef.current = true
      recorder.cancel()
    }
  }, [recorder])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !waveform) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = canvas.offsetWidth * dpr
    canvas.height = canvas.offsetHeight * dpr
    ctx.scale(dpr, dpr)

    const width = canvas.offsetWidth
    const height = canvas.offsetHeight
    const data = waveform.data

    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = '#6c8cff'

    const barWidth = width / data.length
    for (let i = 0; i < data.length; i++) {
      const value = (data[i] + 1) / 2
      const barHeight = value * height * 0.8
      const x = i * barWidth
      const y = (height - barHeight) / 2
      ctx.fillRect(x, y, Math.max(1, barWidth - 1), barHeight)
    }
  }, [waveform])

  useEffect(() => {
    if (transcript && !showTranscript) {
      setShowTranscript(true)
    } else if (!transcript) {
      setShowTranscript(false)
    }
  }, [transcript])

  const showToolbar = !isEmptyState || (activeSource || currentModel)

  return (
    <div className={`composer ${isEmptyState ? 'composer--empty' : ''}`} role="group" aria-label="Ask a question">
      <div className="composer-input">
        <textarea
          ref={textareaRef}
          className="composer-textarea"
          value={value}
          rows={showTranscript ? 3 : 2}
          placeholder="Ask your database anything…"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled && !recorder.recording}
          readOnly={showTranscript}
        />
        {showTranscript && transcript && (
          <div className="transcript-overlay">
            <span className="transcript-label">You said:</span>
            <span className="transcript-text">"{transcript}"</span>
            <button type="button" className="transcript-dismiss" onClick={() => setShowTranscript(false)} aria-label="Dismiss transcript">✕</button>
          </div>
        )}
      </div>

      {showToolbar && (
        <div className="composer-toolbar">
          <div className="toolbar-left">
            <button
              type="button"
              className={`toolbar-btn ${mode === 'voice' ? 'active' : ''}`}
              onClick={() => onModeChange('voice')}
              disabled={processing || recorder.recording}
              title="Voice input"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 00-3 3v7a3 3 0 006 0V5a3 3 0 00-3-3z" />
                <path d="M19 10v2a7 7 0 01-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="22" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
              <span>Voice</span>
            </button>
            <button
              type="button"
              className={`toolbar-btn ${mode === 'text' ? 'active' : ''}`}
              onClick={() => onModeChange('text')}
              disabled={processing || recorder.recording}
              title="Text input"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="4 7 4 4 20 4 20 7" />
                <line x1="9" y1="20" x2="15" y2="20" />
                <line x1="12" y1="4" x2="12" y2="20" />
              </svg>
              <span>Type</span>
            </button>
          </div>

          <div className="toolbar-center">
            {activeSource && (
              <span className="toolbar-chip">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="2" width="20" height="20" rx="2" />
                  <path d="M6 10h16M6 14h12M6 18h8" />
                </svg>
                <span>{activeSource}</span>
              </span>
            )}
            {currentModel && (
              <span className="toolbar-chip">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="2" width="20" height="20" rx="2" />
                  <path d="M12 8v8M8 12h8" />
                  <circle cx="12" cy="16" r="1" />
                </svg>
                <span>{currentModel.replace(':latest', '')}</span>
              </span>
            )}
          </div>

          <div className="toolbar-right">
            {processing ? (
              <button type="button" className="btn btn-abort" onClick={onAbort}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="2" y="2" width="20" height="20" rx="2" />
                </svg>
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-ask"
                onClick={onSubmit}
                disabled={disabled || !value.trim()}
              >
                <span>Ask</span>
                <svg className="ask-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}

      <div className="composer-mic">
        <button
          type="button"
          className={`mic-button ${recorder.recording ? 'recording' : ''}`}
          onPointerDown={recorder.recording ? undefined : onPointerDown}
          onPointerUp={recorder.recording ? onPointerUp : undefined}
          onPointerLeave={recorder.recording ? onPointerLeave : undefined}
          title={recorder.recording ? 'Release to ask' : 'Hold to speak'}
          aria-label={recorder.recording ? 'Stop recording' : 'Hold to speak'}
          disabled={processing}
        >
          <span className="mic-dot" />
          {recorder.recording ? (
            <span className="mic-count">Listening… ● {String(recorder.elapsed).padStart(2, '0')}</span>
          ) : (
            <>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 00-3 3v7a3 3 0 006 0V5a3 3 0 00-3-3z" />
                <path d="M19 10v2a7 7 0 01-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="22" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
              <span>Hold to speak</span>
            </>
          )}
        </button>

        {recorder.recording && (
          <div className="waveform-container">
            <canvas className="waveform-canvas" ref={canvasRef} />
          </div>
        )}

        <span className="composer-hint">
          {mode === 'voice' ? 'Hold button to record · Release to send' : 'Enter to ask · Shift+Enter for new line'}
        </span>

        <label className="mic-device">
          <select
            className="mic-device-select"
            value={recorder.deviceId}
            onChange={(event) => recorder.setDeviceId(event.target.value)}
            onFocus={() => void recorder.refreshDevices()}
            title="Choose which microphone to use"
            aria-label="Choose microphone"
            disabled={recorder.recording}
          >
            <option value="">Default microphone</option>
            {recorder.devices.map((device, index) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label || `Microphone ${index + 1}`}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  )
}
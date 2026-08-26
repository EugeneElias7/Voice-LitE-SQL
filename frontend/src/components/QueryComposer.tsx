import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, Database, Mic, Plus, Square, X } from 'lucide-react'
import { useRecorder } from '../useRecorder'

interface QueryComposerProps {
  value: string
  onChange: (value: string) => void
  onSubmit: (text: string) => void
  onVoiceFile: (file: File) => void
  disabled: boolean
  processing: boolean
  onAbort: () => void
  onPermissionDenied: (message: string) => void
  activeSourceName?: string
}

export function QueryComposer({
  value,
  onChange,
  onSubmit,
  onVoiceFile,
  disabled,
  processing,
  onAbort,
  onPermissionDenied,
  activeSourceName,
}: QueryComposerProps) {
  const recorder = useRecorder(onPermissionDenied)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const frameRef = useRef<HTMLDivElement>(null)
  const [voiceActive, setVoiceActive] = useState(false)
  const [transcribing, setTranscribing] = useState(false)

  useEffect(() => {
    if (recorder.error) {
      setVoiceActive(false)
      setTranscribing(false)
    }
  }, [recorder.error])

  // Sync real-time transcript to composer value
  useEffect(() => {
    if (voiceActive && (recorder.transcript || recorder.interimTranscript)) {
      const fullTranscript = recorder.transcript + (recorder.transcript && recorder.interimTranscript ? ' ' : '') + recorder.interimTranscript
      onChange(fullTranscript)
    }
  }, [recorder.transcript, recorder.interimTranscript, voiceActive, onChange])

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        if (!disabled && value.trim()) onSubmit(value)
      }
    },
    [disabled, onSubmit, value],
  )

  const autoGrow = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [])

  useEffect(() => {
    autoGrow()
  }, [value, autoGrow])

  const startVoice = useCallback(async () => {
    if (processing || disabled) return
    setVoiceActive(true)
    setTranscribing(false)
    await recorder.start()
  }, [recorder, processing, disabled])

  const cancelVoice = useCallback(() => {
    recorder.cancel()
    setVoiceActive(false)
    setTranscribing(false)
  }, [recorder])

  const stopVoice = useCallback(async () => {
    if (transcribing) return
    setTranscribing(true)
    const file = await recorder.stop()
    if (file) {
      onVoiceFile(file)
    }
    setVoiceActive(false)
    setTranscribing(false)
    requestAnimationFrame(() => textareaRef.current?.focus())
  }, [recorder, transcribing, onVoiceFile])

  // While voice recording, Enter just stops the recording. The transcript
  // stays in the composer, and the user presses Enter again (or clicks Send)
  // in the normal input to submit.
  useEffect(() => {
    if (!voiceActive) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        const target = event.target as HTMLElement | null
        const isEditable =
          target instanceof HTMLInputElement ||
          target instanceof HTMLTextAreaElement ||
          target?.isContentEditable
        if (isEditable) return
        event.preventDefault()
        event.stopPropagation()
        void stopVoice()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [voiceActive, stopVoice])

  const canSend = value.trim().length > 0 && !disabled

  return (
    <div className="query-composer">
      <div className="composer-frame" ref={frameRef}>
        {voiceActive ? (
          <div className="composer-voice">
            <div className="voice-status">
              <span className="rec-dot" />
              {transcribing ? 'Transcribing…' : `Listening… ${String(recorder.elapsed).padStart(2, '0')}`}
            </div>
            {recorder.devices.length > 1 && (
              <div className="voice-device-selector">
                <label>
                  <span>Microphone:</span>
                  <select
                    value={recorder.deviceId}
                    onChange={(e) => recorder.setDeviceId(e.target.value)}
                    disabled={recorder.recording}
                    aria-label="Select microphone"
                  >
                    <option value="">Default</option>
                    {recorder.devices.map((device, index) => (
                      <option key={device.deviceId} value={device.deviceId}>
                        {device.label || `Microphone ${index + 1}`}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            <div className="voice-wave" aria-hidden="true">
              {Array.from({ length: 5 }).map((_, i) => (
                <span key={i} className="voice-bar" style={{ animationDelay: `${i * 80}ms` }} />
              ))}
            </div>
            <div className="voice-actions">
              <button className="voice-btn danger" onClick={cancelVoice}>
                <X size={15} strokeWidth={1.75} />
                Cancel
              </button>
              <button className="voice-btn primary" onClick={stopVoice} disabled={transcribing}>
                <Mic size={15} strokeWidth={1.75} />
                {transcribing ? 'Transcribing…' : 'Stop & Send'}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="composer-input-row">
              <button
                type="button"
                className="composer-icon-btn"
                title="Add attachment"
                disabled={processing}
              >
                <Plus size={18} strokeWidth={1.75} />
              </button>
              <textarea
                ref={textareaRef}
                className="composer-textarea"
                value={value}
                rows={1}
                placeholder={`Ask anything about ${activeSourceName || 'your database'}…`}
                onChange={event => {
                  onChange(event.target.value)
                  autoGrow()
                }}
                onKeyDown={handleKeyDown}
                disabled={disabled}
              />
              <button
                type="button"
                className="composer-icon-btn voice"
                onClick={startVoice}
                disabled={processing}
                aria-label="Voice input"
                title="Voice input"
              >
                <Mic size={18} strokeWidth={1.75} />
              </button>
              {processing ? (
                <button
                  type="button"
                  className="composer-icon-btn"
                  onClick={onAbort}
                  title="Stop"
                  aria-label="Stop"
                >
                  <Square size={16} strokeWidth={1.75} />
                </button>
              ) : (
                <button
                  type="button"
                  className="composer-icon-btn primary"
                  onClick={() => canSend && onSubmit(value)}
                  disabled={!canSend}
                  aria-label="Send"
                  title="Send"
                >
                  <ArrowUp size={18} strokeWidth={1.75} />
                </button>
              )}
            </div>
            <div className="composer-footer">
              {activeSourceName && (
                <span className="composer-chip">
                  <Database size={13} strokeWidth={1.75} />
                  {activeSourceName}
                </span>
              )}
              <span className="composer-hint">
                Enter to ask · Shift+Enter for new line
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
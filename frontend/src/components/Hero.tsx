import { useRef, useState, useEffect, useCallback } from 'react'
import type { DemoQuestion } from '../types'
import { VoiceButton } from './VoiceButton'

interface HeroProps {
  question: string
  onChange: (value: string) => void
  onSubmit: () => void
  onVoiceFile: (file: File) => void
  disabled: boolean
  processing: boolean
  onAbort: () => void
  onPermissionDenied: (message: string) => void
  suggestions: DemoQuestion[]
}

export function Hero({
  question,
  onChange,
  onSubmit,
  onVoiceFile,
  disabled,
  processing,
  onAbort,
  onPermissionDenied,
  suggestions,
}: HeroProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isComposing, setIsComposing] = useState(false)

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
        e.preventDefault()
        if (!disabled) onSubmit()
      }
    },
    [disabled, onSubmit, isComposing],
  )

  const handleCompositionStart = () => setIsComposing(true)
  const handleCompositionEnd = (e: React.CompositionEvent<HTMLTextAreaElement>) => {
    setIsComposing(false)
    onChange(e.currentTarget.value)
  }

  const autoResize = useCallback(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [question])

  useEffect(autoResize, [question, autoResize])

  return (
    <div className="composer" role="group" aria-label="Ask a question">
      <div className="composer-row">
        <textarea
          ref={textareaRef}
          className="composer-textarea"
          value={question}
          rows={2}
          placeholder="Ask a question about your data…"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          disabled={disabled && !processing}
          aria-label="Your question"
        />
        {processing ? (
          <button
            type="button"
            className="btn btn-abort"
            onClick={onAbort}
            aria-label="Stop processing"
          >
            <span className="btn-icon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            </span>
            Stop
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-ask"
            onClick={onSubmit}
            disabled={disabled || !question.trim()}
            aria-label="Submit question"
          >
            <span className="btn-text">Ask</span>
            <span className="btn-icon ask-arrow" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </span>
          </button>
        )}
      </div>

      <div className="composer-footer">
        <VoiceButton
          onVoiceFile={onVoiceFile}
          disabled={disabled || processing}
          onPermissionDenied={onPermissionDenied}
          processing={processing}
        />

        <div className="suggestions" role="list" aria-label="Suggested questions">
          <span className="suggestions-label">Try asking:</span>
          <ul className="suggestions-list">
            {suggestions.slice(0, 4).map((q, i) => (
              <li key={i} role="listitem">
                <button
                  type="button"
                  className="suggestion-chip"
                  onClick={() => onChange(q.question)}
                  disabled={disabled || processing}
                >
                  {q.question}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <span className="composer-hint">Enter to ask · Shift+Enter for new line</span>
      </div>
    </div>
  )
}
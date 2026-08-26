import { useEffect, useState } from 'react'
import { fetchSuggestions } from '../api'
import type { DemoQuestion } from '../types'

interface SuggestionsProps {
  questions: DemoQuestion[]
  onPick: (question: string) => void
  disabled: boolean
  schema?: any
}

export function Suggestions({ questions, onPick, disabled, schema }: SuggestionsProps) {
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // Start with demo questions
    const initial = questions.slice(0, 4).map(q => q.question)
    setSuggestions(initial)

    // Fetch schema-aware suggestions
    if (!schema) return
    setLoading(true)
    fetchSuggestions().then(res => {
      setSuggestions(prev => [...new Set([...prev, ...res.questions])].slice(0, 6))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [questions, schema])

  if (suggestions.length === 0) return null

  return (
    <div className="suggestions" role="group" aria-label="Example questions">
      <span className="suggestions-title">Try asking</span>
      <div className="suggestions-list">
        {suggestions.map(q => (
          <button
            key={q}
            type="button"
            className="suggestion"
            disabled={disabled || loading}
            onClick={() => onPick(q)}
            title="Insert into composer"
          >
            “{q}”
          </button>
        ))}
        {loading && <span className="suggestion loading">…</span>}
      </div>
    </div>
  )
}
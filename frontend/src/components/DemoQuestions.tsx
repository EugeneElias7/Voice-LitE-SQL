import type { DemoQuestion } from '../types'

interface DemoQuestionsProps {
  questions: DemoQuestion[]
  onPick: (question: string) => void
  disabled: boolean
}

const MAX_SUGGESTIONS = 4

export function DemoQuestions({ questions, onPick, disabled }: DemoQuestionsProps) {
  const suggestions = questions.slice(0, MAX_SUGGESTIONS)
  if (!suggestions.length) return null

  return (
    <div className="suggestions" role="group" aria-label="Example questions">
      <span className="suggestions-title">Try asking</span>
      <div className="suggestions-list">
        {suggestions.map((demo) => (
          <button
            type="button"
            key={demo.question}
            className="suggestion"
            disabled={disabled}
            onClick={() => onPick(demo.question)}
            title="Fill in the question"
          >
            “{demo.question}”
          </button>
        ))}
      </div>
    </div>
  )
}
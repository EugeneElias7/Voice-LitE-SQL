import { useEffect, useRef, useState } from 'react'
import { Braces, FlaskConical, Sparkles, Square, Volume2 } from 'lucide-react'
import type { ConversationMessage, StageStatus } from '../types'
import { AnswerRenderer } from './AnswerRenderer'
import { ProcessingTrace } from './ProcessingTrace'
import { ResearchTrace } from './ResearchTrace'
import { SQLDisclosure } from './SQLDisclosure'
import { useSpeech } from '../useSpeech'

interface ConversationViewProps {
  messages: ConversationMessage[]
  processing: boolean
  mode: 'text' | 'voice'
  stageStatuses: StageStatus[]
  activeQuestion: string
  researchMode: boolean
  suggestions: string[]
  onAsk: (question: string) => void
}

export function ConversationView({
  messages,
  processing,
  mode,
  stageStatuses,
  activeQuestion,
  researchMode,
  suggestions,
  onAsk,
}: ConversationViewProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages, processing, activeQuestion])

  const empty = messages.length === 0 && !processing

  return (
    <div className="conversation-view">
      {empty ? (
        <EmptyConversation onAsk={onAsk} suggestions={suggestions} />
      ) : (
        <div className="conversation-messages">
          {messages.map(message =>
            message.role === 'user' ? (
              <UserMessage key={message.id} message={message} />
            ) : (
              <AssistantMessage
                key={message.id}
                message={message}
                researchMode={researchMode}
              />
            ),
          )}

          {processing && (
            <ProcessingTrace
              stages={stageStatuses}
              processing={processing}
              mode={mode}
              question={activeQuestion}
              result={null}
            />
          )}

          <div ref={messagesEndRef} />
        </div>
      )}
    </div>
  )
}

function EmptyConversation({
  onAsk,
  suggestions,
}: {
  onAsk: (q: string) => void
  suggestions: string[]
}) {
  return (
    <div className="empty-conversation">
      <div className="empty-spark">
        <Sparkles size={20} strokeWidth={1.75} />
      </div>
      <h1 className="empty-title">Ask your data anything</h1>
      <p className="empty-subtitle">
        Query your database using natural language or your voice.
      </p>
      <div className="empty-suggestions">
        <span className="empty-suggestions-label">Try asking</span>
        {suggestions.map(s => (
          <button key={s} className="empty-suggestion" onClick={() => onAsk(s)}>
            <Sparkles size={14} strokeWidth={1.75} />
            <span>{s}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function UserMessage({ message }: { message: ConversationMessage }) {
  return (
    <div className="message user-message">
      <div className="message-content">
        <div className="message-role-label">You</div>
        <div className="user-bubble">
          {message.question || (message.mode === 'voice' ? 'Voice query' : '')}
        </div>
      </div>
    </div>
  )
}

function AssistantMessage({
  message,
  researchMode,
}: {
  message: ConversationMessage
  researchMode: boolean
}) {
  const answer = message.answer
  const sql = message.sql || message.result?.final_sql || message.result?.generation?.generated_sql || ''
  const [showSql, setShowSql] = useState(false)
  const [showResearch, setShowResearch] = useState(false)
  const speech = useSpeech()

  if (!answer) return null

  return (
    <div className="message assistant-message">
      <div className="message-avatar assistant">
        <Sparkles size={16} strokeWidth={1.75} />
      </div>
      <div className="message-content">
        <div className="message-role-label">
          <span className="assistant-brand">✦ Voice-LitE-SQL</span>
        </div>
        <div className="assistant-body">
          <AnswerRenderer answer={answer} />

          <div className="message-actions">
            {answer.type !== 'error' && answer.speechText && (
              <button
                className={`action-chip ${speech.speaking ? 'speaking' : ''}`}
                onClick={() => (speech.speaking ? speech.stop() : speech.speak(answer.speechText))}
              >
                {speech.speaking ? (
                  <>
                    <Square size={14} strokeWidth={1.75} />
                    Speaking… Stop
                  </>
                ) : (
                  <>
                    <Volume2 size={14} strokeWidth={1.75} />
                    Listen
                  </>
                )}
              </button>
            )}
            {sql && (
              <button className="action-chip" onClick={() => setShowSql(v => !v)}>
                <Braces size={14} strokeWidth={1.75} />
                View SQL
              </button>
            )}
            {researchMode && (
              <button
                className="action-chip"
                onClick={() => setShowResearch(v => !v)}
              >
                <FlaskConical size={14} strokeWidth={1.75} />
                Research trace
              </button>
            )}
          </div>

          {speech.unavailable && (
            <div className="speech-unavailable">{speech.unavailable}</div>
          )}

          {showSql && sql && <SQLDisclosure sql={sql} />}
          {showResearch && researchMode && message.result && (
            <ResearchTrace
              result={message.result}
              open={showResearch}
              onToggle={() => setShowResearch(v => !v)}
            />
          )}
        </div>
      </div>
    </div>
  )
}
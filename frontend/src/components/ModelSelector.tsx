import { useEffect, useRef } from 'react'
import type { OllamaModel } from '../types'

interface ModelSelectorProps {
  models: OllamaModel[]
  activeModel: string
  onSelect: (modelName: string) => void
  onClose: () => void
}

const BASELINE_MODEL = 'qwen2.5-coder:1.5b'

export function ModelSelector({
  models,
  activeModel,
  onSelect,
  onClose,
}: ModelSelectorProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onClose])

  const isBaseline = (name: string) => name === BASELINE_MODEL

  return (
    <div className="model-selector-modal" role="dialog" aria-modal="true" aria-label="Select Model" ref={containerRef}>
      <div className="modal-backdrop" onClick={onClose} />
      <div className="modal-content selector-modal">
        <div className="modal-header">
          <h2>Model</h2>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="selector-body">
          <ul className="model-options">
            {models.map((model) => {
              const baseline = isBaseline(model.name)
              const sizeGB = (model.size / 1e9).toFixed(1)
              return (
                <li key={model.name}>
                  <button
                    type="button"
                    className={`model-option ${activeModel === model.name ? 'active' : ''} ${baseline ? 'baseline' : 'enhanced'}`}
                    onClick={() => onSelect(model.name)}
                  >
                    <div className="model-indicator">
                      {activeModel === model.name ? (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <span className="radio" />
                      )}
                    </div>
                    <div className="model-info">
                      <div className="model-header">
                        <span className="model-name">{model.name}</span>
                        {baseline && <span className="model-badge baseline">Research baseline</span>}
                        {!baseline && <span className="model-badge enhanced">Enhanced</span>}
                      </div>
                      <div className="model-meta">
                        <span>{sizeGB} GB</span>
                        <span>•</span>
                        <span>Local (Ollama)</span>
                        <span>•</span>
                        <span>{baseline ? '1.5B params' : '9B params'}</span>
                      </div>
                    </div>
                  </button>
                </li>
              )
            })}
            {models.length === 0 && (
              <li className="no-models">
                <p>No models found</p>
                <p className="hint">Run <code>ollama pull qwen2.5-coder:1.5b</code> or <code>ollama pull qwen3.5:9b</code></p>
              </li>
            )}
          </ul>
        </div>
      </div>
    </div>
  )
}
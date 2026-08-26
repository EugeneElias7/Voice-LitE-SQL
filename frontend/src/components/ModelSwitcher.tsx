import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Loader2, X } from 'lucide-react'
import type { OllamaModel } from '../types'

interface ModelSwitcherProps {
  currentModel: string
  models: OllamaModel[]
  onSelectModel: (model: string) => void
}

export function ModelSwitcher({
  currentModel,
  models,
  onSelectModel,
}: ModelSwitcherProps) {
  const [open, setOpen] = useState(false)
  const [optimisticModel, setOptimisticModel] = useState(currentModel)
  const [validating] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // biome-ignore lint/correctness/useState: validating state reserved for future async validation
  // biome-ignore lint/correctness/useState: setter reserved for future async validation
  const [, _unused] = useState(false)

  useEffect(() => {
    setOptimisticModel(currentModel)
  }, [currentModel])

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleSelect = useCallback(
    (model: string) => {
      setOptimisticModel(model)
      setOpen(false)
      onSelectModel(model)
    },
    [onSelectModel]
  )

  return (
    <div className="popover-wrap" ref={ref}>
      <button
        className={`pill ${validating ? 'validating' : ''}`}
        onClick={() => setOpen(v => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        disabled={validating}
        title={validating ? 'Checking model…' : optimisticModel}
      >
        <span className="model-name">{optimisticModel}</span>
        <ChevronDown className="pill-chevron" size={13} strokeWidth={1.75} />
        {validating && <Loader2 size={14} className="spinner" strokeWidth={1.75} />}
      </button>

      {open && (
        <div className="popover">
          <div className="popover-head">
            <span className="popover-head-label">Model</span>
            <button
              className="popover-close"
              onClick={() => setOpen(false)}
              aria-label="Close"
              disabled={validating}
            >
              <X size={14} strokeWidth={1.75} />
            </button>
          </div>
          <div className="popover-body">
            {models.map(model => (
              <button
                key={model.name}
                className={`popover-item ${optimisticModel === model.name ? 'active' : ''}`}
                onClick={() => handleSelect(model.name)}
                disabled={validating}
              >
                <span className="popover-item-main">
                  <span className="popover-item-name mono" style={{ fontFamily: 'var(--mono)' }}>
                    {model.name}
                  </span>
                  <span className="popover-item-sub">
                    {(model.size / 1e9).toFixed(1)}B params
                  </span>
                </span>
                {optimisticModel === model.name && (
                  <Check className="popover-item-check" size={16} strokeWidth={1.75} />
                )}
              </button>
            ))}
            {models.length === 0 && (
              <div className="popover-empty">No models available</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
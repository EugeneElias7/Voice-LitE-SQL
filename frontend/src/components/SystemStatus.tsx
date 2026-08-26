import type { SystemStatus } from '../types'

interface StatusRowProps {
  label: string
  value: string
  ok: boolean
}

function StatusRow({ label, value, ok }: StatusRowProps) {
  return (
    <div className="status-row">
      <span className={`status-dot ${ok ? 'ok' : 'down'}`} aria-hidden="true" />
      <span className="status-row-label">{label}</span>
      <span className="status-row-value">{value}</span>
    </div>
  )
}

// Compact component used inside the header status tray. Shows a quiet,
// per-component health snapshot pulled from the real /api/status payload.
export function SystemStatusPanel({ status }: { status: SystemStatus | null }) {
  if (!status) {
    return (
      <div className="status-panel" aria-label="System status">
        <p className="muted">Checking components…</p>
      </div>
    )
  }

  const backend = status.backend.state === 'ready'
  const database = status.database.state === 'ready'
  const ollama = status.ollama.state === 'ready'
  const whisper = status.whisper.state === 'ready'
  const chroma = status.chroma.state === 'ready'

  return (
    <div className="status-panel" aria-label="System status">
      <StatusRow label="Backend" value={backend ? 'Connected' : 'Offline'} ok={backend} />
      <StatusRow
        label="Database"
        value={`${status.database.tables ?? '?'} tables`}
        ok={database}
      />
      <StatusRow label="Ollama" value={ollama ? 'Connected' : 'Offline'} ok={ollama} />
      <StatusRow label="Qwen 1.5B" value={status.model?.name ?? '—'} ok={Boolean(status.model?.loaded)} />
      <StatusRow label="Whisper" value={whisper ? 'Ready' : 'Not found'} ok={whisper} />
      <StatusRow label="ChromaDB" value={chroma ? 'Ready' : 'Not built'} ok={chroma} />
    </div>
  )
}
import { useRef, useState, useCallback, useEffect } from 'react'
import { useRecorder } from '../useRecorder'

interface VoiceButtonProps {
  onVoiceFile: (file: File) => void
  disabled: boolean
  processing: boolean
  onPermissionDenied: (message: string) => void
}

export function VoiceButton({
  onVoiceFile,
  disabled,
  processing,
  onPermissionDenied,
}: VoiceButtonProps) {
  const recorder = useRecorder(onPermissionDenied)
  const guardRef = useRef(false)
  const [micDevices, setMicDevices] = useState<MediaDeviceInfo[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('')
  const [showDeviceMenu, setShowDeviceMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const loadDevices = async () => {
      if (!navigator.mediaDevices?.enumerateDevices) return
      try {
        const devices = await navigator.mediaDevices.enumerateDevices()
        const inputs = devices.filter((d) => d.kind === 'audioinput')
        setMicDevices(inputs)
        const saved = localStorage.getItem('l11-input-device')
        if (saved && inputs.some((d) => d.deviceId === saved)) {
          setSelectedDeviceId(saved)
        }
      } catch {
        /* ignore */
      }
    }
    loadDevices()
  }, [])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowDeviceMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const onPointerDown = useCallback(() => {
    if (disabled || processing) return
    guardRef.current = false
    recorder.start(selectedDeviceId || undefined)
  }, [disabled, processing, recorder, selectedDeviceId])

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

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div className="voice-button-group" ref={menuRef}>
      <button
        type="button"
        className={`mic-button ${recorder.recording ? 'recording' : ''} ${disabled ? 'disabled' : ''}`}
        onPointerDown={recorder.recording ? undefined : onPointerDown}
        onPointerUp={recorder.recording ? onPointerUp : undefined}
        onPointerLeave={recorder.recording ? onPointerLeave : undefined}
        disabled={disabled || processing}
        aria-label={recorder.recording ? 'Release to stop recording' : 'Hold to speak'}
        title={recorder.recording ? 'Release to stop' : 'Hold to speak'}
      >
        <span className="mic-dot" aria-hidden="true" />
        {recorder.recording ? (
          <span className="mic-count">Listening… ● {formatTime(recorder.elapsed)}</span>
        ) : (
          <>
            <span className="mic-icon" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="22" />
                <line x1="8" y1="22" x2="16" y2="22" />
              </svg>
            </span>
            <span className="mic-label">Ask with your voice</span>
          </>
        )}
      </button>

      {micDevices.length > 0 && (
        <>
          <button
            type="button"
            className={`mic-device-trigger ${showDeviceMenu ? 'open' : ''}`}
            onClick={() => setShowDeviceMenu(!showDeviceMenu)}
            aria-label="Select microphone"
            aria-expanded={showDeviceMenu}
            aria-haspopup="listbox"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            </svg>
            <span className="device-indicator" aria-hidden="true" />
          </button>

          {showDeviceMenu && (
            <ul className="device-menu" role="listbox" aria-label="Microphone selection">
              <li role="option" aria-selected={!selectedDeviceId} onClick={() => { setSelectedDeviceId(''); localStorage.setItem('l11-input-device', ''); setShowDeviceMenu(false); }}>
                <span className="device-name">Default microphone</span>
              </li>
              {micDevices.map((d, i) => (
                <li
                  key={d.deviceId}
                  role="option"
                  aria-selected={selectedDeviceId === d.deviceId}
                  onClick={() => { setSelectedDeviceId(d.deviceId); localStorage.setItem('l11-input-device', d.deviceId); setShowDeviceMenu(false); }}
                >
                  <span className="device-name">{d.label || `Microphone ${i + 1}`}</span>
                  {selectedDeviceId === d.deviceId && <span className="device-check" aria-hidden="true">✓</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
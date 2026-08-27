import { useCallback, useEffect, useRef, useState } from 'react'

export type VoiceState = 
  | 'idle'
  | 'requesting_permission'
  | 'recording'
  | 'stopping'
  | 'transcribing'
  | 'ready'
  | 'error'

export interface RecorderState {
  recording: boolean
  elapsed: number
  error: string | null
  devices: MediaDeviceInfo[]
  deviceId: string
  setDeviceId: (id: string) => void
  refreshDevices: () => Promise<void>
  start: (deviceId?: string) => Promise<void>
  stop: () => Promise<File | null>
  cancel: () => void
  stream: MediaStream | null
  transcript: string
  interimTranscript: string
  recognitionActive: boolean
  snapshotTranscript: () => string
  voiceState: VoiceState
  setVoiceState: (state: VoiceState) => void
}

interface SpeechRecognitionConstructor {
  new (): SpeechRecognition
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  start: () => void
  stop: () => void
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
  onstart: (() => void) | null
  onend: (() => void) | null
}

interface SpeechRecognitionEvent extends Event {
  resultIndex: number
  results: SpeechRecognitionResultList
}

interface SpeechRecognitionResultList {
  length: number
  item(index: number): SpeechRecognitionResult
  [index: number]: SpeechRecognitionResult
}

interface SpeechRecognitionResult {
  isFinal: boolean
  length: number
  item(index: number): SpeechRecognitionAlternative
  [index: number]: SpeechRecognitionAlternative
}

interface SpeechRecognitionAlternative {
  transcript: string
  confidence: number
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string
  message: string
}

const DEVICE_KEY = 'l11-input-device'

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

function pickMimeType(): string {
  if (typeof window === 'undefined' || !window.MediaRecorder) return ''
  const found = MIME_CANDIDATES.find((mime) => MediaRecorder.isTypeSupported(mime))
  return found || ''
}

function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  return (
    (window as unknown as { SpeechRecognition?: SpeechRecognitionConstructor }).SpeechRecognition ||
    (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition ||
    null
  )
}

export function useRecorder(onPermissionDenied?: (message: string) => void): RecorderState {
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceIdState] = useState<string>('')
  const [transcript, setTranscript] = useState('')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [recognitionActive, setRecognitionActive] = useState(false)
  const [voiceState, setVoiceState] = useState<VoiceState>('idle')

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const startTimeRef = useRef(0)
  const askedRef = useRef(false)
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  useEffect(() => {
    try {
      setDeviceIdState(window.localStorage.getItem(DEVICE_KEY) || '')
    } catch {
      /* storage unavailable */
    }
  }, [])

  const setDeviceId = useCallback((id: string) => {
    setDeviceIdState(id)
    try {
      window.localStorage.setItem(DEVICE_KEY, id)
    } catch {
      /* storage unavailable */
    }
  }, [])

  const refreshDevices = useCallback(async () => {
    if (!window.navigator?.mediaDevices?.enumerateDevices) return
    try {
      const list = async () => {
        const all = await window.navigator.mediaDevices.enumerateDevices()
        return all.filter((d) => d.kind === 'audioinput')
      }
      let inputs = await list()
      if (inputs.some((d) => d.label === '') && !askedRef.current) {
        askedRef.current = true
        try {
          const temp = await window.navigator.mediaDevices.getUserMedia({ audio: true })
          temp.getTracks().forEach((t) => t.stop())
        } catch {
          /* permission denied or unavailable; labels stay empty */
        }
        inputs = await list()
      }
      setDevices(inputs)
    } catch {
      /* enumeration unavailable */
    }
  }, [])

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  const stopRecognition = useCallback(() => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {
        /* already stopped */
      }
      recognitionRef.current = null
      setRecognitionActive(false)
    }
  }, [])

  const startRecognition = useCallback(() => {
    const SpeechRecognition = getSpeechRecognition()
    if (!SpeechRecognition) return

    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      setRecognitionActive(true)
    }

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = ''
      let final = ''

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]
        if (result.isFinal) {
          final += result[0].transcript
        } else {
          interim += result[0].transcript
        }
      }

      if (final) {
        setTranscript(prev => prev + (prev ? ' ' : '') + final)
      }
      setInterimTranscript(interim)
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        console.warn('Speech recognition error:', event.error)
      }
    }

    recognition.onend = () => {
      setRecognitionActive(false)
    }

    recognitionRef.current = recognition
    recognition.start()
  }, [])

  const start = useCallback(async (overrideDeviceId?: string) => {
    const effectiveDeviceId = overrideDeviceId ?? deviceId
    setError(null)
    setTranscript('')
    setInterimTranscript('')
    setVoiceState('requesting_permission')
    if (!window.navigator?.mediaDevices?.getUserMedia) {
      const message = 'Microphone API is not available in this browser'
      setError(message)
      setVoiceState('error')
      onPermissionDenied?.(message)
      return
    }
    let stream: MediaStream
    try {
      stream = effectiveDeviceId
        ? await window.navigator.mediaDevices.getUserMedia({ audio: { deviceId: { exact: effectiveDeviceId } } })
        : await window.navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err) {
      const name = err instanceof DOMException ? err.name : ''
      const isPermission = name === 'NotAllowedError' || name === 'SecurityError'
      const isDeviceGone = deviceId && (name === 'OverconstrainedError' || name === 'NotFoundError')
      if (isDeviceGone) {
        try {
          stream = await window.navigator.mediaDevices.getUserMedia({ audio: true })
        } catch (err2) {
          const message =
            err2 instanceof DOMException && err2.name === 'NotAllowedError'
              ? 'Microphone permission denied. Check the site settings or use text input.'
              : 'Could not access the microphone.'
          setError(message)
          onPermissionDenied?.(message)
          return
        }
      } else {
        const message = isPermission
          ? 'Microphone permission denied. Check the site settings or use text input.'
          : 'Could not access the microphone.'
        setError(message)
        onPermissionDenied?.(message)
        return
      }
    }
    setVoiceState('recording')
    const mimeType = pickMimeType()
    let recorder: MediaRecorder
    try {
      recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream)
    } catch {
      recorder = new MediaRecorder(stream)
    }
    chunksRef.current = []
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunksRef.current.push(event.data)
    }
    mediaRecorderRef.current = recorder
    streamRef.current = stream
    recorder.start()
    setRecording(true)
    startTimeRef.current = Date.now()
    setElapsed(0)
    timerRef.current = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000))
    }, 250)

    startRecognition()
  }, [deviceId, onPermissionDenied])

  const stop = useCallback(async (): Promise<File | null> => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === 'inactive') return null
    const mime = recorder.mimeType || pickMimeType() || 'audio/webm'
    const extension = mime.includes('mp4') ? 'mp4' : mime.includes('ogg') ? 'ogg' : 'webm'
    setVoiceState('stopping')
    const file = await new Promise<File | null>((resolve) => {
      recorder.onstop = () => {
        const type = recorder.mimeType || mime
        const blob = new Blob(chunksRef.current, { type })
        const name = `recording-${Date.now()}.${extension}`
        resolve(blob.size > 0 ? new File([blob], name, { type }) : null)
      }
      recorder.stop()
    })
    clearTimer()
    stopStream()
    stopRecognition()
    setRecording(false)
    setVoiceState('transcribing')
    mediaRecorderRef.current = null
    return file
  }, [clearTimer, stopStream])

  const cancel = useCallback(() => {
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.onstop = null
        recorder.stop()
      } catch {
        /* already stopped */
      }
    }
    clearTimer()
    stopStream()
    stopRecognition()
    setRecording(false)
    setTranscript('')
    setInterimTranscript('')
    mediaRecorderRef.current = null
  }, [clearTimer, stopStream])

  const snapshotTranscript = useCallback((): string => {
    const finalText = transcript.trim()
    const interimText = interimTranscript.trim()
    if (finalText && interimText) return `${finalText} ${interimText}`
    return finalText || interimText
  }, [transcript, interimTranscript])

  return {
    recording,
    elapsed,
    error,
    devices,
    deviceId,
    setDeviceId,
    refreshDevices,
    start,
    stop,
    cancel,
    stream: streamRef.current,
    transcript,
    interimTranscript,
    recognitionActive,
    snapshotTranscript,
    voiceState,
    setVoiceState,
  }
}
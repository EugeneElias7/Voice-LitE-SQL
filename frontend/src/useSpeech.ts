import { useCallback, useEffect, useRef, useState } from 'react'
import { textToSpeech } from './api'

export interface SpeechController {
  speaking: boolean
  paused: boolean
  loading: boolean
  unavailable: string | null
  speak: (text: string) => void
  stop: () => void
  pause: () => void
  resume: () => void
}

export function useSpeech(): SpeechController {
  const [speaking, setSpeaking] = useState(false)
  const [paused, setPaused] = useState(false)
  const [loading, setLoading] = useState(false)
  const [unavailable, setUnavailable] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const speak = useCallback(
    async (text: string) => {
      const clean = String(text || '').trim()
      if (!clean) return
      if (typeof window === 'undefined') {
        setUnavailable('Speech is not available in this environment.')
        return
      }
      if (speaking) return
      setSpeaking(true)
      setPaused(false)
      setLoading(true)
      setUnavailable(null)

      abortRef.current = new AbortController()
      try {
        // Use a female voice if supported by backend (e.g., "af_heart", "af_bella", "af_nicole", etc.)
        const blob = await textToSpeech(clean, 'af_heart')
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audioRef.current = audio
        audio.onended = () => {
          setSpeaking(false)
          setPaused(false)
          URL.revokeObjectURL(url)
        }
        audio.onerror = () => {
          setSpeaking(false)
          setPaused(false)
          setUnavailable('Failed to play audio.')
          URL.revokeObjectURL(url)
        }
        setLoading(false)
        await audio.play()
      } catch (e) {
        setSpeaking(false)
        setPaused(false)
        setLoading(false)
        setUnavailable(e instanceof Error ? e.message : 'TTS request failed.')
      }
    },
    [],
  )

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setSpeaking(false)
    setPaused(false)
  }, [])

  const pause = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      setPaused(true)
    }
  }, [])

  const resume = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.play().catch(() => {})
      setPaused(false)
    }
  }, [])

  useEffect(() => () => stop(), [stop])

  return { speaking, paused, loading, unavailable, speak, stop, pause, resume }
}
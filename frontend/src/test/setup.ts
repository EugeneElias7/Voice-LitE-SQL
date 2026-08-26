import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// ResizeObserver polyfill for jsdom
if (typeof window !== 'undefined' && !window.ResizeObserver) {
  window.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// jsdom lacks matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// jsdom lacks canvas 2d - provide a no-op for recharts/measurement
const originalGetContext = HTMLCanvasElement.prototype.getContext
Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
  writable: true,
  value: function (contextId: string) {
    if (contextId === '2d') {
      return null
    }
    return originalGetContext ? originalGetContext.call(this, contextId) : null
  },
})

class LocalStorageMock {
  private store = new Map<string, string>()
  get length() {
    return this.store.size
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }
  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value)
  }
  removeItem(key: string): void {
    this.store.delete(key)
  }
  clear(): void {
    this.store.clear()
  }
}

vi.stubGlobal('localStorage', new LocalStorageMock())
vi.stubGlobal('MediaRecorder', undefined)

// jsdom only fires requestAnimationFrame once; make it advance time so
// count-up animations reach their final value within a couple of frames.
let rafHandle = 0
Object.defineProperty(window, 'requestAnimationFrame', {
  writable: true,
  configurable: true,
  value: (cb: FrameRequestCallback) => {
    rafHandle++
    setTimeout(() => cb(performance.now() + 1000), 0)
    return rafHandle
  },
})

// SpeechSynthesis mock (defined on window directly so afterEach unstubs don't clear it)
class FakeSpeechSynthesis {
  speaking = false
  paused = false
  voices: SpeechSynthesisVoice[] = [
    { lang: 'en-US', name: 'Google US English', default: true, localService: false, voiceURI: 'google' } as SpeechSynthesisVoice,
  ]
  speak = vi.fn(() => {
    this.speaking = true
  })
  cancel = vi.fn(() => {
    this.speaking = false
    this.paused = false
  })
  pause = vi.fn(() => {
    this.paused = true
  })
  resume = vi.fn(() => {
    this.paused = false
  })
  getVoices = vi.fn(() => this.voices)
  addEventListener = vi.fn()
  removeEventListener = vi.fn()
}

Object.defineProperty(window, 'speechSynthesis', {
  writable: true,
  configurable: true,
  value: new FakeSpeechSynthesis(),
})
Object.defineProperty(window, 'SpeechSynthesisUtterance', {
  writable: true,
  configurable: true,
  value: class FakeSpeechSynthesisUtterance {
    text = ''
    lang = ''
    rate = 1
    pitch = 1
    voice: SpeechSynthesisVoice | null = null
    onstart: (() => void) | null = null
    onend: (() => void) | null = null
    onerror: (() => void) | null = null
    constructor(text?: string) {
      this.text = text ?? ''
    }
  },
})
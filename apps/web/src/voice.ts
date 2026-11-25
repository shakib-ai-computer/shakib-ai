import { useCallback, useEffect, useRef, useState } from 'react'
import { markdownToPlainText } from './markdown'

// Browser Web Speech API helpers (the "voice" skill is client_side by
// design — no server component). Types are declared locally because the
// standard TS DOM lib does not ship SpeechRecognition types.

interface SpeechRecognitionAlternativeLike {
  transcript: string
}

interface SpeechRecognitionResultLike {
  isFinal: boolean
  0: SpeechRecognitionAlternativeLike
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<SpeechRecognitionResultLike>
}

interface SpeechRecognitionErrorEventLike {
  error: string
}

interface SpeechRecognitionLike {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
}

export type SpeechLang = 'en-US' | 'bn-BD'

export function recognitionSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    (window.SpeechRecognition !== undefined || window.webkitSpeechRecognition !== undefined)
  )
}

export function synthesisSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

interface Dictation {
  supported: boolean
  listening: boolean
  error: string | null
  start: (lang: SpeechLang) => void
  stop: () => void
}

/** Microphone dictation: final transcripts are appended via onTranscript. */
export function useDictation(onTranscript: (text: string) => void): Dictation {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const callbackRef = useRef(onTranscript)
  callbackRef.current = onTranscript
  const supported = recognitionSupported()

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const start = useCallback(
    (lang: SpeechLang) => {
      const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition
      if (!Ctor) return
      setError(null)
      const rec = new Ctor()
      rec.lang = lang
      rec.interimResults = false
      rec.continuous = true
      rec.onresult = (event) => {
        let text = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i]
          if (result.isFinal) text += result[0].transcript
        }
        if (text.trim()) callbackRef.current(text.trim())
      }
      rec.onerror = (event) => {
        setError(`speech recognition error: ${event.error}`)
        setListening(false)
      }
      rec.onend = () => setListening(false)
      recognitionRef.current = rec
      try {
        rec.start()
        setListening(true)
      } catch {
        setError('could not start speech recognition')
      }
    },
    [],
  )

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop()
    }
  }, [])

  return { supported, listening, error, start, stop }
}

/** Read text (Markdown is flattened first) aloud in the chosen language. */
export function speakMarkdown(markdown: string, lang: SpeechLang): void {
  if (!synthesisSupported()) return
  const text = markdownToPlainText(markdown)
  if (!text) return
  window.speechSynthesis.cancel()
  // SpeechSynthesisUtterance has a practical per-utterance length limit in
  // some browsers; chunk on sentence boundaries to be safe.
  const chunks = text.match(/[^.!?।\n]{1,300}[.!?।]?/g) ?? [text]
  for (const chunk of chunks) {
    const utterance = new SpeechSynthesisUtterance(chunk.trim())
    utterance.lang = lang
    window.speechSynthesis.speak(utterance)
  }
}

export function stopSpeaking(): void {
  if (synthesisSupported()) window.speechSynthesis.cancel()
}

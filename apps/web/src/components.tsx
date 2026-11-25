import { useState } from 'react'
import { ApiError } from './api'
import { speakMarkdown, stopSpeaking, synthesisSupported, type SpeechLang } from './voice'

/** The backend's own error text, shown verbatim — never replaced by fakes. */
export function ErrorNotice({ error, label }: { error: unknown; label?: string }) {
  if (!error) return null
  const message =
    error instanceof ApiError
      ? error.status === 503
        ? error.message
        : `${error.message} (HTTP ${error.status || 'network'})`
      : error instanceof Error
        ? error.message
        : String(error)
  const isConfig = error instanceof ApiError && error.status === 503
  return (
    <div className={isConfig ? 'notice notice-config' : 'notice notice-error'} role="alert">
      {label && <strong>{label}: </strong>}
      {isConfig && <strong>Not configured on the server — </strong>}
      <span>{message}</span>
    </div>
  )
}

export function SignInPrompt({ feature }: { feature: string }) {
  return (
    <div className="notice notice-info">
      <strong>Sign-in required.</strong> {feature} is stored per user on the server, so it
      needs an account. Use <em>Sign in / Register</em> in the sidebar — chat, research and
      the other tools still work in guest mode when the server allows it.
    </div>
  )
}

/** Read-aloud button (browser speech synthesis) for a block of Markdown. */
export function ReadAloudButton({ text, lang }: { text: string; lang: SpeechLang }) {
  const [speaking, setSpeaking] = useState(false)
  if (!synthesisSupported()) return null
  return (
    <button
      type="button"
      className="btn btn-small"
      onClick={() => {
        if (speaking) {
          stopSpeaking()
          setSpeaking(false)
        } else {
          speakMarkdown(text, lang)
          setSpeaking(true)
          window.setTimeout(() => setSpeaking(false), 4000)
        }
      }}
    >
      {speaking ? '⏹ Stop reading' : '🔊 Read aloud'}
    </button>
  )
}

/** Microphone dictation toggle + optional "not supported" note. */
export function MicButton({
  supported,
  listening,
  onToggle,
}: {
  supported: boolean
  listening: boolean
  onToggle: () => void
}) {
  if (!supported) {
    return (
      <span className="voice-unsupported" title="Speech recognition is not available in this browser">
        🎙 not supported in this browser
      </span>
    )
  }
  return (
    <button
      type="button"
      className={listening ? 'btn btn-small btn-recording' : 'btn btn-small'}
      onClick={onToggle}
      title={listening ? 'Stop dictation' : 'Start voice dictation'}
    >
      {listening ? '⏹ Listening…' : '🎙 Dictate'}
    </button>
  )
}

export function formatDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

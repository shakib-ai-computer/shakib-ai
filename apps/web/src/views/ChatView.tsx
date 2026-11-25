import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addConversationMessage,
  createConversation,
  getConversation,
  listConversations,
  sendChat,
  type ChatMessage,
  type Conversation,
  type ModelRole,
} from '../api'
import { useAuth } from '../auth'
import { ErrorNotice, MicButton, ReadAloudButton, formatDate } from '../components'
import { Markdown } from '../markdown'
import { useDictation, type SpeechLang } from '../voice'

const ROLES: { id: ModelRole; label: string }[] = [
  { id: 'fast', label: 'Fast' },
  { id: 'smart', label: 'Smart' },
  { id: 'strategic', label: 'Strategic' },
]

export default function ChatView() {
  const { user } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [role, setRole] = useState<ModelRole>('smart')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [persistWarning, setPersistWarning] = useState<string | null>(null)
  const [speechLang, setSpeechLang] = useState<SpeechLang>('en-US')
  const threadRef = useRef<HTMLDivElement>(null)

  const dictation = useDictation((text) =>
    setInput((prev) => (prev ? `${prev} ${text}` : text)),
  )

  const loadConversations = useCallback(async () => {
    if (!user) {
      setConversations([])
      return
    }
    try {
      const res = await listConversations()
      setConversations(res.conversations)
    } catch (err) {
      setError(err)
    }
  }, [user])

  useEffect(() => {
    void loadConversations()
  }, [loadConversations])

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight })
  }, [messages, sending])

  const openConversation = async (id: number) => {
    setError(null)
    try {
      const detail = await getConversation(id)
      setActiveId(id)
      setMessages(detail.messages.map((m) => ({ role: m.role, content: m.content })))
    } catch (err) {
      setError(err)
    }
  }

  const newChat = () => {
    setActiveId(null)
    setMessages([])
    setError(null)
    setPersistWarning(null)
  }

  /** Persist a message to the active conversation; returns its id. */
  const persist = async (convId: number, msg: ChatMessage) => {
    await addConversationMessage(convId, msg.role, msg.content)
  }

  const send = async () => {
    const text = input.trim()
    if (!text || sending) return
    setError(null)
    setPersistWarning(null)
    const userMsg: ChatMessage = { role: 'user', content: text }
    const history = [...messages, userMsg]
    setMessages(history)
    setInput('')
    setSending(true)
    try {
      const res = await sendChat(history, role)
      const reply = res.choices?.[0]?.message?.content ?? ''
      const assistantMsg: ChatMessage = { role: 'assistant', content: reply }
      setMessages([...history, assistantMsg])

      // Save the exchange to the signed-in user's history (best effort —
      // a storage failure is reported, never hidden, but does not erase
      // the reply the user already received).
      if (user) {
        try {
          let convId = activeId
          if (convId === null) {
            const conv = await createConversation(text.slice(0, 80))
            convId = conv.id
            setActiveId(convId)
          }
          await persist(convId, userMsg)
          await persist(convId, assistantMsg)
          void loadConversations()
        } catch {
          setPersistWarning('The reply was received but could not be saved to your history.')
        }
      }
    } catch (err) {
      setError(err)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="chat-layout">
      <div className="chat-side">
        <button type="button" className="btn btn-primary btn-block" onClick={newChat}>
          + New chat
        </button>
        {user ? (
          conversations.length === 0 ? (
            <p className="muted small">No saved conversations yet.</p>
          ) : (
            <ul className="conv-list">
              {conversations.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    className={c.id === activeId ? 'conv-item active' : 'conv-item'}
                    onClick={() => void openConversation(c.id)}
                  >
                    <span className="conv-title">{c.title || '(untitled)'}</span>
                    <span className="conv-date">{formatDate(c.updated_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : (
          <p className="muted small">
            Guest mode — sign in to save and revisit conversations.
          </p>
        )}
      </div>

      <div className="chat-main">
        <ErrorNotice error={error} />
        {persistWarning && <div className="notice notice-info">{persistWarning}</div>}
        <div className="chat-thread" ref={threadRef}>
          {messages.length === 0 && (
            <p className="muted">
              Ask anything. Replies come from the model gateway via SHAKIB AI Core — if the
              gateway is not configured on the server you will see its exact 503 message
              here instead of a made-up answer.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={m.role === 'user' ? 'msg msg-user' : 'msg msg-assistant'}>
              <div className="msg-role">{m.role === 'user' ? 'You' : 'SHAKIB AI'}</div>
              {m.role === 'assistant' ? (
                <>
                  <Markdown text={m.content} />
                  <ReadAloudButton text={m.content} lang={speechLang} />
                </>
              ) : (
                <p className="msg-plain">{m.content}</p>
              )}
            </div>
          ))}
          {sending && <p className="muted">Thinking…</p>}
        </div>

        <div className="chat-controls">
          <label className="field-inline">
            Model role
            <select value={role} onChange={(e) => setRole(e.target.value as ModelRole)}>
              {ROLES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field-inline">
            Voice
            <select
              value={speechLang}
              onChange={(e) => setSpeechLang(e.target.value as SpeechLang)}
            >
              <option value="en-US">English (US)</option>
              <option value="bn-BD">বাংলা (BD)</option>
            </select>
          </label>
          <MicButton
            supported={dictation.supported}
            listening={dictation.listening}
            onToggle={() =>
              dictation.listening ? dictation.stop() : dictation.start(speechLang)
            }
          />
        </div>
        {dictation.error && <div className="notice notice-error">{dictation.error}</div>}
        <div className="chat-input-row">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
            rows={3}
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void send()}
            disabled={sending || !input.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}

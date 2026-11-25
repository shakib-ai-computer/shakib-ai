import { useCallback, useEffect, useState } from 'react'
import {
  deleteConversation,
  getConversation,
  listConversations,
  type Conversation,
  type ConversationDetail,
} from '../api'
import { useAuth } from '../auth'
import { ErrorNotice, SignInPrompt, formatDate } from '../components'
import { Markdown } from '../markdown'

export default function HistoryView() {
  const { user } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [counts, setCounts] = useState<Record<number, number>>({})
  const [open, setOpen] = useState<ConversationDetail | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    if (!user) return
    try {
      const res = await listConversations()
      setConversations(res.conversations)
      // Message counts need each conversation's detail; fetch them so the
      // list shows real numbers rather than guesses.
      const entries = await Promise.all(
        res.conversations.map(async (c) => {
          try {
            const detail = await getConversation(c.id)
            return [c.id, detail.messages.length] as const
          } catch {
            return [c.id, -1] as const
          }
        }),
      )
      setCounts(Object.fromEntries(entries))
    } catch (err) {
      setError(err)
    }
  }, [user])

  useEffect(() => {
    void load()
  }, [load])

  if (!user) {
    return (
      <div className="view">
        <SignInPrompt feature="Conversation history" />
      </div>
    )
  }

  const toggle = async (id: number) => {
    if (open?.id === id) {
      setOpen(null)
      return
    }
    setError(null)
    try {
      setOpen(await getConversation(id))
    } catch (err) {
      setError(err)
    }
  }

  const remove = async (id: number) => {
    setError(null)
    try {
      await deleteConversation(id)
      if (open?.id === id) setOpen(null)
      await load()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="view">
      <ErrorNotice error={error} />
      {conversations.length === 0 ? (
        <p className="muted">No conversations yet — chats you have while signed in appear here.</p>
      ) : (
        <ul className="history-list">
          {conversations.map((c) => (
            <li key={c.id} className="card history-item">
              <div className="history-head">
                <button type="button" className="history-open" onClick={() => void toggle(c.id)}>
                  <span className="history-title">{c.title || '(untitled)'}</span>
                  <span className="muted small">
                    {counts[c.id] === undefined
                      ? '…'
                      : counts[c.id] < 0
                        ? 'message count unavailable'
                        : `${counts[c.id]} messages`}
                    {' · created '}
                    {formatDate(c.created_at)}
                    {' · updated '}
                    {formatDate(c.updated_at)}
                  </span>
                </button>
                <button
                  type="button"
                  className="btn btn-small btn-danger"
                  onClick={() => void remove(c.id)}
                >
                  Delete
                </button>
              </div>
              {open?.id === c.id && (
                <div className="history-messages">
                  {open.messages.length === 0 && <p className="muted">No messages stored.</p>}
                  {open.messages.map((m) => (
                    <div key={m.id} className={m.role === 'user' ? 'msg msg-user' : 'msg msg-assistant'}>
                      <div className="msg-role">
                        {m.role === 'user' ? 'You' : 'SHAKIB AI'} · {formatDate(m.created_at)}
                      </div>
                      {m.role === 'assistant' ? (
                        <Markdown text={m.content} />
                      ) : (
                        <p className="msg-plain">{m.content}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

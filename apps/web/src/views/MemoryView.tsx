import { useCallback, useEffect, useState } from 'react'
import { addMemory, deleteMemory, listMemory, type MemoryItem } from '../api'
import { useAuth } from '../auth'
import { ErrorNotice, SignInPrompt, formatDate } from '../components'

export default function MemoryView() {
  const { user } = useAuth()
  const [items, setItems] = useState<MemoryItem[]>([])
  const [kind, setKind] = useState('note')
  const [content, setContent] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!user) return
    try {
      const res = await listMemory()
      setItems(res.items)
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
        <SignInPrompt feature="Long-term memory" />
      </div>
    )
  }

  const add = async () => {
    if (!content.trim() || busy) return
    setError(null)
    setBusy(true)
    try {
      await addMemory(kind.trim() || 'note', content.trim())
      setContent('')
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number) => {
    setError(null)
    try {
      await deleteMemory(id)
      await load()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="view">
      <ErrorNotice error={error} />
      <form
        className="card form-card"
        onSubmit={(e) => {
          e.preventDefault()
          void add()
        }}
      >
        <div className="form-row">
          <label className="field field-narrow">
            Kind
            <input value={kind} onChange={(e) => setKind(e.target.value)} placeholder="note" />
          </label>
          <label className="field">
            Remember this
            <input
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="e.g. I prefer research reports in Bengali"
              required
            />
          </label>
        </div>
        <button type="submit" className="btn btn-primary" disabled={busy || !content.trim()}>
          Add to memory
        </button>
      </form>

      {items.length === 0 ? (
        <p className="muted">No memory items yet. Items you add are stored on the server under your account only.</p>
      ) : (
        <ul className="memory-list">
          {items.map((item) => (
            <li key={item.id} className="card memory-item">
              <div className="memory-head">
                <span className="badge badge-mid">{item.kind}</span>
                <span className="muted small">{formatDate(item.created_at)}</span>
                <button
                  type="button"
                  className="btn btn-small btn-danger"
                  onClick={() => void remove(item.id)}
                >
                  Delete
                </button>
              </div>
              <p>{item.content}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import {
  deleteKey,
  getChatModels,
  getModelSettings,
  listKeys,
  storeKey,
  type ChatModels,
  type ModelSettings,
  type StoredKey,
} from '../api'
import { useAuth } from '../auth'
import { ErrorNotice, SignInPrompt, formatDate } from '../components'

export default function SettingsView() {
  const { user } = useAuth()
  const [models, setModels] = useState<ModelSettings | null>(null)
  const [chatModels, setChatModels] = useState<ChatModels | null>(null)
  const [keys, setKeys] = useState<StoredKey[]>([])
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [keysError, setKeysError] = useState<unknown>(null)
  const [savedNote, setSavedNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getModelSettings().then(setModels).catch((err: unknown) => setError(err))
    getChatModels().then(setChatModels).catch(() => setChatModels(null))
  }, [])

  const loadKeys = useCallback(async () => {
    if (!user) return
    try {
      const res = await listKeys()
      setKeys(res.keys)
    } catch (err) {
      setKeysError(err)
    }
  }, [user])

  useEffect(() => {
    void loadKeys()
  }, [loadKeys])

  const saveKey = async () => {
    if (!provider.trim() || !apiKey || busy) return
    setKeysError(null)
    setSavedNote(null)
    setBusy(true)
    try {
      const saved = await storeKey(provider.trim(), apiKey)
      // The key itself is write-only: clear the input immediately and only
      // ever show the masked last-4 the API returns.
      setApiKey('')
      setProvider('')
      setSavedNote(`Key for “${saved.provider}” stored (ends …${saved.last4}).`)
      await loadKeys()
    } catch (err) {
      setKeysError(err)
    } finally {
      setBusy(false)
    }
  }

  const removeKey = async (providerName: string) => {
    setKeysError(null)
    try {
      await deleteKey(providerName)
      await loadKeys()
    } catch (err) {
      setKeysError(err)
    }
  }

  return (
    <div className="view">
      <ErrorNotice error={error} />

      <div className="card">
        <h3>Model roles (server configuration, read-only)</h3>
        {models ? (
          <>
            <p>
              Gateway:{' '}
              {models.gateway_configured ? (
                <span className="badge badge-high">configured</span>
              ) : (
                <span className="badge badge-low">not configured</span>
              )}{' '}
              <span className="muted small">{models.gateway_base_url || '(no base URL set)'}</span>
            </p>
            {Object.keys(models.roles).length === 0 && (
              <p className="muted">No model roles are configured on the server.</p>
            )}
            <table className="table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Fallback chain (tried in order)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(models.roles).map(([role, chain]) => (
                  <tr key={role}>
                    <td>
                      <strong>{role}</strong>
                    </td>
                    <td>{chain.length > 0 ? chain.join(' → ') : <span className="muted">(empty)</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {chatModels?.gateway_error && (
              <p className="muted small">Gateway check: {chatModels.gateway_error}</p>
            )}
            <p className="muted small">
              Role chains are set by the server operator via MODEL_FAST / MODEL_SMART /
              MODEL_STRATEGIC environment variables — they cannot be changed from the browser,
              and no key values are ever shown here.
            </p>
          </>
        ) : (
          !error && <p className="muted">Loading…</p>
        )}
      </div>

      <div className="card">
        <h3>Your provider API keys</h3>
        {!user ? (
          <SignInPrompt feature="Provider key storage" />
        ) : (
          <>
            <p className="muted small">
              Keys you add are sent once to SHAKIB AI Core and stored Fernet-encrypted under
              your account. The API only ever returns the provider name and the last 4
              characters — a saved key can be replaced or deleted, never read back.
            </p>
            <ErrorNotice error={keysError} />
            {savedNote && <div className="notice notice-info">{savedNote}</div>}
            <form
              className="form-row"
              onSubmit={(e) => {
                e.preventDefault()
                void saveKey()
              }}
            >
              <label className="field">
                Provider
                <input
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  placeholder="e.g. openai"
                  required
                />
              </label>
              <label className="field">
                API key (write-only)
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="Paste key — it will not be shown again"
                  autoComplete="off"
                  required
                />
              </label>
              <button type="submit" className="btn btn-primary" disabled={busy || !provider.trim() || !apiKey}>
                Save key
              </button>
            </form>
            {keys.length === 0 ? (
              <p className="muted">No provider keys stored.</p>
            ) : (
              <ul className="key-list">
                {keys.map((k) => (
                  <li key={k.id} className="key-item">
                    <span>
                      <strong>{k.provider}</strong> · …{k.last4}
                      <span className="muted small"> · added {formatDate(k.created_at)}</span>
                    </span>
                    <button
                      type="button"
                      className="btn btn-small btn-danger"
                      onClick={() => void removeKey(k.provider)}
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  )
}

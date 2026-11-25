import { useState } from 'react'
import { login, register } from '../api'
import { useAuth } from '../auth'
import { ErrorNotice, formatDate } from '../components'

export default function AuthView() {
  const { user, signIn, signOut } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  if (user) {
    return (
      <div className="view">
        <div className="card">
          <h3>Signed in</h3>
          <p>
            <strong>{user.email}</strong>
          </p>
          <p className="muted small">
            User ID {user.user_id}
            {user.created_at && <> · account created {formatDate(user.created_at)}</>}
          </p>
          <button type="button" className="btn" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>
    )
  }

  const submit = async () => {
    if (busy) return
    setError(null)
    setBusy(true)
    try {
      const res =
        mode === 'login' ? await login(email.trim(), password) : await register(email.trim(), password)
      await signIn(res.access_token)
      setPassword('')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="view">
      <div className="card form-card auth-card">
        <div className="toggle-group" role="group" aria-label="Authentication mode">
          <button
            type="button"
            className={mode === 'login' ? 'toggle active' : 'toggle'}
            onClick={() => setMode('login')}
          >
            Sign in
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'toggle active' : 'toggle'}
            onClick={() => setMode('register')}
          >
            Register
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <label className="field">
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              minLength={8}
              required
            />
          </label>
          <ErrorNotice error={error} />
          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={busy || !email.trim() || password.length < 8}
          >
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <p className="muted small">
          Signing in is optional while the server runs with AUTH_REQUIRED off: chat, research,
          council, files, images and skills work in guest mode; memory, history and provider
          keys are per-user and need an account.
        </p>
      </div>
    </div>
  )
}

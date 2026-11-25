import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { getHealth, type Health } from './api'
import { AuthProvider, useAuth } from './auth'
import AuthView from './views/AuthView'
import ChatView from './views/ChatView'
import CouncilView from './views/CouncilView'
import FilesView from './views/FilesView'
import HistoryView from './views/HistoryView'
import ImagesView from './views/ImagesView'
import MemoryView from './views/MemoryView'
import ResearchView from './views/ResearchView'
import SettingsView from './views/SettingsView'
import SkillsView from './views/SkillsView'

const MODULES = [
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'research', label: 'Deep Research', icon: '🔎' },
  { id: 'council', label: 'Critical Analysis', icon: '⚖️' },
  { id: 'files', label: 'Files', icon: '📄' },
  { id: 'images', label: 'Images', icon: '🖼️' },
  { id: 'memory', label: 'Memory', icon: '🧠' },
  { id: 'skills', label: 'Skills', icon: '🧩' },
  { id: 'history', label: 'History', icon: '🕘' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
  { id: 'auth', label: 'Account', icon: '👤' },
] as const

type ModuleId = (typeof MODULES)[number]['id']

function Shell() {
  const { user, loading, signOut } = useAuth()
  const [active, setActive] = useState<ModuleId>('chat')
  const [navOpen, setNavOpen] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [councilRunId, setCouncilRunId] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then((h) => {
        setHealth(h)
        setHealthError(false)
      })
      .catch(() => setHealthError(true))
  }, [])

  const goCouncil = useCallback((runId: string) => {
    setCouncilRunId(runId)
    setActive('council')
    setNavOpen(false)
  }, [])

  const consumeCouncilRunId = useCallback(() => setCouncilRunId(null), [])

  const navigate = (id: ModuleId) => {
    setActive(id)
    setNavOpen(false)
  }

  const current = MODULES.find((m) => m.id === active)!

  return (
    <div className="shell">
      <header className="topbar">
        <button
          type="button"
          className="btn btn-small nav-toggle"
          aria-label="Toggle navigation"
          onClick={() => setNavOpen((v) => !v)}
        >
          ☰
        </button>
        <span className="topbar-brand">SHAKIB AI</span>
        <span className="topbar-user">{loading ? '…' : user ? user.email : 'Guest'}</span>
      </header>

      <aside className={navOpen ? 'sidebar open' : 'sidebar'}>
        <div className="brand">
          <h1>SHAKIB AI</h1>
          <span className="tagline">Unified Deep Research &amp; All-in-One Agent</span>
        </div>

        <div className="health-box">
          {health ? (
            <>
              <div>
                <span className="dot dot-ok" /> Core v{health.version} online
              </div>
              <div className="muted small">
                Gateway: {health.gateway_configured ? 'configured' : 'not configured'} ·
                Research: {health.research_configured ? 'configured' : 'not configured'} ·
                Auth required: {health.auth_required ? 'yes' : 'no'}
              </div>
            </>
          ) : healthError ? (
            <div>
              <span className="dot dot-bad" /> Core unreachable — views will show the
              connection error until the backend is running.
            </div>
          ) : (
            <div className="muted small">Checking Core…</div>
          )}
        </div>

        <nav>
          {MODULES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={m.id === active ? 'nav-item active' : 'nav-item'}
              onClick={() => navigate(m.id)}
            >
              <span aria-hidden>{m.icon}</span> {m.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          {user ? (
            <>
              <div className="muted small">Signed in as</div>
              <div className="user-email">{user.email}</div>
              <button type="button" className="btn btn-small" onClick={signOut}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <div className="muted small">Guest / dev mode</div>
              <button
                type="button"
                className="btn btn-small btn-primary"
                onClick={() => navigate('auth')}
              >
                Sign in / Register
              </button>
            </>
          )}
        </div>
      </aside>

      <main className="panel">
        <h2>
          {current.icon} {current.label}
        </h2>
        {active === 'chat' && <ChatView />}
        {active === 'research' && <ResearchView onRunCouncil={goCouncil} />}
        {active === 'council' && (
          <CouncilView initialRunId={councilRunId} onConsumedInitialRunId={consumeCouncilRunId} />
        )}
        {active === 'files' && <FilesView />}
        {active === 'images' && <ImagesView />}
        {active === 'memory' && <MemoryView />}
        {active === 'skills' && <SkillsView />}
        {active === 'history' && <HistoryView />}
        {active === 'settings' && <SettingsView />}
        {active === 'auth' && <AuthView />}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}

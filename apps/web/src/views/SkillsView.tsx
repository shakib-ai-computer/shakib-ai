import { useEffect, useState } from 'react'
import { listSkills, type Skill } from '../api'
import { ErrorNotice } from '../components'

function statusBadge(skill: Skill) {
  switch (skill.status) {
    case 'ready':
      return <span className="badge badge-high">ready</span>
    case 'needs_configuration':
      return <span className="badge badge-low">needs configuration</span>
    case 'client_side':
      return <span className="badge badge-mid">client-side (browser)</span>
    default:
      return <span className="badge">{skill.status}</span>
  }
}

export default function SkillsView() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    listSkills()
      .then((res) => {
        if (!cancelled) setSkills(res.skills)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="view">
      <p className="muted">
        Live readiness from the server — a skill is only shown as <em>ready</em> when its
        endpoint would actually work. “Needs configuration” names the exact server
        environment variables that are missing (names only, never values).
      </p>
      <ErrorNotice error={error} />
      {loading && <p className="muted">Loading…</p>}
      <div className="skills-grid">
        {skills.map((skill) => (
          <div key={skill.name} className="card skill-card">
            <div className="skill-head">
              <h3>{skill.name}</h3>
              {statusBadge(skill)}
            </div>
            <p>{skill.description}</p>
            {skill.missing.length > 0 && (
              <p className="muted small">
                Missing on server: {skill.missing.map((m) => <code key={m}>{m} </code>)}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

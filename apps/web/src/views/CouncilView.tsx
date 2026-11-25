import { useEffect, useState } from 'react'
import {
  runCouncil,
  type CouncilMemberResult,
  type CouncilPoint,
  type CouncilResult,
  type ResearchLanguage,
} from '../api'
import { ErrorNotice } from '../components'

// Member key -> the list field the backend returns for it (see
// services/core/app/council.py MEMBER specs).
const MEMBERS: { key: string; title: string; listKey: 'points' | 'findings' | 'scenarios' | 'gaps'; icon: string }[] = [
  { key: 'devils_advocate', title: "Devil's Advocate", listKey: 'points', icon: '😈' },
  { key: 'autopsy', title: 'Autopsy', listKey: 'findings', icon: '🔬' },
  { key: 'red_team', title: 'Red Team', listKey: 'scenarios', icon: '🎯' },
  { key: 'expose', title: 'Expose', listKey: 'gaps', icon: '🔦' },
]

const FIELD_LABELS: Record<string, string> = {
  point: 'Point',
  target_claim: 'Target claim',
  strength: 'Strength',
  issue: 'Issue',
  severity: 'Severity',
  evidence_gap: 'Evidence gap',
  scenario: 'Scenario',
  plausibility: 'Plausibility',
  impact: 'Impact',
  gap: 'Gap',
  why_it_matters: 'Why it matters',
}

function MemberCard({ title, icon, member }: { title: string; icon: string; member: CouncilMemberResult }) {
  const items: CouncilPoint[] =
    member.points ?? member.findings ?? member.scenarios ?? member.gaps ?? []
  return (
    <div className="card council-card">
      <h3>
        {icon} {title}
      </h3>
      {member.status === 'error' ? (
        <div className="notice notice-error">
          <strong>This member failed:</strong> {member.reason ?? 'unknown error'}
        </div>
      ) : (
        <>
          {member.summary && <p>{member.summary}</p>}
          {items.length > 0 && (
            <ul className="council-points">
              {items.map((item, i) => (
                <li key={i}>
                  {Object.entries(item)
                    .filter(([, v]) => v !== undefined && v !== null && v !== '')
                    .map(([k, v]) => (
                      <div key={k}>
                        <strong>{FIELD_LABELS[k] ?? k}:</strong> {String(v)}
                      </div>
                    ))}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

export default function CouncilView({
  initialRunId,
  onConsumedInitialRunId,
}: {
  initialRunId: string | null
  onConsumedInitialRunId: () => void
}) {
  const [mode, setMode] = useState<'run' | 'text'>('run')
  const [runId, setRunId] = useState('')
  const [reportText, setReportText] = useState('')
  const [language, setLanguage] = useState<ResearchLanguage>('en')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [result, setResult] = useState<CouncilResult | null>(null)

  // Arriving from the Research view's "Run Council" shortcut.
  useEffect(() => {
    if (initialRunId) {
      setMode('run')
      setRunId(initialRunId)
      onConsumedInitialRunId()
    }
  }, [initialRunId, onConsumedInitialRunId])

  const submit = async () => {
    if (running) return
    if (mode === 'run' && !runId.trim()) return
    if (mode === 'text' && !reportText.trim()) return
    setError(null)
    setRunning(true)
    try {
      const res = await runCouncil(
        mode === 'run'
          ? { run_id: runId.trim(), language }
          : { report_markdown: reportText, sources: [], language },
      )
      setResult(res)
    } catch (err) {
      setError(err)
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="view">
      <p className="muted">
        Four adversarial passes over a report: Devil's Advocate argues against it, Autopsy
        dissects its reasoning, Red Team attacks it, Expose surfaces what it leaves out. The
        council output is a separate analysis — it never edits the report.
      </p>
      <form
        className="card form-card"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <div className="toggle-group" role="group" aria-label="Council input">
          <button
            type="button"
            className={mode === 'run' ? 'toggle active' : 'toggle'}
            onClick={() => setMode('run')}
          >
            By research run ID
          </button>
          <button
            type="button"
            className={mode === 'text' ? 'toggle active' : 'toggle'}
            onClick={() => setMode('text')}
          >
            Paste report text
          </button>
        </div>
        {mode === 'run' ? (
          <label className="field">
            Research run ID
            <input
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              placeholder="e.g. 20261120T123456Z-ab12cd34"
            />
          </label>
        ) : (
          <label className="field">
            Report text (Markdown)
            <textarea
              value={reportText}
              onChange={(e) => setReportText(e.target.value)}
              rows={10}
              placeholder="Paste the report to analyse…"
            />
          </label>
        )}
        <label className="field">
          Analysis language
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as ResearchLanguage)}
          >
            <option value="en">English</option>
            <option value="bn">বাংলা</option>
          </select>
        </label>
        <button type="submit" className="btn btn-primary" disabled={running}>
          {running ? 'Council is deliberating…' : 'Run Critical Analysis'}
        </button>
      </form>

      <ErrorNotice error={error} />

      {result && (
        <div>
          <p className="muted small">
            {result.run_id && <>Run: {result.run_id} · </>}
            Language: {result.language}
            {result.generated_by_role && <> · Generated by role: {result.generated_by_role}</>}
          </p>
          <div className="council-grid">
            {MEMBERS.map((m) => {
              const member = result.members[m.key]
              return member ? (
                <MemberCard key={m.key} title={m.title} icon={m.icon} member={member} />
              ) : (
                <div key={m.key} className="card council-card">
                  <h3>
                    {m.icon} {m.title}
                  </h3>
                  <div className="notice notice-error">Member missing from the response.</div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

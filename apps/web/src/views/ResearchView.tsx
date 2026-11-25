import { useState } from 'react'
import {
  downloadExport,
  runResearch,
  type ExportFormat,
  type ResearchLanguage,
  type ResearchResult,
} from '../api'
import { ErrorNotice, MicButton, ReadAloudButton } from '../components'
import { Markdown } from '../markdown'
import { useDictation, type SpeechLang } from '../voice'

const REPORT_TYPES = [
  { id: 'research_report', label: 'Research report' },
  { id: 'resource_report', label: 'Resource report' },
  { id: 'detailed_report', label: 'Detailed report' },
]

function scoreClass(score: number): string {
  if (score >= 75) return 'badge badge-high'
  if (score >= 50) return 'badge badge-mid'
  return 'badge badge-low'
}

export default function ResearchView({
  onRunCouncil,
}: {
  onRunCouncil: (runId: string) => void
}) {
  const [query, setQuery] = useState('')
  const [language, setLanguage] = useState<ResearchLanguage>('en')
  const [reportType, setReportType] = useState('research_report')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [exportError, setExportError] = useState<unknown>(null)
  const [result, setResult] = useState<ResearchResult | null>(null)

  const dictation = useDictation((text) =>
    setQuery((prev) => (prev ? `${prev} ${text}` : text)),
  )
  const speechLang: SpeechLang = language === 'bn' ? 'bn-BD' : 'en-US'

  const submit = async () => {
    if (query.trim().length < 3 || running) return
    setError(null)
    setExportError(null)
    setRunning(true)
    try {
      setResult(await runResearch(query.trim(), language, reportType))
    } catch (err) {
      setError(err)
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  const exportAs = async (format: ExportFormat) => {
    if (!result) return
    setExportError(null)
    try {
      await downloadExport(result.run_id, format)
    } catch (err) {
      setExportError(err)
    }
  }

  const contradiction = result?.contradiction

  return (
    <div className="view">
      <form
        className="card form-card"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <label className="field">
          Research question
          <div className="input-with-mic">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="What should SHAKIB AI research in depth?"
              rows={3}
              required
              minLength={3}
            />
            <MicButton
              supported={dictation.supported}
              listening={dictation.listening}
              onToggle={() =>
                dictation.listening ? dictation.stop() : dictation.start(speechLang)
              }
            />
          </div>
        </label>
        {dictation.error && <div className="notice notice-error">{dictation.error}</div>}
        <div className="form-row">
          <label className="field">
            Report language
            <div className="toggle-group" role="group" aria-label="Report language">
              <button
                type="button"
                className={language === 'en' ? 'toggle active' : 'toggle'}
                onClick={() => setLanguage('en')}
              >
                English
              </button>
              <button
                type="button"
                className={language === 'bn' ? 'toggle active' : 'toggle'}
                onClick={() => setLanguage('bn')}
              >
                বাংলা
              </button>
            </div>
          </label>
          <label className="field">
            Report type
            <select value={reportType} onChange={(e) => setReportType(e.target.value)}>
              {REPORT_TYPES.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button type="submit" className="btn btn-primary" disabled={running || query.trim().length < 3}>
          {running ? 'Researching… (this can take a while)' : 'Run deep research'}
        </button>
      </form>

      <ErrorNotice error={error} />

      {result && (
        <div className="research-result">
          <div className="result-toolbar">
            <span className="muted small">Run ID: {result.run_id}</span>
            <div className="toolbar-actions">
              <ReadAloudButton text={result.report_markdown} lang={speechLang} />
              <button type="button" className="btn btn-small" onClick={() => void exportAs('md')}>
                ⬇ Markdown
              </button>
              <button type="button" className="btn btn-small" onClick={() => void exportAs('docx')}>
                ⬇ DOCX
              </button>
              <button type="button" className="btn btn-small" onClick={() => void exportAs('pdf')}>
                ⬇ PDF
              </button>
              <button
                type="button"
                className="btn btn-small btn-accent"
                onClick={() => onRunCouncil(result.run_id)}
              >
                ⚖ Run Council on this report
              </button>
            </div>
          </div>
          <ErrorNotice error={exportError} label="Export" />

          <div className="card">
            <Markdown text={result.report_markdown} />
          </div>

          {contradiction && (
            <div className="card">
              <h3>Contradiction check</h3>
              <p>
                Status:{' '}
                <span
                  className={
                    contradiction.status === 'ok'
                      ? 'badge badge-high'
                      : contradiction.status === 'skipped'
                        ? 'badge badge-mid'
                        : 'badge badge-low'
                  }
                >
                  {contradiction.status}
                </span>
                {typeof contradiction.claims_checked === 'number' &&
                  ` · ${contradiction.claims_checked} claims checked`}
              </p>
              {contradiction.reason && <p className="muted">{contradiction.reason}</p>}
              {contradiction.contradictions && contradiction.contradictions.length > 0 ? (
                <ul>
                  {contradiction.contradictions.map((pair, i) => (
                    <li key={i}>
                      <strong>“{pair.claim_a}”</strong> vs <strong>“{pair.claim_b}”</strong>
                      <br />
                      <span className="muted">{pair.explanation}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                contradiction.status === 'ok' && <p className="muted">No contradictions found.</p>
              )}
            </div>
          )}

          <div className="card">
            <h3>Sources ({result.sources.length})</h3>
            {result.sources.length === 0 && <p className="muted">No sources returned.</p>}
            <ul className="source-list">
              {result.sources.map((s, i) => (
                <li key={i} className="source-item">
                  <div className="source-head">
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.title || s.url}
                    </a>
                    {typeof s.credibility_score === 'number' && (
                      <span className={scoreClass(s.credibility_score)}>
                        credibility {s.credibility_score}/100
                      </span>
                    )}
                  </div>
                  <div className="muted small">{s.url}</div>
                  {s.credibility_reasons && s.credibility_reasons.length > 0 && (
                    <div className="muted small">{s.credibility_reasons.join(' · ')}</div>
                  )}
                </li>
              ))}
            </ul>
            <p className="muted small">
              Credibility scores are transparent heuristics (domain type, HTTPS, independent
              corroboration) — signals for prioritising reading, not truth verdicts.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

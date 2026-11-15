import { useEffect, useRef, useState, type SubmitEvent } from 'react'
import {
  analyze,
  ApiError,
  getAnalysis,
  getSessionId,
  listAnalyses,
  MAX_INPUT_CHARS,
  type AnalysisResult,
  type AnalysisSummary,
} from './api'
import { History } from './components/History'
import { Results } from './components/Results'
import './App.css'

const sessionId = getSessionId()

export default function App() {
  const [jd, setJd] = useState('')
  const [resume, setResume] = useState('')
  const [loading, setLoading] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [history, setHistory] = useState<AnalysisSummary[]>([])
  const resultsRef = useRef<HTMLDivElement>(null)

  async function refreshHistory() {
    try {
      setHistory(await listAnalyses(sessionId))
    } catch {
      // History is a convenience; the main flow still works without it.
    }
  }

  // Load this browser's past analyses once (fetch = external system, so an effect is right).
  useEffect(() => {
    let cancelled = false
    listAnalyses(sessionId)
      .then((items) => !cancelled && setHistory(items))
      .catch(() => {}) // history is a convenience; the main flow works without it
    return () => {
      cancelled = true
    }
  }, [])

  // Tick the "Analyzing… Ns" counter while a request is in flight.
  useEffect(() => {
    if (!loading) return
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [loading])

  function showResult(r: AnalysisResult) {
    setResult(r)
    requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  async function onSubmit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setElapsed(0)
    setLoading(true)
    try {
      showResult(await analyze(sessionId, jd, resume))
      void refreshHistory()
    } catch (err) {
      setError(describe(err))
    } finally {
      setLoading(false)
    }
  }

  async function onSelectHistory(id: string) {
    setError(null)
    try {
      showResult(await getAnalysis(id))
    } catch (err) {
      setError(describe(err))
    }
  }

  const tooLong = jd.length > MAX_INPUT_CHARS || resume.length > MAX_INPUT_CHARS
  const canSubmit = jd.trim() !== '' && resume.trim() !== '' && !tooLong && !loading

  return (
    <div className="app">
      <header className="app-header">
        <h1>resume-gap</h1>
        <p className="muted">
          See which job requirements your resume backs up — with the exact line as proof — and what to build for the rest.
        </p>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <form className="inputs" onSubmit={onSubmit}>
            <TextBox label="Job description" value={jd} onChange={setJd} placeholder="Paste the full job posting" />
            <TextBox label="Your resume" value={resume} onChange={setResume} placeholder="Paste your resume as plain text" />
            <button type="submit" className="button-primary" disabled={!canSubmit}>
              {loading ? `Analyzing… ${elapsed}s` : 'Analyze'}
            </button>
            {loading && <p className="muted small">Usually takes 10–20 seconds.</p>}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
          </form>
          <History items={history} activeId={result?.id ?? null} onSelect={onSelectHistory} />
        </aside>

        <main className="main" ref={resultsRef}>
          {result ? (
            <Results result={result} />
          ) : (
            <div className="placeholder">
              <p>Paste a job description and your resume, then hit Analyze.</p>
              <p className="muted small">
                Your text is sent to Google's Gemini API to run the analysis. Leave out your name and contact details.
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

function TextBox({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  const over = value.length > MAX_INPUT_CHARS
  return (
    <label className="textbox">
      <span className="textbox-label">
        {label}
        <span className={`counter ${over ? 'over' : ''}`}>
          {value.length.toLocaleString()} / {MAX_INPUT_CHARS.toLocaleString()}
        </span>
      </span>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} rows={10} />
    </label>
  )
}

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'The AI model is busy right now (rate limit). Wait about a minute and try again.'
    return err.message
  }
  return 'Something went wrong. Please try again.'
}
